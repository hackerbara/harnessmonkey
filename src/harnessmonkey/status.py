from __future__ import annotations

import hashlib
import json
import os
import platform as platform_module
import sys
from pathlib import Path
from typing import Any

from harnessmonkey.config import HarnessMonkeyConfig, LaunchProfile
from harnessmonkey.install import (
    OWNER_MARKER,
    _version_from_path,
    current_target_is_installed_shim,
    shim_digest,
    shim_target_is_locked,
)
from harnessmonkey.launch_profile import load_active_launch_packages, select_launch_target
from harnessmonkey.package_model import (
    PackageKind,
    PackageManifest,
    PackageValidationError,
    load_package_manifest,
    manifest_digest,
)
from harnessmonkey.paths import StatePaths
from harnessmonkey.smoke import run_command
from harnessmonkey.source_discovery import (
    discover_official_claude,
    is_managed_launcher_path,
    meets_plausible_official_size,
)


def _active_profile(config: HarnessMonkeyConfig) -> LaunchProfile:
    return config.profiles.setdefault("default", LaunchProfile())


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _latest_build_report(active_patch_set: str | None) -> tuple[Path | None, dict[str, Any] | None]:
    if not active_patch_set:
        return None, None
    patch_set_path = Path(active_patch_set).expanduser()
    if not patch_set_path.is_absolute():
        patch_set_path = patch_set_path.resolve()
    report_path = patch_set_path / "build-report.json"
    report = _read_json_file(report_path)
    if report is None:
        return None, None
    return report_path, report


def _display_patch_set(active_patch_set: str | None) -> str | None:
    if not active_patch_set:
        return None
    patch_set_path = Path(active_patch_set).expanduser()
    if not patch_set_path.is_absolute():
        patch_set_path = patch_set_path.resolve()
    return str(patch_set_path)


def _built_patch_ids(report: dict[str, Any] | None) -> list[str]:
    if not report:
        return []
    for key in ("enabledPatches", "patchIds", "builtPatchIds", "activePatchIds"):
        value = report.get(key)
        if isinstance(value, list):
            return [str(item) for item in value]
    snapshot = report.get("buildInputSnapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("patches"), list):
        return [str(item) for item in snapshot["patches"]]
    return []


def _load_desired_patch_manifests(
    paths: StatePaths, desired_patch_ids: list[str]
) -> tuple[dict[str, PackageManifest], list[str]]:
    manifests: dict[str, PackageManifest] = {}
    warnings: list[str] = []
    for patch_id in desired_patch_ids:
        package_dir = paths.patches_dir / patch_id
        if not package_dir.exists():
            warnings.append(f"patch {patch_id} skipped: missing")
            continue
        try:
            manifests[patch_id] = load_package_manifest(package_dir, PackageKind.PATCH)
        except PackageValidationError as exc:
            warnings.append(f"patch {patch_id} skipped: invalid ({exc})")
    return manifests, warnings


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _version_from_output(output: str | None) -> str | None:
    if not output:
        return None
    first = output.split(maxsplit=1)[0]
    return first or None


def _source_identity_from_report(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {}
    identity = report.get("sourceIdentity")
    if isinstance(identity, dict):
        result = dict(identity)
    else:
        result = {}
    if isinstance(report.get("sourceClaudePath"), str):
        result.setdefault("path", report["sourceClaudePath"])
    if isinstance(report.get("sourceVersion"), str):
        result.setdefault("claudeVersion", report["sourceVersion"])
    if isinstance(report.get("sourceVersionOutput"), str):
        result.setdefault("versionOutput", report["sourceVersionOutput"])
    if isinstance(report.get("sourceSha256"), str):
        result.setdefault("sha256", report["sourceSha256"])
    if isinstance(report.get("sourceSizeBytes"), int):
        result.setdefault("sizeBytes", report["sourceSizeBytes"])
    return result


def _source_identity_from_discovery(
    paths: StatePaths, config: HarnessMonkeyConfig
) -> dict[str, Any]:
    source = discover_official_claude(config, paths)
    if source is None:
        return {}
    result = run_command([str(source), "--version"])
    version_output = None
    if result.returncode == 0:
        version_output = result.stdout.strip() or result.stderr.strip() or None
    try:
        size = source.stat().st_size
    except OSError:
        size = None
    identity: dict[str, Any] = {
        "path": str(source),
        "claudeVersion": _version_from_output(version_output),
        "versionOutput": version_output,
        "sha256": _file_sha256(source),
        "platform": sys.platform,
        "arch": platform_module.machine() or "unknown",
    }
    if size is not None:
        identity["sizeBytes"] = size
    return {key: value for key, value in identity.items() if value is not None}


def _source_identity(
    paths: StatePaths, config: HarnessMonkeyConfig, report: dict[str, Any] | None
) -> dict[str, Any]:
    from_report = _source_identity_from_report(report)
    from_discovery = _source_identity_from_discovery(paths, config)
    return from_discovery or from_report


def _target_identities(manifest: PackageManifest) -> list[dict[str, Any]]:
    if manifest.patch is None:
        return []
    identities: list[dict[str, Any]] = []
    for target in manifest.patch.targets:
        identity = target.get("sourceIdentity")
        if isinstance(identity, dict):
            identities.append(identity)
    return identities


def _source_identity_status(
    source: dict[str, Any], patch_manifests: dict[str, PackageManifest]
) -> str:
    if not patch_manifests:
        return "unknown"
    if not source:
        return "unknown"
    for manifest in patch_manifests.values():
        identities = _target_identities(manifest)
        if not identities:
            return "unknown"
        if not any(_identity_matches(source, identity) for identity in identities):
            return _best_identity_mismatch_status(source, identities)
    return "compatible"


IDENTITY_MISMATCH_PRIORITY = {
    "source_sha_mismatch": 0,
    "source_size_mismatch": 1,
    "platform_mismatch": 2,
    "arch_mismatch": 3,
    "version_mismatch": 4,
    "unknown": 5,
}


def _best_identity_mismatch_status(source: dict[str, Any], targets: list[dict[str, Any]]) -> str:
    statuses = [_identity_mismatch_status(source, target) for target in targets]
    return min(statuses, key=lambda status: IDENTITY_MISMATCH_PRIORITY.get(status, 99))


def _identity_mismatch_status(source: dict[str, Any], target: dict[str, Any]) -> str:
    version = target.get("claudeVersion")
    if version is not None and str(source.get("claudeVersion")) != str(version):
        return "version_mismatch"
    version_output = target.get("versionOutput")
    if version_output is not None and str(source.get("versionOutput")) != str(version_output):
        return "version_mismatch"
    platform = target.get("platform")
    if platform is not None and str(source.get("platform")) != str(platform):
        return "platform_mismatch"
    arch = target.get("arch")
    if arch is not None and str(source.get("arch")) != str(arch):
        return "arch_mismatch"
    sha = target.get("sha256")
    if sha is not None and str(source.get("sha256")) != str(sha):
        return "source_sha_mismatch"
    size = target.get("sizeBytes")
    if size is not None and str(source.get("sizeBytes")) != str(size):
        return "source_size_mismatch"
    return "unknown"


def _identity_matches(source: dict[str, Any], target: dict[str, Any]) -> bool:
    fields = (
        ("claudeVersion", "claudeVersion"),
        ("versionOutput", "versionOutput"),
        ("sha256", "sha256"),
        ("sizeBytes", "sizeBytes"),
        ("platform", "platform"),
        ("arch", "arch"),
    )
    for source_key, target_key in fields:
        target_value = target.get(target_key)
        if target_value is None:
            continue
        source_value = source.get(source_key)
        if source_value is None:
            return False
        if str(source_value) != str(target_value):
            return False
    return True


def _manifest_compatibility_status(
    desired_patch_ids: list[str], patch_manifests: dict[str, PackageManifest], warnings: list[str]
) -> str:
    if warnings:
        return "invalid"
    if len(patch_manifests) != len(desired_patch_ids):
        return "invalid"
    return "compatible" if desired_patch_ids else "unknown"


def _last_build_compatibility(report: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not report:
        return "unknown", []
    compatibility = report.get("compatibility")
    if isinstance(compatibility, dict):
        status = str(compatibility.get("status") or "unknown")
        warnings = compatibility.get("warnings")
        return status, [str(item) for item in warnings] if isinstance(warnings, list) else []
    if str(report.get("status")) in {"verified", "manual_smoke_pending", "skipped_gates"}:
        return "compatible", []
    if report.get("failureReason"):
        return "unknown", [str(report["failureReason"])]
    return "unknown", []


def _manifest_digests(patch_manifests: dict[str, PackageManifest]) -> dict[str, str]:
    return {patch_id: manifest_digest(manifest) for patch_id, manifest in patch_manifests.items()}


def _reported_manifest_digests(report: dict[str, Any] | None) -> dict[str, str]:
    value = (report or {}).get("packageManifestDigests")
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if isinstance(item, str)}


def _source_matches_report(source: dict[str, Any], report: dict[str, Any] | None) -> bool:
    report_identity = _source_identity_from_report(report)
    if not source or not report_identity:
        return True
    for key in ("sha256", "sizeBytes", "claudeVersion", "versionOutput", "platform", "arch"):
        expected = report_identity.get(key)
        if expected is None:
            continue
        actual = source.get(key)
        if actual is None or str(actual) != str(expected):
            return False
    return True


def _current_executable_path(current_path: Path) -> str | None:
    try:
        if not (current_path.exists() or current_path.is_symlink()):
            return None
        resolved = current_path.resolve(strict=True)
    except OSError:
        return None
    return str(resolved) if resolved.is_file() and os.access(resolved, os.X_OK) else None


def _install_record_path(paths: StatePaths) -> Path:
    return paths.state_dir / "install-record.json"


def _shim_target_from_record(record_path: Path) -> str | None:
    record = _read_json_file(record_path)
    if not record:
        return None
    target = record.get("targetPath")
    return target if isinstance(target, str) else None


def _shim_is_installed(record_path: Path) -> bool:
    record = _read_json_file(record_path)
    if not record:
        return False
    target = record.get("targetPath")
    try:
        return isinstance(target, str) and current_target_is_installed_shim(Path(target), record)
    except OSError:
        return False


def _detected_claude_command_path() -> Path | None:
    import shutil

    found = shutil.which("claude")
    return Path(found) if found else None


def _shim_previously_managed(record: dict[str, Any] | None) -> bool:
    """install-record.json exists for this target path with our owner marker.

    This is a pure existence check, independent of whether the target
    currently *is* the installed shim (see `_shim_is_installed`): a target
    that was previously managed and is still intact is both
    `shimPreviouslyManaged` and `shimInstalled`.
    """
    return (
        record is not None
        and record.get("owner") == OWNER_MARKER
        and isinstance(record.get("targetPath"), str)
    )


def classify_plausible_official_source(target_path: Path, paths: StatePaths) -> Path | None:
    """Best-effort "this is some other executable" classification.

    Reuses the same primitives `source_discovery.py` already applies to
    config/env/PATH candidates (resolve -> is_file -> X_OK -> not one of
    HarnessMonkey's own managed paths via `is_managed_launcher_path`). Per R8,
    this proves the target is *not* one of our own managed binaries -- it is
    not, and must never be presented as, verified-Anthropic provenance.

    CMux incident fix: path-shape checks alone let *any* executable file
    outside HarnessMonkey's own managed paths through -- including an
    unrelated tool's 8KB wrapper script, which is how that script got cached
    and swapped in as "official" on a real machine. This now also requires
    `meets_plausible_official_size` (see `source_discovery.py`'s
    `MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES`): a cheap, offline `stat()`-only size
    floor, generously below the real ~230MB Claude binary and generously
    above any wrapper/shim script. Never executes `target_path` to check it
    -- classification stays filesystem-metadata-only, by design.

    Stage-2 (`repair.py`) reuses this exact function for its own
    "current target classifies as plausible official" precondition rather
    than re-deriving the classification -- see that module for the
    additional, code-disambiguated refusal reasons it layers on top when
    this returns `None`.
    """
    try:
        resolved = target_path.resolve(strict=True)
    except OSError:
        return None
    if not (resolved.is_file() and os.access(resolved, os.X_OK)):
        return None
    if is_managed_launcher_path(resolved, paths):
        return None
    if not meets_plausible_official_size(resolved):
        return None
    return resolved


def _cheap_official_version(path: Path) -> str | None:
    """Best-effort version extraction for a detected replacement target.

    `path` here is reached only when the target's digest does NOT match the
    managed shim -- i.e. exactly when an unverified binary sits at the
    target path, with only `classify_plausible_official_source`'s path-shape
    check as credential (not verified Anthropic provenance). Detection runs
    on every `status --json`/GUI refresh (R5), so this must never execute
    `path` -- see `install._version_from_path`'s docstring for the concrete
    failure mode (running an intact shim's `--version` re-enters
    `select_launch_target` and executes whatever `claude` resolves on PATH).
    Per spec R7, extraction failure must not suppress detection -- callers
    treat None as "version unknown", not as an error.
    """
    return _version_from_path(path)


_NO_OFFICIAL_REPLACEMENT: dict[str, Any] = {
    "targetReplacedByOfficial": False,
    "detectedOfficialSha256": None,
    "detectedOfficialVersion": None,
    "shimRepairAvailable": False,
    "rolloutRequired": False,
}


def _detect_official_replacement(
    paths: StatePaths, record: dict[str, Any] | None, shim_installed: bool
) -> dict[str, Any]:
    """Stage-1 detection fields from the shim-update-resilience spec (§1).

    Detection only: no cache-writing, no repair, no rollout. Computed fresh
    on every status call (R5) -- one stat/resolve plus, at most, one file
    hash and one subprocess probe, only when a replacement candidate is
    actually found. No mtime/size gate: `status --json` is not called from a
    hot loop anywhere in this codebase today (refresh is user/event
    triggered), so the spec's own framing -- "cheap stat + hash of one
    file" -- applies directly without needing the optional gate.
    """
    if not _shim_previously_managed(record):
        return dict(_NO_OFFICIAL_REPLACEMENT)
    assert record is not None
    target_path = Path(record["targetPath"])
    # Repair availability never depends on whether a replacement was
    # detected -- an intact shim has nothing to repair. It also no longer
    # depends on the OLD previous-source cache being valid (adjudication,
    # controller decision): `restore_install_transaction` (install.py:368-
    # 439) never reads `previousSourceCachePath`/`previousSourceSha256` --
    # it restores from `previousType`/`previousTarget`/
    # `previousContentBase64`/`previousMode`, and `repair_shim_action`
    # overwrites all of those fields on success anyway (R4). Gating
    # `shimRepairAvailable` on the old cache's validity only produced a bug:
    # a corrupt old cache plus an otherwise-healthy replaced target made
    # repair permanently unavailable even though repair never reads that
    # cache. Kept intentionally pinned: `_install_record_source`
    # (launch_profile.py) still returns None on a corrupt cache -- that is
    # the separate launch-fallback safety gate (R9), untouched here.
    repair_available = not shim_installed
    if shim_installed:
        return {**_NO_OFFICIAL_REPLACEMENT, "shimRepairAvailable": repair_available}
    resolved = classify_plausible_official_source(target_path, paths)
    if resolved is None:
        return {**_NO_OFFICIAL_REPLACEMENT, "shimRepairAvailable": repair_available}
    expected_shim_digest = shim_digest(paths.state_dir)
    detected_digest = _file_sha256(resolved)
    if detected_digest is None or detected_digest == expected_shim_digest:
        return {**_NO_OFFICIAL_REPLACEMENT, "shimRepairAvailable": repair_available}
    return {
        "targetReplacedByOfficial": True,
        "detectedOfficialSha256": detected_digest,
        "detectedOfficialVersion": _cheap_official_version(resolved),
        "shimRepairAvailable": repair_available,
        # The active patched build was, by construction, built from the
        # source the (now-replaced) managed shim pointed at -- not this
        # newly detected digest -- so rollout is required whenever a
        # replacement is detected. `discover_official_claude`/`source_identity`
        # can't stand in for this: they deliberately exclude a candidate that
        # resolves to the recorded managed target (see
        # source_discovery.source_identity), which is exactly this target.
        "rolloutRequired": True,
    }


def _patchset_path(active_patch_set: str | None) -> Path | None:
    if not active_patch_set:
        return None
    patchset_path = Path(active_patch_set).expanduser()
    if not patchset_path.is_absolute():
        patchset_path = patchset_path.resolve(strict=False)
    return patchset_path


def _expected_active_executables(
    active_patch_set: str | None, report: dict[str, Any] | None
) -> list[Path]:
    expected: list[Path] = []
    patchset_path = _patchset_path(active_patch_set)
    if patchset_path is not None:
        expected.append(patchset_path / "claude")
    output_path = (report or {}).get("outputPath")
    if isinstance(output_path, str):
        expected.append(Path(output_path).expanduser())
    return expected


def _patched_build_active(
    paths: StatePaths, active_patch_set: str | None, report: dict[str, Any] | None
) -> bool:
    try:
        resolved = paths.current_path.resolve(strict=True)
    except OSError:
        return False
    if not (resolved.is_file() and os.access(resolved, os.X_OK)):
        return False
    for expected in _expected_active_executables(active_patch_set, report):
        try:
            if resolved == expected.resolve(strict=True):
                return True
        except OSError:
            continue
    return False


def _high_risk_options(loaded_options: list[PackageManifest]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for option in loaded_options:
        risk = option.risk
        if risk is None or risk.level != "high":
            continue
        records.append(
            {
                "id": option.id,
                "label": option.label,
                "warning": risk.status_warning or risk.notes or f"{option.label} enabled",
            }
        )
    return records


def status_payload(paths: StatePaths, config: HarnessMonkeyConfig) -> dict[str, Any]:
    profile = _active_profile(config)
    desired_patch_ids = list(profile.patches)
    active_option_ids = list(profile.options)
    report_path, report = _latest_build_report(config.activePatchSet)
    built_patch_ids = _built_patch_ids(report)
    loaded_launch = load_active_launch_packages(paths, config)
    patch_manifests, patch_warnings = _load_desired_patch_manifests(paths, desired_patch_ids)
    source = _source_identity(paths, config, report)
    manifest_status = _manifest_compatibility_status(
        desired_patch_ids, patch_manifests, patch_warnings
    )
    source_status = _source_identity_status(source, patch_manifests)
    last_build_status, build_warnings = _last_build_compatibility(report)
    current_digests = _manifest_digests(patch_manifests)
    reported_digests = _reported_manifest_digests(report)
    digest_missing = bool(
        desired_patch_ids
        and current_digests
        and report is not None
        and any(pid not in reported_digests for pid in desired_patch_ids)
    )
    digest_mismatch = bool(
        desired_patch_ids
        and reported_digests
        and any(reported_digests.get(pid) != current_digests.get(pid) for pid in desired_patch_ids)
    )
    source_report_mismatch = not _source_matches_report(source, report)
    patched_active = _patched_build_active(paths, config.activePatchSet, report)
    target = select_launch_target(paths, config, dict(os.environ))
    target_kind = target.kind if target is not None else "missing"
    active_patch_ids = built_patch_ids if patched_active else []
    active_report_missing = config.activePatchSet is not None and report is None
    current_executable = _current_executable_path(paths.current_path)
    install_record = _install_record_path(paths)
    shim_installed = _shim_is_installed(install_record)
    install_record_data = _read_json_file(install_record)
    shim_previously_managed = _shim_previously_managed(install_record_data)
    # Shim lock feature: read-only, `st_flags`-only check (never touches
    # file bytes) -- only meaningful while `shim_installed` is True, exactly
    # like `shimTargetPath`/`installRecordPath` above/below. False on
    # non-mac platforms or whenever the target isn't currently the installed
    # shim at all. Reuses `install_record_data` (already loaded just above)
    # instead of re-reading `install_record` from disk a third time; also
    # guards against the record having vanished between that read and
    # `_shim_is_installed`'s own earlier read (a real, if narrow, race) --
    # without the `isinstance` check a missing/malformed `targetPath` would
    # otherwise reach `Path(None)` and raise `TypeError`.
    _shim_target_path = install_record_data.get("targetPath") if install_record_data else None
    shim_locked = (
        shim_target_is_locked(Path(_shim_target_path))
        if shim_installed and isinstance(_shim_target_path, str)
        else False
    )
    official_replacement = _detect_official_replacement(
        paths, install_record_data, shim_installed
    )
    installed = (
        (patched_active or shim_installed)
        if config.installMode == "shim"
        else (current_executable is not None or shim_installed)
    )
    runnable = current_executable is not None
    rebuild_required = (
        desired_patch_ids != built_patch_ids
        or desired_patch_ids != active_patch_ids
        or active_report_missing
        or digest_missing
        or digest_mismatch
        or source_status not in {"compatible", "unknown"}
        or source_report_mismatch
        or manifest_status == "invalid"
        or (installed and not runnable)
    )
    compatibility_warnings = [
        *loaded_launch.warnings,
        *patch_warnings,
        *build_warnings,
    ]
    if digest_missing:
        compatibility_warnings.append(
            "enabled patch package manifest digest missing from last build"
        )
    if digest_mismatch:
        compatibility_warnings.append("enabled patch package manifest changed since last build")
    if source_report_mismatch:
        compatibility_warnings.append("source identity changed since last build")
    if manifest_status == "invalid":
        compatibility_status = "invalid"
    elif source_status not in {"compatible", "unknown"}:
        compatibility_status = source_status
    elif source_report_mismatch:
        compatibility_status = "source_mismatch"
    else:
        compatibility_status = (
            last_build_status if last_build_status != "unknown" else manifest_status
        )
    if compatibility_warnings and not desired_patch_ids and not installed:
        status = "warning"
    elif not installed:
        status = "not_installed"
    elif rebuild_required or not runnable:
        status = "rebuild_required"
    elif compatibility_warnings:
        status = "warning"
    else:
        status = "ok"

    return {
        "schemaVersion": 1,
        "status": status,
        "activeProfile": config.activeProfile,
        "activePrompt": profile.prompt,
        "desiredPatchIds": desired_patch_ids,
        "builtPatchIds": built_patch_ids,
        "activePatchIds": active_patch_ids,
        "patchedBuildActive": patched_active,
        "targetClaudeKind": target_kind,
        "activeOptionIds": active_option_ids,
        "highRiskOptions": _high_risk_options(loaded_launch.options),
        "sourceClaudeVersion": source.get("claudeVersion"),
        "sourceClaudePath": source.get("path"),
        "sourceSha256": source.get("sha256"),
        "compatibilityStatus": compatibility_status,
        "manifestCompatibilityStatus": manifest_status,
        "sourceIdentityStatus": source_status,
        "lastBuildCompatibilityStatus": last_build_status,
        "liveValidationStatus": "unknown",
        "compatibilityWarnings": compatibility_warnings,
        "statusWarnings": compatibility_warnings,
        "rebuildRequired": rebuild_required,
        "latestBuildReportPath": str(report_path) if report_path is not None else None,
        "lastError": None,
        # Transitional V1/V1.5 status fields kept for existing consumers.
        "sourceClaudePathLegacy": source.get("path"),
        "officialClaudePath": config.officialClaudePath,
        "installMode": config.installMode,
        "activePatchSet": _display_patch_set(config.activePatchSet),
        "currentClaudePath": current_executable,
        "shimInstalled": shim_installed,
        "shimTargetPath": _shim_target_from_record(install_record) if shim_installed else None,
        "installRecordPath": str(install_record) if shim_installed else None,
        # Shim lock feature: additive, read-only. True only when the target
        # is currently the installed shim AND carries the macOS/BSD
        # user-immutable flag (see install.py's `_lock_target`/
        # `shim_target_is_locked`). False on non-mac platforms, when
        # nothing is installed, or if chflags itself is unsupported/failed.
        "shimLocked": shim_locked,
        # Reverted-shim visibility gap fix: `shimTargetPath`/`installRecordPath`
        # above stay gated on `shim_installed` exactly as before (existing
        # consumers depend on that gating) -- this field is additive and is
        # NOT gated on it, so a consumer can tell "never managed this
        # machine" (None) apart from "managed but something -- e.g. the
        # official Anthropic auto-updater -- reverted the shim since" (a
        # non-None value while shimInstalled is False). Combine with
        # `shimPreviouslyManaged and not shimInstalled` (both already exposed
        # below/above) to detect that reverted-since-managed condition
        # directly; no separate boolean is needed for it.
        "lastManagedTargetPath": (
            install_record_data.get("targetPath") if shim_previously_managed else None
        ),
        # Stage-1 shim-update-resilience detection fields (spec §1). Additive
        # and optional for consumers; shimInstalled semantics are unchanged.
        "shimPreviouslyManaged": shim_previously_managed,
        "targetReplacedByOfficial": official_replacement["targetReplacedByOfficial"],
        "detectedOfficialSha256": official_replacement["detectedOfficialSha256"],
        "detectedOfficialVersion": official_replacement["detectedOfficialVersion"],
        "shimRepairAvailable": official_replacement["shimRepairAvailable"],
        "rolloutRequired": official_replacement["rolloutRequired"],
        "discoveredOfficialClaudePath": str(discover_official_claude(config, paths))
        if discover_official_claude(config, paths)
        else None,
        "detectedClaudeCommandPath": str(_detected_claude_command_path())
        if _detected_claude_command_path()
        else None,
        "buildStrategy": (
            (report or {}).get("buildStrategy") or (report or {}).get("engine") or "unknown"
        ),
        "lastBuildStrategy": (
            (report or {}).get("buildStrategy") or (report or {}).get("engine") or "unknown"
        ),
        "changedModules": (report or {}).get("changedModules", []),
        "repackSummary": (report or {}).get("repackSummary"),
        "stateDir": str(paths.state_dir),
        "logsDir": str(paths.logs_dir),
    }
