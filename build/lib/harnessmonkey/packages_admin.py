"""Package-install admin surface for the `add-patch` / `add-option` / `add-prompt` CLI verbs.

This module never activates/enables anything it installs: `add_package` only copies a
validated package into the per-kind bucket under the HarnessMonkey state dir
(`~/.harnessmonkey/{patches,prompts,options}/<manifest.id>/`). It never touches
`config.json` or `active_profile`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from harnessmonkey.package_model import (
    PackageKind,
    PackageManifest,
    PackageValidationError,
    load_package_manifest,
    validate_package_id,
)

_BUCKETS = {"patch": "patches", "prompt": "prompts", "option": "options"}


def _envelope(ok: bool, summary: str, *, code: str | None = None, warnings=None) -> dict:
    return {
        "schemaVersion": 1, "ok": ok, "status": "ok" if ok else "error",
        "summary": summary,
        "error": None if ok else {"message": summary, "code": code},
        "warnings": list(warnings or []),
    }


def invalid_package_error(message: str) -> dict:
    """Public helper so CLI handlers can emit the same 6-key envelope shape used
    by `add_package` for `invalid_package` failures detected before `add_package`
    is even called (e.g. a missing source file, or an invalid `--id`)."""
    return _envelope(False, message, code="invalid_package")


def _reject_symlinks(root: Path) -> None:
    """Reject a package source tree containing any symlink.

    `shutil.copytree` (used both for the id-rename staging copy and the final
    install copy) dereferences symlinks by default: a symlink pointing outside the
    package (e.g. at `~/.ssh/id_rsa`) would have its *content* silently copied into
    both places. Phase-1's own validation (`_package_local_path`,
    package_model.py:211-223) only checks that manifest-*referenced* local paths
    resolve inside the package directory after following symlinks — it does not
    walk the whole tree, and nothing in package_model.py explicitly permits
    symlinks anywhere in a package. In the absence of an explicit phase-1
    allowance, we treat any symlink inside a package source tree as invalid.
    """
    if root.is_symlink():
        raise PackageValidationError("package_contains_symlink")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PackageValidationError("package_contains_symlink")


class _KindMismatch(Exception):
    """Raised by `_load_manifest` when the manifest's own kind differs from the target.

    Carries the manifest's actual (validated) kind so `add_package` can report the
    binding `kind_mismatch` error code instead of the generic `invalid_package` one.
    """

    def __init__(self, actual_kind: PackageKind) -> None:
        super().__init__(f"kind {actual_kind.value!r} does not match target")
        self.actual_kind = actual_kind


def _peek_kind_and_id(package_dir: Path) -> tuple[str | None, str | None]:
    """Best-effort, non-validating peek at a `*.json` manifest candidate's raw fields.

    This does NOT reimplement any of the schema/slug/local-path enforcement that
    `package_model.load_package_manifest` performs (see `_load_manifest` below) — it
    only reads `kind` and `id` so `_load_manifest` can (a) pick the correct
    `expected_kind` to hand to the real validator and (b) decide whether the source
    folder needs to be staged under an id-named directory before validating (see
    below).

    Mirrors `load_package_manifest`'s own multi-candidate scan (it globs every
    `*.json` file and accepts the folder as long as exactly one candidate
    parses+validates): here we look at every `*.json` file, keep the ones that
    parse as a JSON object with both `kind` and `id` present as strings, and only
    return a peeked pair when exactly one candidate qualifies. Any other outcome
    (no manifest, no unambiguous candidate, bad JSON, non-dict payload) yields
    `(None, None)` and lets the real validator surface the error.
    """
    json_paths = sorted(path for path in package_dir.glob("*.json") if path.is_file())
    candidates: list[tuple[str, str]] = []
    for json_path in json_paths:
        try:
            with json_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        raw_kind = data.get("kind")
        raw_id = data.get("id")
        if isinstance(raw_kind, str) and isinstance(raw_id, str):
            candidates.append((raw_kind, raw_id))
    if len(candidates) != 1:
        return None, None
    return candidates[0]


def _load_manifest(package_dir: Path, kind: str) -> PackageManifest:
    """Validate `package_dir` by delegating to the phase-1 loader.

    Real validation (schema, id slug, kind enum, exactly-one-manifest, in-package
    local paths, sha256 shapes, id/folder-slug match, prompt/option/patch field
    shape, etc.) is entirely performed by
    `harnessmonkey.package_model.load_package_manifest` (package_model.py:429), which
    itself requires an `expected_kind: PackageKind` and raises
    `PackageValidationError` (a `ValueError` subclass, package_model.py:45-46) on any
    failure. This function does not reimplement any of that.

    Two small wrinkles handled here, both using the non-validating peek above purely
    to route into that real validator correctly:

    1. `load_package_manifest`'s own kind-mismatch failure mode is the generic
       `_fail("kind_must_match_bucket")` (package_model.py:395-396), which would be
       indistinguishable from any other `invalid_package` failure. The binding
       contract for `add_package` requires a distinct `kind_mismatch` error code.
       So we peek the manifest's own `kind` field to pick the *manifest's own* kind
       as `expected_kind` for the real validator (so a well-formed manifest of a
       different kind still validates successfully), then compare the validated
       result's kind against the caller's target `kind` afterward and raise
       `_KindMismatch` if they differ. If the peek can't determine a kind, we fall
       back to the caller's target kind and let `PackageValidationError` surface
       naturally as `invalid_package`.
    2. `load_package_manifest_from_dict` requires the manifest's `id` to equal the
       package directory's basename (`id_must_match_folder`,
       package_model.py:390-393) — a check aimed at already-installed packages
       (`~/.harnessmonkey/<bucket>/<id>/`), not arbitrary source directories being
       installed. `add_package` is specified to accept a source directory named
       differently from the manifest id (renaming it into place with a warning), so
       when the peeked `id` differs from `package_dir.name`, we stage a throwaway
       copy of the source under a temp directory named after the peeked id purely
       so the real validator's folder-slug check passes; the original `source`
       passed to `add_package` is untouched and is what actually gets copied to the
       final destination.

    Security note (Critical-1 fix): the peeked `id` is attacker-controlled raw JSON
    content and MUST be validated with phase-1's own slug rule
    (`package_model.validate_package_id`) *before* it is ever used to build a
    filesystem path. `validate_package_id` requires the value to match
    `^[a-z0-9][a-z0-9._-]*$` — a value satisfying that pattern can never contain
    `/` and can never be exactly `..` (its first character must be alphanumeric),
    so it can never traverse out of, or replace, the staging tempdir when joined
    onto it with `Path.__truediv__`. If the peeked id fails that check, staging is
    skipped entirely (no path is built from it, no tempdir is even created for it)
    and the *unmodified* `package_dir` is handed to the real validator instead,
    which will independently re-derive the same raw id from the manifest and reject
    it with its own `id_invalid_slug` failure — surfacing as `invalid_package` with
    zero filesystem writes.
    """
    target_kind = PackageKind(kind)
    peeked_kind_raw, peeked_id = _peek_kind_and_id(package_dir)

    try:
        expected_kind = PackageKind(peeked_kind_raw) if peeked_kind_raw else target_kind
    except ValueError:
        expected_kind = target_kind

    needs_staging = False
    if peeked_id and peeked_id != package_dir.name:
        try:
            validate_package_id(peeked_id)
            needs_staging = True
        except PackageValidationError:
            # Invalid id (path traversal, absolute path, empty, etc.) — never build
            # a path from it. Fall through to validating the original package_dir
            # directly; the real validator will raise its own id-slug failure.
            needs_staging = False

    if needs_staging:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve()
            staged = tmp_root / peeked_id
            # Defense-in-depth: even though `validate_package_id` above already
            # guarantees `peeked_id` cannot escape `tmp_root` when joined, refuse
            # to proceed if it somehow did.
            if not staged.resolve(strict=False).is_relative_to(tmp_root):
                raise PackageValidationError("package_path_escape")
            shutil.copytree(package_dir, staged)
            manifest = load_package_manifest(staged, expected_kind)
    else:
        manifest = load_package_manifest(package_dir, expected_kind)

    if manifest.kind != target_kind:
        raise _KindMismatch(manifest.kind)
    return manifest


def _tree_digest(root: Path) -> str:
    """Stable sha256 digest of every file's (relative path, content) under `root`.

    Used to decide whether a would-be overwrite is actually a no-op (identical
    content) so `add_package(..., overwrite=True)` can report "unchanged"
    instead of needlessly recopying. Directory structure beyond file paths
    (e.g. empty dirs) is not represented — packages are defined by their files.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _atomic_replace_dir(new_dir: Path, dest: Path) -> None:
    """Swap `dest` for the fully-populated sibling `new_dir`, atomically per-step.

    Pattern: rename the old `dest` out of the way (fast, same-filesystem rename,
    effectively can't fail), then rename `new_dir` into `dest`'s place. If that
    second rename somehow fails, the backup is renamed straight back so `dest`
    is never left missing or half-written. Mirrors the temp-sibling + rename
    swap pattern used for single files in install.py's `atomic_write_bytes`.
    """
    backup = dest.parent / f".{dest.name}.bak-{uuid.uuid4().hex}"
    os.replace(dest, backup)
    try:
        os.replace(new_dir, dest)
    except Exception:
        os.replace(backup, dest)
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)


def add_package(source: Path, kind: str, home: Path, overwrite: bool = False) -> dict:
    source = Path(source)
    home = Path(home)
    try:
        _reject_symlinks(source)
    except PackageValidationError as exc:
        return _envelope(False, f"invalid package: {exc}", code="invalid_package")

    try:
        manifest = _load_manifest(source, kind)
    except _KindMismatch as exc:
        return _envelope(
            False,
            f"manifest kind {exc.actual_kind.value!r} does not match {kind!r}",
            code="kind_mismatch",
        )
    except Exception as exc:
        return _envelope(False, f"invalid package: {exc}", code="invalid_package")

    package_id = manifest.id
    dest = home / _BUCKETS[kind] / package_id
    warnings = []
    if source.name != package_id:
        warnings.append(f"source basename {source.name!r} renamed to manifest id {package_id!r}")

    if dest.exists():
        if not overwrite:
            return _envelope(
                False, f"package already installed: {package_id}", code="package_exists"
            )
        if _tree_digest(source) == _tree_digest(dest):
            return _envelope(True, f"unchanged {package_id}", warnings=warnings)
        tmp_new = dest.parent / f".{package_id}.new-{uuid.uuid4().hex}"
        try:
            shutil.copytree(source, tmp_new)
            _atomic_replace_dir(tmp_new, dest)
        finally:
            if tmp_new.exists():
                shutil.rmtree(tmp_new, ignore_errors=True)
        return _envelope(True, f"updated {kind} package {package_id}", warnings=warnings)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest)
    return _envelope(True, f"installed {kind} package {package_id}", warnings=warnings)


def _profile_references(package_id: str, kind: str, profile: dict) -> bool:
    if kind == "patch":
        return package_id in (profile.get("patches") or [])
    if kind == "prompt":
        return profile.get("prompt") == package_id
    return package_id in (profile.get("options") or [])


def remove_package(package_id: str, kind: str, home: Path, profile: dict) -> dict:
    """Remove an installed `kind` package (`~/.harnessmonkey/{patches,prompts,options}/<id>/`).

    Refusal is purely about the *active profile* referencing the package (spec:
    protection is for the next build/launch) — build-baked state
    (`activePatchIds`/`builtPatchIds`) never blocks removal.

    Security note (mirrors `add_package`/`_load_manifest`'s Critical-1 fix): unlike
    `add_package`, this function joins attacker-influenced `package_id` into a
    filesystem path and then `shutil.rmtree`s it, which is a *more* dangerous
    primitive than an unwanted `copytree` — an unvalidated traversal id (e.g.
    `"../../etc"`) could delete an arbitrary directory. `package_id` is therefore
    gated through phase-1's `validate_package_id` (same slug rule,
    `^[a-z0-9][a-z0-9._-]*$`) before it is ever used to build `target`.
    """
    home = Path(home)
    try:
        validate_package_id(package_id)
    except PackageValidationError as exc:
        return invalid_package_error(f"invalid package id {package_id!r}: {exc}")

    target = home / _BUCKETS[kind] / package_id
    if not target.is_dir():
        return _envelope(
            False, f"no installed {kind} package: {package_id}", code="package_missing"
        )
    if _profile_references(package_id, kind, profile):
        return _envelope(
            False,
            f"{kind} package {package_id} is referenced by the active profile; "
            "disable/deselect it first",
            code="package_in_use",
        )
    shutil.rmtree(target)
    return _envelope(True, f"removed {kind} package {package_id}")


def scaffold_prompt_package(source_file: Path, package_id: str, name: str | None) -> dict:
    return {
        "schemaVersion": 1, "kind": "prompt", "id": package_id,
        "label": name or package_id, "description": f"Imported from {source_file.name}",
        "prompt": {"mode": "append", "source": {"path": "prompt.md"}},
    }
