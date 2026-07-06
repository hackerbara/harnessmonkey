from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from time import time

from harnessmonkey import authorization
from harnessmonkey.constants import OWNER_MARKER
from harnessmonkey.progress import StageTracker
from harnessmonkey.shim import write_shim
from harnessmonkey.source_discovery import meets_plausible_official_size

SHIM_STAGES: tuple[tuple[str, str], ...] = (
    ("preflight", "Preflight checks"),
    ("record", "Write install record"),
    ("swap", "Swap shim"),
)


class ProtectedTargetRestoreUnavailable(RuntimeError):
    pass


class TargetNotPlausibleOfficial(RuntimeError):
    """Raised by `install_shim_transaction` when `target_path` currently
    holds a real, readable, executable file that is too small to plausibly
    be a real Claude binary (CMux incident: install-shim previously had no
    classification gate at all here, so pointing it at an unrelated small
    wrapper script silently cached that script as "the official source" to
    preserve/restore -- see `_install_target_fails_plausibility`).
    """


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_VERSION_SEGMENT_RE = re.compile(r"^\d+(?:\.\d+)+$")


def _version_from_path(path: Path) -> str | None:
    """Best-effort version extraction from a resolved source path's own
    versioned-directory layout (e.g. `.../claude/versions/2.1.201/claude`,
    matching the official installer's own directory shape described in the
    spec's "Observed failure mode").

    This NEVER executes `path`. Both `status.py`'s replaced-shim detection
    (called on every `status --json`/GUI refresh) and `repair.py`'s
    cache-source/repair-shim actions need this: running `<path> --version`
    against an unverified path is arbitrary-binary execution whose only
    credential is that the path merely *classifies* as plausible-official
    (see `classify_plausible_official_source`'s own docstring -- that proves
    internal consistency, not provenance). Concretely, when `path` is later
    shown to still be the intact managed shim, `--version` is a management
    token, so running the shim invokes `select_launch_target(...,
    prefer_official=True)` -> `shutil.which("claude")` -> execution of
    whatever `claude` resolves on PATH.

    Per spec R7, extraction failure just means "version unknown" -- it never
    gates anything, so falling back to `None` here is always safe. Lives
    here (rather than in `status.py` or `repair.py`) so both modules can
    import it without a circular import: `repair.py` already imports from
    `status.py` (`classify_plausible_official_source`), so the parser must
    live somewhere `status.py` can import without importing `repair.py` --
    `install.py` imports neither and both already depend on it directly.
    """
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        candidate = parts[index + 1]
        if part == "versions" and _VERSION_SEGMENT_RE.match(candidate):
            return candidate
    return None


def shim_digest(state_dir: Path) -> str:
    return sha256_bytes(_shim_bytes(state_dir))


def _shim_bytes(state_dir: Path) -> bytes:
    from harnessmonkey.shim import render_shim_script

    return render_shim_script(str(state_dir)).encode("utf-8")


def describe_existing(path: Path) -> dict:
    if not path.exists() and not path.is_symlink():
        return {"previousType": "missing"}
    if path.is_symlink():
        return {"previousType": "symlink", "previousTarget": os.readlink(path)}
    data = path.read_bytes()
    return {
        "previousType": "file",
        "previousContentBase64": base64.b64encode(data).decode("ascii"),
        "previousMode": stat.S_IMODE(path.stat().st_mode),
    }


def _existing_managed_record(record_path: Path, target_path: Path) -> dict | None:
    if not record_path.exists():
        return None
    try:
        record = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("targetPath") != str(target_path):
        return None
    try:
        if current_target_is_installed_shim(target_path, record):
            return record
    except OSError:
        return None
    return None


def atomic_write_bytes(path: Path, data: bytes, mode: int) -> None:
    """Write `data` to `path` via temp-file + rename (atomic on same filesystem)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.chmod(mode)
    tmp.replace(path)


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write `payload` to `path` as JSON via temp-file + rename."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def sources_root(state_dir: Path) -> Path:
    return state_dir / "sources"


def cache_source(resolved_source: Path, state_dir: Path, *, version: str | None = None) -> dict:
    """HarnessMonkey's single source-cache mechanism (spec R1).

    Copies `resolved_source`'s bytes into the digest-keyed cache directory
    (`state_dir/sources/<sha256>/claude`), atomically (temp file + rename),
    and writes/refreshes a `source-record.json` sidecar in the same
    directory (path/sha256/sizeBytes/capturedAt/version). This is the same
    directory layout `_cache_previous_source` has always written into --
    generalized here so install-time caching and the explicit
    `cache-source`/`repair-shim` commands write through one place instead of
    a second parallel scheme. `resolve_cached_source`'s read-side containment
    check (`state_dir / "sources"`) is unchanged and keeps working for
    records written before this sidecar existed.
    """
    data = resolved_source.read_bytes()
    digest = sha256_bytes(data)
    digest_dir = sources_root(state_dir) / digest
    digest_dir.mkdir(parents=True, exist_ok=True)
    cache_path = digest_dir / "claude"
    if not cache_path.exists():
        mode = stat.S_IMODE(resolved_source.stat().st_mode) | 0o755
        atomic_write_bytes(cache_path, data, mode)
    record_path = digest_dir / "source-record.json"
    atomic_write_json(
        record_path,
        {
            "path": str(resolved_source),
            "sha256": digest,
            "sizeBytes": len(data),
            "capturedAt": time(),
            "version": version,
        },
    )
    return {
        "sourcePath": str(resolved_source),
        "previousResolvedPath": str(resolved_source),
        "previousSourceCachePath": str(cache_path),
        "previousSourceSha256": digest,
        "previousSourceSizeBytes": len(data),
    }


def _cache_previous_source(target_path: Path, state_dir: Path) -> dict:
    if not (target_path.exists() or target_path.is_symlink()):
        return {}
    try:
        source_path = target_path.resolve(strict=True)
    except OSError:
        return {}
    if not source_path.is_file() or not os.access(source_path, os.X_OK):
        return {}
    return cache_source(source_path, state_dir)


def _read_source_record(digest_dir: Path) -> dict | None:
    try:
        raw = json.loads((digest_dir / "source-record.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _source_record_captured_at(digest_dir: Path) -> float:
    record = _read_source_record(digest_dir)
    if record is None:
        return 0.0
    value = record.get("capturedAt")
    return float(value) if isinstance(value, (int, float)) else 0.0


def gc_source_cache(
    state_dir: Path, *, active_digest: str | None, keep_recent: int = 2
) -> list[str]:
    """R6 retention: never GC `active_digest` (the digest referenced by the
    active install record); of the remaining distinct digests, keep the
    `keep_recent` most recently captured (by source-record.json
    `capturedAt`) and remove the rest. Call only after a successful new
    cache write. Returns the list of removed digests.
    """
    sources_dir = sources_root(state_dir)
    if not sources_dir.exists():
        return []
    digest_dirs = [entry for entry in sources_dir.iterdir() if entry.is_dir()]
    others = [entry for entry in digest_dirs if entry.name != active_digest]
    others.sort(key=_source_record_captured_at, reverse=True)
    to_remove = others[keep_recent:]
    removed: list[str] = []
    for digest_dir in to_remove:
        shutil.rmtree(digest_dir, ignore_errors=True)
        removed.append(digest_dir.name)
    return removed


def resolve_cached_source(record: dict, state_dir: Path) -> Path | None:
    """Verify and return an install record's cached previous-source path.

    The sha256 check only proves internal consistency -- that the cached
    bytes match what was recorded -- it says nothing about *provenance*. A
    hand-edited (or otherwise tampered) record could point
    previousSourceCachePath at an arbitrary file that happens to match a
    likewise hand-edited sha. Containing the resolved path to `state_dir /
    "sources"` -- the only location `_cache_previous_source` ever writes to
    -- keeps such a record from redirecting launch/cleanup at paths outside
    what HarnessMonkey itself manages. This mirrors the same
    same-trust-domain judgment `select_launch_target` already applies to the
    "patched" branch via its `versions_dir` containment check.
    """
    cache_raw = record.get("previousSourceCachePath")
    expected_sha = record.get("previousSourceSha256")
    if not isinstance(cache_raw, str) or not isinstance(expected_sha, str):
        return None
    try:
        cache_path = Path(cache_raw).expanduser().resolve(strict=True)
    except OSError:
        return None
    sources_root = (state_dir / "sources").resolve(strict=False)
    if not cache_path.is_relative_to(sources_root):
        return None
    try:
        if not (
            cache_path.is_file()
            and os.access(cache_path, os.X_OK)
            and sha256_bytes(cache_path.read_bytes()) == expected_sha
        ):
            return None
    except OSError:
        return None
    return cache_path


def clean_source_from_install_record(target_path: Path, record_path: Path) -> Path | None:
    record = _existing_managed_record(record_path, target_path)
    if record is None:
        return None
    cache_path = resolve_cached_source(record, record_path.parent)
    if cache_path is not None:
        return cache_path
    previous_target = record.get("previousTarget")
    if isinstance(previous_target, str):
        try:
            resolved = Path(previous_target).expanduser().resolve(strict=True)
        except OSError:
            return None
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def _privileged_mkdir(path: Path) -> None:
    authorization.run_privileged_argv(
        ["/bin/mkdir", "-p", str(path)],
        reason=f"HarnessMonkey needs permission to create {path}",
    )


def _privileged_replace(tmp_path: Path, target_path: Path) -> None:
    authorization.run_privileged_argv(
        ["/bin/mv", "-f", str(tmp_path), str(target_path)],
        reason=f"HarnessMonkey needs permission to update {target_path}",
    )


def _privileged_remove(target_path: Path) -> None:
    authorization.run_privileged_argv(
        ["/bin/rm", "-f", str(target_path)],
        reason=f"HarnessMonkey needs permission to restore {target_path}",
    )


def _lock_target(target_path: Path) -> bool:
    """Set the macOS/BSD user-immutable flag on `target_path`, as the FINAL
    step after HarnessMonkey has just written its own shim bytes there (see
    `install_shim_transaction`/`repair_shim_action`).

    Evidence (controlled experiment on a real machine, 2026-07-03/04): the
    official Claude installer's own self-heal mechanism re-detects and
    silently re-overwrites a bare (unflagged) shim within roughly 15 seconds
    of any fresh official-claude launch -- its own code swallows the
    resulting EPERM quietly (sessions keep working the whole time), so the
    shim just keeps getting clobbered. Setting `UF_IMMUTABLE` here defeats
    that reverter cleanly and never touches the official installer's own
    download path (those land under `~/.local/share/claude/versions/`, never
    the shim's target path).

    Only ever called immediately after HarnessMonkey itself finished writing
    `target_path`, so HarnessMonkey is always the owner of the bytes it is
    about to flag -- a plain (unprivileged) `os.chflags` call is therefore
    always sufficient here, even for an otherwise-authorization-required
    target directory (root/sudo was needed only to *reach* the directory
    entry, never to own the file this process itself just wrote into it).

    No-op (returns False) on any platform without user-immutable-flag
    support, or if the underlying `chflags` call fails for *any* reason
    (permission, unsupported filesystem, etc.): a locking failure must never
    fail the caller's transaction -- the shim keeps working unlocked, exactly
    as it did before this feature existed. Callers report the returned bool
    honestly (`targetLocked`/`shimLocked`) instead of assuming success.

    Invariant: our shim is always a regular file we just wrote ourselves --
    never a symlink. `Path.stat`/`os.chflags` both follow symlinks by
    default, so if `target_path` is ever a symlink here (e.g. a caller
    handed us the official installer's reasserted symlink, or a `--force`
    path that bypassed the symlink-excluding
    `current_target_is_installed_shim` gate), flagging it would silently set
    UF_IMMUTABLE on whatever the link resolves to -- someone else's file,
    not ours. Bail out first: a symlink is never lockable as "our shim".
    """
    if target_path.is_symlink():
        return False
    if not (sys.platform == "darwin" and hasattr(os, "chflags")):
        return False
    try:
        os.chflags(str(target_path), stat.UF_IMMUTABLE)
    except OSError:
        return False
    return True


def shim_target_is_locked(target_path: Path) -> bool:
    """Read-only: is the macOS/BSD user-immutable flag currently set on
    `target_path`? Never touches file bytes, only `st_flags` -- safe to call
    from any read-only detection path (see `status.py`'s `shimLocked`
    field), locked or not, installed or not. False on any platform without
    `st_flags` support (e.g. Linux) or if the stat call fails for any reason
    (missing file, dangling symlink, permission).

    Invariant: our shim is always a regular file, never a symlink (see
    `_lock_target`'s docstring). `Path.stat()` follows symlinks by default,
    so without this guard a symlink at `target_path` would report whatever
    flag its resolved destination happens to carry -- not meaningful as "is
    this OUR shim locked". Bail out first: a symlink is never ours, so it is
    never reported as locked.
    """
    if target_path.is_symlink():
        return False
    if not (sys.platform == "darwin" and hasattr(os, "chflags")):
        return False
    try:
        flags = target_path.stat().st_flags
    except (OSError, AttributeError):
        return False
    return bool(flags & stat.UF_IMMUTABLE)


def _unlock_target(target_path: Path) -> bool:
    """Lift the user-immutable flag from `target_path` if present, before
    any HarnessMonkey write to it (swap, restore/uninstall, or a rollback --
    see every call site below).

    Returns True only when the flag was actually present AND successfully
    cleared. Callers use this to decide whether `target_path` held *our*
    previously-locked shim: HarnessMonkey only ever flags bytes it wrote
    itself (see `_lock_target`'s docstring), so finding the flag set here
    means the pre-write content was ours -- which drives the abort-path
    re-lock decisions at each call site (still ours and still intact after
    an aborted write -> re-lock; nothing was ours to begin with -> don't).
    Returns False both when there was nothing to unlock (never locked, or a
    non-mac platform) and when the flag was present but the `chflags` call
    itself failed -- either way there is nothing for a caller to
    conditionally re-lock.

    Invariant: our shim is always a regular file, never a symlink (see
    `_lock_target`'s docstring) -- a symlink at `target_path` can never be
    ours to unlock, so there is nothing to do. This is checked explicitly
    here, up front, rather than relying solely on `shim_target_is_locked`'s
    own guard below: both a real installed shim's target and an external
    reassertion (e.g. the official installer's symlink; see
    `repair.py`'s unlock call site and `restore_install_transaction`'s
    `--force` path in install.py) can land here, and neither should ever
    have `chflags` called against it through a link.
    """
    if target_path.is_symlink():
        return False
    if not shim_target_is_locked(target_path):
        return False
    try:
        current_flags = target_path.stat().st_flags
        os.chflags(str(target_path), current_flags & ~stat.UF_IMMUTABLE)
    except OSError:
        return False
    return True


def _write_shim_to_target(target_path: Path, state_dir: Path) -> None:
    # Unlock immediately before the swap, not before building the
    # replacement at its own tmp path: a re-install over an existing
    # HarnessMonkey-locked shim would otherwise fail with EPERM at the swap
    # below, on both the plain and privileged paths (`chflags UF_IMMUTABLE`
    # blocks rename()/unlink() unconditionally, privilege or not, until the
    # flag is explicitly cleared -- verified directly against a real
    # filesystem). Keeping the unlock window as narrow as possible (matching
    # `repair.py`'s equivalent unlock-just-before-swap placement) minimizes
    # how long `target_path` sits unprotected while nothing about writing the
    # tmp file needs it unlocked at all. `was_locked` gates the abort-path
    # re-lock decision if the swap itself then fails below (see
    # `_unlock_target`'s docstring).
    if authorization.target_needs_authorization(target_path):
        tmp = state_dir / (target_path.name + ".harnessmonkey.tmp")
        write_shim(tmp, state_dir)
        _privileged_mkdir(target_path.parent)
        was_locked = _unlock_target(target_path)
        try:
            _privileged_replace(tmp, target_path)
        except Exception:
            if was_locked:
                _lock_target(target_path)
            raise
        return
    tmp = target_path.with_suffix(target_path.suffix + ".harnessmonkey.tmp")
    write_shim(tmp, state_dir)
    was_locked = _unlock_target(target_path)
    try:
        tmp.replace(target_path)
    except Exception:
        if was_locked:
            _lock_target(target_path)
        raise


def _install_tmp_candidates(target_path: Path, state_dir: Path) -> tuple[Path, ...]:
    return (
        state_dir / (target_path.name + ".harnessmonkey.tmp"),
        target_path.with_suffix(target_path.suffix + ".harnessmonkey.tmp"),
    )


def protected_install_requires_refusal(target_path: Path, record_path: Path) -> bool:
    if not authorization.target_needs_authorization(target_path):
        return False
    if not target_path.exists() and not target_path.is_symlink():
        return False
    if record_path.exists():
        try:
            record = json.loads(record_path.read_text())
        except (OSError, json.JSONDecodeError):
            record = None
        if isinstance(record, dict) and current_target_is_installed_shim(target_path, record):
            return False
    return True


def _install_target_fails_plausibility(target_path: Path) -> bool:
    """True when `target_path` currently resolves to a readable, executable
    file that is too small to plausibly be a real Claude binary.

    Only meaningful when there is no existing HarnessMonkey-managed record
    for this exact target (see `install_shim_transaction`'s
    `existing_record` check, which runs first): a legitimate re-install over
    our own already-managed shim is always allowed, no matter how small the
    rendered shim script itself is. A target that is missing or a dangling
    symlink has nothing to validate -- that is the normal first-install
    bootstrap case and is left alone.

    Deliberately does not reuse the full
    `status.classify_plausible_official_source` (which would also exclude
    HarnessMonkey's own managed bin/versions roots -- an unrelated concern for
    an install-over target, and importing it here would create a circular
    import: `status.py` already imports from this module at load time).
    Reuses the same size-only primitive
    (`source_discovery.meets_plausible_official_size`) instead.
    """
    if not (target_path.exists() or target_path.is_symlink()):
        return False
    try:
        resolved = target_path.resolve(strict=True)
    except OSError:
        return False
    if not (resolved.is_file() and os.access(resolved, os.X_OK)):
        return False
    return not meets_plausible_official_size(resolved)


def install_target_not_plausible_official(target_path: Path, record_path: Path) -> bool:
    """Public precondition check shared by `install_shim_transaction` and the
    CLI's `install-shim --dry-run` preview (`cli._dry_run_install_payload`):
    would install-shim currently refuse `target_path` because its existing
    content doesn't look like a real Claude binary (CMux incident fix, see
    `_install_target_fails_plausibility`)?

    Always False when `target_path` already has a HarnessMonkey-managed
    record (a legitimate re-install over our own shim is always allowed).
    """
    if _existing_managed_record(record_path, target_path) is not None:
        return False
    return _install_target_fails_plausibility(target_path)


def install_shim_transaction(
    target_path: Path,
    state_dir: Path,
    dry_run: bool,
    *,
    on_event: Callable[[dict], None] | None = None,
) -> Path:
    tracker = StageTracker(on_event)
    tracker.plan(SHIM_STAGES)
    record_path = state_dir / "install-record.json"
    tracker.start("preflight")
    try:
        if protected_install_requires_refusal(target_path, record_path):
            raise ProtectedTargetRestoreUnavailable(
                "refusing to overwrite protected existing target without safe restore: "
                f"{target_path}"
            )
        existing_record = _existing_managed_record(record_path, target_path)
        if existing_record is None and _install_target_fails_plausibility(target_path):
            raise TargetNotPlausibleOfficial(
                "refusing to install shim over a target that does not look like a real "
                "Claude binary -- it looks too small to be a real Claude app, more like "
                f"another program's launcher: {target_path}"
            )
        previous = (
            {
                key: value
                for key, value in existing_record.items()
                if key.startswith("previous") or key == "sourcePath"
            }
            if existing_record is not None
            else describe_existing(target_path)
        )
    except (ProtectedTargetRestoreUnavailable, TargetNotPlausibleOfficial) as exc:
        tracker.fail(str(exc))
        raise
    tracker.done()
    if dry_run:
        return record_path
    tracker.start("record")
    state_dir.mkdir(parents=True, exist_ok=True)
    if existing_record is None:
        previous.update(_cache_previous_source(target_path, state_dir))
    record = {
        "owner": OWNER_MARKER,
        "targetPath": str(target_path),
        "stateDir": str(state_dir),
        "timestamp": time(),
        "installedShimSha256": shim_digest(state_dir),
        **previous,
    }
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    tracker.done()
    tracker.start("swap")
    try:
        _write_shim_to_target(target_path, state_dir)
    except Exception as exc:
        tracker.fail(str(exc))
        record_path.unlink(missing_ok=True)
        for tmp in _install_tmp_candidates(target_path, state_dir):
            tmp.unlink(missing_ok=True)
        raise
    tracker.done()
    # Lock after write (final step, requirement 1): see `_lock_target`'s
    # docstring for the field evidence. The outcome is recorded as an
    # additive `targetLocked` field on the install record itself (rather
    # than changing this function's return type) so `install-shim --json`
    # can report it honestly -- every existing caller/test relies on
    # `install_shim_transaction` returning `record_path`, not a richer
    # result type.
    target_locked = _lock_target(target_path)
    record["targetLocked"] = target_locked
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record_path


def current_target_is_installed_shim(target_path: Path, record: dict) -> bool:
    if target_path.is_symlink() or not target_path.exists():
        return False
    state_dir = record.get("stateDir")
    if not isinstance(state_dir, str):
        return False
    expected = shim_digest(Path(state_dir))
    return isinstance(expected, str) and sha256_bytes(target_path.read_bytes()) == expected


def restore_install_transaction(
    target_path: Path,
    record_path: Path,
    force: bool,
    *,
    on_event: Callable[[dict], None] | None = None,
) -> bool:
    tracker = StageTracker(on_event)
    tracker.plan(SHIM_STAGES)
    tracker.start("preflight")
    if not record_path.exists():
        tracker.fail("no install record")
        return False
    record = json.loads(record_path.read_text())
    if record.get("owner") != OWNER_MARKER and not force:
        tracker.fail("record owned by another tool")
        return False
    if record.get("targetPath") != str(target_path) and not force:
        tracker.fail("target is not the managed shim")
        return False
    if not force and not current_target_is_installed_shim(target_path, record):
        tracker.fail("target is not the managed shim")
        return False
    tracker.done()

    tracker.start("record")
    previous_type = record.get("previousType")
    needs_authorization = authorization.target_needs_authorization(target_path)
    if previous_type not in {"missing", "symlink", "file"}:
        tracker.fail("unsupported previous type")
        return False
    tracker.done()

    tracker.start("swap")
    # Unlock before any of our own writes below (missing/symlink/file
    # branches and the privileged remove) -- see `_unlock_target`'s
    # docstring. `was_locked` gates the abort-path re-lock decisions: if the
    # flag was ours (True) and the restore itself then fails, the target is
    # still intact (still our shim -- unlink()/replace() are atomic
    # all-or-nothing) so re-lock it. Uninstall's own SUCCESS path
    # deliberately never re-locks (requirement 6): it restores the ORIGINAL
    # target, which was never ours to flag.
    was_locked = _unlock_target(target_path)
    if needs_authorization:
        # The install record lives in the user-writable state directory. For a
        # protected target, do not let that mutable record drive elevated writes
        # of file bytes or symlink destinations. The narrow privileged operation
        # for protected uninstall is remove-only; richer restore can be added
        # later with integrity protected prior-payload storage.
        try:
            _privileged_remove(target_path)
        except Exception:
            if was_locked:
                _lock_target(target_path)
            raise
        tracker.done()
        return True
    if previous_type == "missing":
        try:
            target_path.unlink(missing_ok=True)
        except OSError:
            if was_locked:
                _lock_target(target_path)
            raise
    elif previous_type == "symlink":
        tmp = record_path.parent / (target_path.name + ".restore.symlink.tmp")
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(record["previousTarget"])
        try:
            tmp.replace(target_path)
        except Exception as exc:
            tracker.fail(str(exc))
            tmp.unlink(missing_ok=True)
            if was_locked:
                _lock_target(target_path)
            raise
    elif previous_type == "file":
        content = base64.b64decode(record["previousContentBase64"].encode("ascii"), validate=True)
        tmp = (
            record_path.parent / (target_path.name + ".restore.tmp")
            if needs_authorization
            else target_path.with_suffix(target_path.suffix + ".restore.tmp")
        )
        tmp.write_bytes(content)
        tmp.chmod(int(record.get("previousMode", 0o755)))
        try:
            tmp.replace(target_path)
        except Exception as exc:
            tracker.fail(str(exc))
            tmp.unlink(missing_ok=True)
            if was_locked:
                _lock_target(target_path)
            raise
    tracker.done()
    return True


def use_official(current_path: Path, official_path: Path) -> None:
    current_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = current_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(official_path)
    tmp.replace(current_path)
