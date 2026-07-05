from __future__ import annotations

import json
import os
from pathlib import Path
from time import sleep, time
from typing import Any

from harnessmonkey.authorization import target_needs_authorization
from harnessmonkey.install import (
    OWNER_MARKER,
    _lock_target,
    _unlock_target,
    _version_from_path,
    atomic_write_json,
    cache_source,
    describe_existing,
    gc_source_cache,
    sha256_bytes,
    shim_digest,
)
from harnessmonkey.paths import StatePaths
from harnessmonkey.shim import write_shim
from harnessmonkey.source_discovery import is_managed_launcher_path, meets_plausible_official_size
from harnessmonkey.status import classify_plausible_official_source

# R6 default retention: keep the active install record's rollback digest
# plus the N most recently captured *other* distinct digests.
RETENTION_KEEP_RECENT = 2

# Field evidence (verified twice on a real machine): the official Claude
# installer's own self-heal mechanism re-detects and re-overwrites a
# just-repaired target again within roughly 12-45 seconds. A bounded wait
# this long after the swap, followed by a single re-hash, is enough to catch
# that specific fast-loop case honestly instead of reporting "repaired: true"
# and then silently going stale until the next status refresh. This is
# intentionally short: it is not trying to catch every possible future
# clobber, only the fast, already-observed re-heal window.
REPAIR_REVERT_RECHECK_DELAY_SECONDS = 2.0


class CacheSourceRefused(RuntimeError):
    """Raised by `cache_source_action` for every structured refusal.

    `code` is the machine-readable reason the CLI layer surfaces in its
    error envelope (see `cli.handle_cache_source`).
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class RepairRefused(RuntimeError):
    """Raised by `repair_shim_action` for every structured refusal.

    `code` is the machine-readable reason the CLI layer surfaces in its
    error envelope (see `cli.handle_repair_shim`). Every raise site in this
    module happens *before* any write to `target_path` -- refusal always
    means "the target is untouched" (see `repair_shim_action`'s own
    docstring for the I1 nuance: a late refusal can still follow a record
    write, but never a target write).
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _file_sha256(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def _matches_installed_shim_digest(digest: str, state_dir: Path) -> bool:
    """C1: does `digest` match the digest of the shim HarnessMonkey would
    render right now for `state_dir`? Mirrors the comparison status.py's own
    detection performs (status.py:441-444, `expected_shim_digest ==
    detected_digest`) -- reused here so `cache_source_action`/
    `repair_shim_action` never mistake an intact, still-correctly-installed
    managed shim for "a plausible official source" just because it lives
    outside HarnessMonkey's own managed bin/versions roots.
    """
    return digest == shim_digest(state_dir)


def _current_target_digest(target_path: Path) -> str | None:
    """Resolve+hash `target_path` directly, deliberately bypassing
    `classify_plausible_official_source` (and its size floor).

    The rendered HarnessMonkey shim script is always far smaller than
    `MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES`, so the CMux-incident size floor
    would otherwise make an intact, still-correctly-installed managed shim
    fail classification for the wrong reason ("too small") before the C1
    already-installed digest check ever runs -- masking that specific,
    already-established refusal behind a generic small-target refusal. This
    helper lets the C1 check in `cache_source_action`/`repair_shim_action`
    run first, exactly as it always has, regardless of the floor.
    """
    try:
        resolved = target_path.resolve(strict=True)
    except OSError:
        return None
    if not (resolved.is_file() and os.access(resolved, os.X_OK)):
        return None
    return _file_sha256(resolved)


def _refusal_code_for_unclassified_target(target_path: Path, paths: StatePaths) -> str:
    """Only used for CacheSourceRefused/RepairRefused messaging: re-derives
    *why* `classify_plausible_official_source` returned None, without
    changing the classification decision itself.

    "target_too_small" is the CMux-incident case: a real, non-managed,
    executable file that simply isn't big enough to plausibly be the real
    Claude binary (see `source_discovery.MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES`).
    """
    try:
        resolved = target_path.resolve(strict=True)
    except OSError:
        return "target_unavailable"
    if not (resolved.is_file() and os.access(resolved, os.X_OK)):
        return "target_unavailable"
    if is_managed_launcher_path(resolved, paths):
        return "managed_path_refused"
    if not meets_plausible_official_size(resolved):
        return "target_too_small"
    return "target_unavailable"


def _read_install_record(record_path: Path) -> dict[str, Any]:
    if not record_path.exists():
        raise RepairRefused("no install record found", code="no_install_record")
    try:
        raw = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RepairRefused(
            f"install record is not readable: {exc}", code="invalid_record"
        ) from exc
    if not isinstance(raw, dict):
        raise RepairRefused("install record is not a JSON object", code="invalid_record")
    return raw


def _active_record_digest(state_dir: Path) -> str | None:
    record_path = state_dir / "install-record.json"
    try:
        raw = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    digest = raw.get("previousSourceSha256")
    return digest if isinstance(digest, str) else None


def cache_source_action(
    target_path: Path, state_dir: Path, paths: StatePaths
) -> dict[str, Any]:
    """spec Sec2 / R1 / R3 / R6: verify a currently-plausible-official
    target and copy it into the single digest-keyed source cache.

    Never touches `target_path`. Raises `CacheSourceRefused` with a
    structured `code` for every refusal path; on success, GCs old cache
    entries per R6 (only ever after this successful new write).
    """
    # C1: refuse before anything else -- before classification, before any
    # size-floor gate -- if the target already IS the correctly installed
    # managed shim (see `_current_target_digest`'s docstring for why this
    # must run ahead of `classify_plausible_official_source`).
    current_digest = _current_target_digest(target_path)
    if current_digest is not None and _matches_installed_shim_digest(current_digest, state_dir):
        raise CacheSourceRefused(
            f"target is already the correctly installed managed shim: {target_path}",
            code="already_installed",
        )

    resolved = classify_plausible_official_source(target_path, paths)
    if resolved is None:
        code = _refusal_code_for_unclassified_target(target_path, paths)
        raise CacheSourceRefused(f"target is not cacheable: {target_path}", code=code)
    detected_digest = _file_sha256(resolved)
    if detected_digest is None:
        raise CacheSourceRefused(f"could not read target: {resolved}", code="copy_failed")
    version = _version_from_path(resolved)

    # R3: re-verify immediately before the copy. A concurrent updater can
    # land between the classification/hash above and this check.
    reresolved = classify_plausible_official_source(target_path, paths)
    recheck_digest = _file_sha256(reresolved) if reresolved is not None else None
    if reresolved != resolved or recheck_digest != detected_digest:
        raise CacheSourceRefused("target changed since detection", code="target_changed")

    try:
        cached = cache_source(resolved, state_dir, version=version)
    except OSError as exc:
        raise CacheSourceRefused(f"failed to cache source: {exc}", code="copy_failed") from exc
    if not cached:
        raise CacheSourceRefused(f"failed to cache source: {resolved}", code="copy_failed")

    active_digest = _active_record_digest(state_dir)
    removed = gc_source_cache(
        state_dir, active_digest=active_digest, keep_recent=RETENTION_KEEP_RECENT
    )
    return {
        "sourcePath": cached["sourcePath"],
        "cachedSourcePath": cached["previousSourceCachePath"],
        "sha256": cached["previousSourceSha256"],
        "sizeBytes": cached["previousSourceSizeBytes"],
        "version": version,
        "gcRemovedDigests": removed,
    }


def repair_shim_action(
    target_path: Path, state_dir: Path, paths: StatePaths
) -> dict[str, Any]:
    """spec Sec3 / R2-R4 / R8: cache-then-swap repair of a managed shim that
    an official update replaced.

    R2: this function performs the repair the moment it is called -- it IS
    the explicit user trigger (see `cli.handle_repair_shim`); nothing in
    `status.py`/detection paths may call it.

    Every precondition through the C1 already-installed gate and the
    authorization gate raises `RepairRefused` before any write of any kind
    (record read is read-only). From the cache-source write onward, a
    refusal can still leave the install record already rewritten (I1: the
    record is written *before* the swap, deliberately -- see the comment
    ahead of the write) -- but the target path itself is never written
    except by the swap, and the swap only happens after every gate below
    passes, so "refusal means the target is untouched" always holds even
    though "refusal means nothing changed at all" no longer does.
    """
    record_path = state_dir / "install-record.json"
    record = _read_install_record(record_path)

    if record.get("owner") != OWNER_MARKER or record.get("targetPath") != str(target_path):
        raise RepairRefused(
            f"install record does not prove {target_path} was previously managed",
            code="not_managed",
        )
    managed_shim_digest = record.get("installedShimSha256")
    if not isinstance(managed_shim_digest, str):
        raise RepairRefused(
            "install record has no managed shim digest to repair from", code="not_managed"
        )

    # C1: before anything else -- before the authorization check, before any
    # caching, before version-probing -- refuse if the current target
    # already IS the correctly installed managed shim. Without this, an
    # intact external shim classifies as "plausible official" (it lives
    # outside HarnessMonkey's own managed bin/versions roots) and repair
    # would cache the shim's own bytes as "the official source" and
    # overwrite the record's true pre-HarnessMonkey rollback data with a
    # description of the shim itself -- permanently destroying the real
    # rollback content and leaving `uninstall-shim` with no way back.
    #
    # This check deliberately runs via `_current_target_digest` -- bypassing
    # `classify_plausible_official_source`'s size floor -- since the
    # rendered shim script is always far smaller than
    # `MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES` and must not be misreported as
    # "target_too_small" ahead of this more specific, already-established
    # "already_installed" refusal (see `_current_target_digest`'s docstring).
    current_digest = _current_target_digest(target_path)
    if current_digest is not None and _matches_installed_shim_digest(current_digest, state_dir):
        raise RepairRefused(
            f"target is already the correctly installed managed shim: {target_path}",
            code="already_installed",
        )

    resolved = classify_plausible_official_source(target_path, paths)
    if resolved is None:
        code = _refusal_code_for_unclassified_target(target_path, paths)
        raise RepairRefused(
            f"current target does not classify as a plausible official source: {target_path}",
            code=code,
        )
    classified_digest = _file_sha256(resolved)
    if classified_digest is None:
        raise RepairRefused(f"could not read target: {resolved}", code="target_unavailable")
    version = _version_from_path(resolved)

    # R8: no elevation, ever, for repair. A protected target re-runs the
    # normal authorizationRequired flow (install-shim) instead -- repair
    # never sudos and never bypasses that prompt based on record contents.
    if target_needs_authorization(target_path):
        raise RepairRefused(
            f"target requires authorization; run install-shim to authorize: {target_path}",
            code="authorization_required",
        )

    # Cache-then-swap (spec Sec2): the currently-replaced target's bytes are
    # cached FIRST -- never rebuild/restore from a live path that may change
    # again mid-operation.
    cached = cache_source(resolved, state_dir, version=version)
    if not cached:
        raise RepairRefused(
            f"failed to cache current target before repair: {resolved}", code="cache_failed"
        )

    # Capture how to restore *this* (newly replaced) official target on a
    # future uninstall -- reuses the exact same primitive a fresh
    # `install_shim_transaction` uses for its own previousType/previousTarget
    # (or previousContentBase64/previousMode) fields, so
    # `restore_install_transaction` needs no changes at all: it only ever
    # reads those fields, never the source-cache fields directly.
    previous_state = describe_existing(target_path)

    # I1: write the new record BEFORE the swap, not after. The prior
    # ordering (swap, then write) left a crash window between the two where
    # the target was already repaired but the record still held pre-repair
    # rollback data -- a later `uninstall-shim` would restore that stale
    # binary. With the record written first: if the process dies before the
    # swap ever runs, the target is untouched and
    # `current_target_is_installed_shim` (the sole gate `uninstall-shim` and
    # status detection use before ever trusting this record's rollback
    # fields) correctly reports "not the shim" from the actual target
    # bytes -- so the new-but-unapplied record is simply inert. If the
    # process dies after the swap, the record was already correct. Either
    # way the on-disk state is self-consistent (R4 + I1).
    new_shim_digest = shim_digest(state_dir)
    new_record = dict(record)
    new_record.pop("previousContentBase64", None)
    new_record.pop("previousMode", None)
    new_record.pop("previousTarget", None)
    new_record.update(previous_state)
    new_record.update(cached)
    new_record["installedShimSha256"] = new_shim_digest
    new_record["timestamp"] = time()
    atomic_write_json(record_path, new_record)

    # R3/I2: re-verify immediately before the swap, with no other I/O on the
    # target path in between (the record write above only touches
    # `record_path`, never `target_path`). If a concurrent official updater
    # landed since the cache write, abort cleanly here -- no partial write,
    # target bytes untouched, next status re-detects. (The record above may
    # already describe content that never got applied to the target on this
    # abort path too -- see the I1 comment: still self-consistent, because
    # nothing acts on the record's rollback fields unless the target's
    # actual bytes match the installed-shim digest, which they never do
    # here.)
    reresolved = classify_plausible_official_source(target_path, paths)
    reresolved_digest = _file_sha256(reresolved) if reresolved is not None else None
    if reresolved != resolved or reresolved_digest != classified_digest:
        raise RepairRefused(
            "target changed since it was classified/cached; aborting repair",
            code="target_changed",
        )

    tmp = target_path.with_suffix(target_path.suffix + ".harnessmonkey.repair.tmp")
    tmp.unlink(missing_ok=True)
    write_shim(tmp, state_dir)
    # Unlock before the swap: defensive, since a target this function is
    # about to repair was just classified/re-verified as a plausible
    # official replacement (i.e. not our locked shim -- a real locked shim
    # can't be replaced by an external actor in the first place, which is
    # the whole point of the shim-lock feature). `was_locked` still gates
    # the abort-path re-lock decision below in case it somehow was ours.
    was_locked = _unlock_target(target_path)
    try:
        tmp.replace(target_path)  # rename within target_path's own directory: atomic swap
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        if was_locked:
            _lock_target(target_path)
        raise RepairRefused(f"failed to swap shim into place: {exc}", code="swap_failed") from exc

    # Fix 1: the swap above is already complete and successful -- "repaired"
    # is (and stays) true regardless of what happens next. This bounded
    # re-check is a NEW step strictly after that transaction, purely to
    # report whether an external actor (observed: the official installer's
    # own self-heal) already clobbered the target again within seconds.
    # Read+hash only -- `_current_target_digest` never executes target_path.
    sleep(REPAIR_REVERT_RECHECK_DELAY_SECONDS)
    reverted_immediately = _current_target_digest(target_path) != new_shim_digest

    # Shim lock (final step, requirement 1) -- deliberately AFTER the
    # revert-recheck above, not before: if the recheck already found the
    # target reverted, there is nothing of ours left at `target_path` to
    # lock -- flagging it would flag someone else's file. Only attempt to
    # lock when our shim is still actually there.
    target_locked = False if reverted_immediately else _lock_target(target_path)

    removed = gc_source_cache(
        state_dir,
        active_digest=cached["previousSourceSha256"],
        keep_recent=RETENTION_KEEP_RECENT,
    )

    return {
        "repaired": True,
        "targetPath": str(target_path),
        "previousOfficialSha256": classified_digest,
        "newOfficialSha256": cached["previousSourceSha256"],
        "newOfficialVersion": version,
        "cachedSourcePath": cached["previousSourceCachePath"],
        "gcRemovedDigests": removed,
        "revertedImmediately": reverted_immediately,
        "targetLocked": target_locked,
    }
