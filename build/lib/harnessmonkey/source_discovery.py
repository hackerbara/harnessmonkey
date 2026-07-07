from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from harnessmonkey.config import HarnessMonkeyConfig
from harnessmonkey.constants import OWNER_MARKER
from harnessmonkey.paths import StatePaths
from harnessmonkey.platform_support import (
    claude_executable_name,
    is_executable_file,
    is_windows,
    windows_claude_install_candidates,
)


@dataclass(frozen=True)
class SourceIdentity:
    path: Path
    kind: str


# CMux incident (field evidence, 2026-07): `install-shim` pointed at an
# unrelated tool's bundled wrapper script (an 8KB bash script at
# `/Applications/cmux.app/.../bin/claude`, nothing to do with HarnessMonkey)
# was silently classified as "a plausible official Claude source" purely
# because it was *some* executable file that wasn't one of HarnessMonkey's own
# managed paths -- it was cached and swapped in as if it were the real thing.
# The real Anthropic `claude` binary is ~230MB (a live install record showed
# `previousSourceSizeBytes: 231708784`). 50MB is a generous margin below that
# real size, while staying safely above any wrapper/shim script (the CMux
# incident's file was 8KB) -- cheap to check via a single `stat()` call, no
# execution of the candidate ever required or allowed.
MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES = 50 * 1024 * 1024


def meets_plausible_official_size(path: Path) -> bool:
    """Cheap, offline size-floor check: does `path` stat at or above the
    minimum size a real Claude binary could plausibly be?

    Filesystem stat only -- never reads or executes `path`. Callers combine
    this with their own existence/executable-bit/managed-path checks (see
    `status.classify_plausible_official_source` and
    `install.py`'s install-shim precondition, both of which apply this same
    floor to different candidate paths).
    """
    try:
        return path.stat().st_size >= MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES
    except OSError:
        return False


def _resolve_existing_executable(candidate: str | Path | None) -> Path | None:
    if candidate is None:
        return None
    try:
        path = Path(candidate).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if is_executable_file(path):
        return path
    return None


def _relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_managed_launcher_path(path: Path, paths: StatePaths) -> bool:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        resolved = Path(path).expanduser().resolve(strict=False)

    managed_roots = [
        paths.bin_dir.resolve(strict=False),
        paths.versions_dir.resolve(strict=False),
    ]
    return any(_relative_to(resolved, root) for root in managed_roots)


def _current_literal_path(paths: StatePaths) -> Path:
    current = paths.current_path.expanduser()
    if not current.is_absolute():
        current = current.resolve(strict=False)
    return current


def _is_current_launcher_path(path: str | Path | None, paths: StatePaths) -> bool:
    if path is None:
        return False
    try:
        candidate = Path(path).expanduser()
    except TypeError:
        return False
    if not candidate.is_absolute():
        candidate = candidate.resolve(strict=False)
    return candidate == _current_literal_path(paths)


def _recorded_managed_target(paths: StatePaths) -> Path | None:
    record_path = paths.state_dir / "install-record.json"
    try:
        raw = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("owner") != OWNER_MARKER:
        return None
    target = raw.get("targetPath")
    if not isinstance(target, str):
        return None
    try:
        return Path(target).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return Path(target).expanduser().resolve(strict=False)


def recorded_source_path(paths: StatePaths) -> Path | None:
    """The original claude binary captured in the shim install record, if any."""
    record_path = paths.state_dir / "install-record.json"
    try:
        raw = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("owner") != OWNER_MARKER:
        return None
    source = raw.get("sourcePath")
    if not isinstance(source, str):
        return None
    return Path(source).expanduser().resolve(strict=False)


def _read_install_record(paths: StatePaths) -> dict | None:
    try:
        raw = json.loads((paths.state_dir / "install-record.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("owner") != OWNER_MARKER:
        return None
    return raw


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def recorded_cached_source_path(paths: StatePaths) -> Path | None:
    """The verified source cache captured by install-shim, if any.

    The install record's `sourcePath` is useful provenance, but the
    digest-keyed cache is the durable build source: it survives PATH becoming
    the managed shim and survives the original install target changing or
    disappearing. As with install.py's read side, the cache must stay inside
    this state directory's own `sources/` tree and match the recorded sha.
    """
    record = _read_install_record(paths)
    if record is None:
        return None
    cache_raw = record.get("previousSourceCachePath")
    expected_sha = record.get("previousSourceSha256")
    if not isinstance(cache_raw, str) or not isinstance(expected_sha, str):
        return None
    try:
        cache_path = Path(cache_raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    sources_root = (paths.state_dir / "sources").resolve(strict=False)
    try:
        cache_path.relative_to(sources_root)
    except ValueError:
        return None
    if not is_executable_file(cache_path):
        return None
    if _sha256_file(cache_path) != expected_sha:
        return None
    return cache_path


def source_identity(path: str | Path | None, paths: StatePaths, kind: str) -> SourceIdentity | None:
    if _is_current_launcher_path(path, paths):
        return None
    resolved = _resolve_existing_executable(path)
    if resolved is None or is_managed_launcher_path(resolved, paths):
        return None
    recorded_target = _recorded_managed_target(paths)
    if recorded_target is not None and resolved == recorded_target:
        return None
    return SourceIdentity(path=resolved, kind=kind)


def discover_official_claude(
    config: HarnessMonkeyConfig,
    paths: StatePaths,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
    *,
    include_install_record: bool = True,
) -> Path | None:
    environ = os.environ if environ is None else environ
    which = shutil.which if which is None else which

    candidates: list[tuple[str | Path | None, str]] = [
        (config.officialClaudePath, "config"),
        (environ.get("HARNESSMONKEY_SOURCE"), "env"),
        (which(claude_executable_name()), "path"),
    ]
    if include_install_record:
        candidates.extend(
            [
                (recorded_cached_source_path(paths), "install-record-cache"),
                (recorded_source_path(paths), "install-record-source"),
            ]
        )
    if is_windows():
        candidates.extend((c, "install") for c in windows_claude_install_candidates(environ))
    for candidate, kind in candidates:
        identity = source_identity(candidate, paths, kind)
        if identity is not None:
            return identity.path
    return None
