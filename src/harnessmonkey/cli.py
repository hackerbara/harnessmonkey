from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as platform_module
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harnessmonkey import __version__, launch_agent
from harnessmonkey.authorization import (
    AuthorizationDenied,
    AuthorizationRequired,
    authorization_method_for_target,
    target_needs_authorization,
)
from harnessmonkey.binary_inspect import inspect_binary_bytes
from harnessmonkey.builder_v15 import (
    BuildRequestV15,
    ValidationRequestV15,
    build_patchset_v15,
    validate_package,
)
from harnessmonkey.cli_json import envelope_error, envelope_ok, print_json, to_jsonable
from harnessmonkey.config import LaunchProfile, load_config, save_config
from harnessmonkey.install import (
    ProtectedTargetRestoreUnavailable,
    TargetNotPlausibleOfficial,
    current_target_is_installed_shim,
    install_shim_transaction,
    install_target_not_plausible_official,
    protected_install_requires_refusal,
    restore_install_transaction,
    use_official,
)
from harnessmonkey.package_model import (
    PackageKind,
    PackageManifest,
    PackageValidationError,
    discover_packages,
    load_package_manifest,
    manifest_digest,
    validate_package_id,
)
from harnessmonkey.packages_admin import (
    add_package,
    invalid_package_error,
    remove_package,
    scaffold_prompt_package,
)
from harnessmonkey.paths import StatePaths, default_paths
from harnessmonkey.repair import (
    CacheSourceRefused,
    RepairRefused,
    cache_source_action,
    repair_shim_action,
)
from harnessmonkey.shim_entry import compute_launch_with_paths
from harnessmonkey.smoke import run_command
from harnessmonkey.source_discovery import discover_official_claude, recorded_source_path
from harnessmonkey.status import status_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harnessmonkey")
    parser.add_argument("--version", action="store_true", help="print HarnessMonkey version")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor")
    list_patches = sub.add_parser("list-patches")
    list_patches.add_argument("--json", action="store_true")
    list_options = sub.add_parser("list-options")
    list_options.add_argument("--json", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    enable = sub.add_parser("enable")
    enable.add_argument("--json", action="store_true")
    enable.add_argument("patch_id")
    disable = sub.add_parser("disable")
    disable.add_argument("--json", action="store_true")
    disable.add_argument("patch_id")
    enable_patch = sub.add_parser("enable-patch")
    enable_patch.add_argument("patch_id")
    enable_patch.add_argument("--json", action="store_true")
    disable_patch = sub.add_parser("disable-patch")
    disable_patch.add_argument("patch_id")
    disable_patch.add_argument("--json", action="store_true")
    enable_option = sub.add_parser("enable-option")
    enable_option.add_argument("option_id")
    enable_option.add_argument("--confirm", action="store_true")
    enable_option.add_argument("--json", action="store_true")
    disable_option = sub.add_parser("disable-option")
    disable_option.add_argument("option_id")
    disable_option.add_argument("--json", action="store_true")
    list_prompts = sub.add_parser("list-prompts")
    list_prompts.add_argument("--json", action="store_true")
    set_prompt = sub.add_parser("set-prompt")
    set_prompt.add_argument("--json", action="store_true")
    set_prompt.add_argument("prompt")
    set_prompt.add_argument("--id", default="default")
    set_prompt.add_argument("--name")
    set_prompt.add_argument("--mode", choices=("append", "replace"), default="append")
    set_prompt.add_argument("--from-file", action="store_true")
    clear_prompt = sub.add_parser("clear-prompt")
    clear_prompt.add_argument("--json", action="store_true")

    add_patch = sub.add_parser("add-patch")
    add_patch.add_argument("source_dir")
    add_patch.add_argument("--json", action="store_true")
    add_option = sub.add_parser("add-option")
    add_option.add_argument("source_dir")
    add_option.add_argument("--json", action="store_true")
    add_prompt = sub.add_parser("add-prompt")
    add_prompt.add_argument("path")
    add_prompt.add_argument("--id")
    add_prompt.add_argument("--name")
    add_prompt.add_argument("--json", action="store_true")

    install_cmd = sub.add_parser("install")
    install_cmd.add_argument("--cli", action="store_true")
    install_cmd.add_argument("--json", action="store_true")
    uninstall_cmd = sub.add_parser("uninstall")
    uninstall_cmd.add_argument("--json", action="store_true")

    remove_patch = sub.add_parser("remove-patch")
    remove_patch.add_argument("patch_id")
    remove_patch.add_argument("--json", action="store_true")
    remove_option = sub.add_parser("remove-option")
    remove_option.add_argument("option_id")
    remove_option.add_argument("--json", action="store_true")
    remove_prompt = sub.add_parser("remove-prompt")
    remove_prompt.add_argument("prompt_id")
    remove_prompt.add_argument("--json", action="store_true")

    inspect_binary = sub.add_parser("inspect-binary")
    inspect_binary.add_argument("--source", required=True)
    inspect_binary.add_argument("--json", action="store_true")

    validate = sub.add_parser("validate-package")
    validate.add_argument("--source", required=True)
    validate.add_argument("--package", required=True)
    validate.add_argument("--source-version", required=True)
    validate.add_argument("--source-version-output", required=True)
    validate.add_argument("--platform", default=sys.platform)
    validate.add_argument("--arch", default=platform_module.machine() or "unknown")
    validate.add_argument("--json", action="store_true")

    build = sub.add_parser("build")
    build.add_argument("--source")
    build.add_argument("--package", action="append", dest="packages")
    build.add_argument("--output-dir")
    build.add_argument("--source-version")
    build.add_argument("--source-version-output")
    build.add_argument("--platform", default=sys.platform)
    build.add_argument("--arch", default=platform_module.machine() or "unknown")
    build.add_argument("--skip-signing", action="store_true")
    build.add_argument("--skip-smoke", action="store_true")
    build.add_argument("--json", action="store_true")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--activate", action="store_true")
    build.add_argument("--progress", action="store_true")

    install = sub.add_parser("install-shim")
    install.add_argument("--target")
    install.add_argument("--state-dir")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--json", action="store_true")
    install.add_argument("--progress", action="store_true")

    uninstall = sub.add_parser("uninstall-shim")
    uninstall.add_argument("--target")
    uninstall.add_argument("--state-dir")
    uninstall.add_argument("--record")
    uninstall.add_argument("--force", action="store_true")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.add_argument("--json", action="store_true")
    uninstall.add_argument("--progress", action="store_true")

    cache_source_parser = sub.add_parser("cache-source")
    cache_source_parser.add_argument("--target")
    cache_source_parser.add_argument("--state-dir")
    cache_source_parser.add_argument("--json", action="store_true")

    repair_shim_parser = sub.add_parser("repair-shim")
    repair_shim_parser.add_argument("--target")
    repair_shim_parser.add_argument("--state-dir")
    repair_shim_parser.add_argument("--json", action="store_true")

    rollback = sub.add_parser("rollback")
    rollback.add_argument("--target")
    rollback.add_argument("--state-dir")
    rollback.add_argument("--record")
    rollback.add_argument("--force", action="store_true")
    rollback.add_argument("--dry-run", action="store_true")
    rollback.add_argument("--json", action="store_true")

    official = sub.add_parser("use-official")
    official.add_argument("--official")
    official.add_argument("--json", action="store_true")

    launch_preview = sub.add_parser("launch-preview")
    launch_preview.add_argument("--json", action="store_true")
    launch_preview.add_argument("argv", nargs=argparse.REMAINDER)
    return parser


def active_profile(config):
    return config.profiles.setdefault("default", LaunchProfile())


def emit(
    args: argparse.Namespace, text: str, payload: Any | None = None, *, error: bool = False
) -> int:
    if getattr(args, "json", False):
        print_json(payload if payload is not None else envelope_ok(text))
    else:
        print(text, file=sys.stderr if error else sys.stdout)
    return 0


def _progress_emitter(enabled: bool) -> Callable[[dict], None] | None:
    """Return a stderr JSONL progress emitter when enabled, else None.

    Each event is written as a single sorted-key JSON object per line to stderr,
    flushed immediately. stdout is never touched, preserving the byte-identical
    stdout contract between --progress and non-progress runs.
    """
    if not enabled:
        return None

    def emit_event(event: dict) -> None:
        print(json.dumps(event, sort_keys=True), file=sys.stderr, flush=True)

    return emit_event


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
    return (report_path, report) if report is not None else (None, None)


def _display_patch_set(active_patch_set: str | None) -> str | None:
    if not active_patch_set:
        return None
    patch_set_path = Path(active_patch_set).expanduser()
    if not patch_set_path.is_absolute():
        patch_set_path = patch_set_path.resolve()
    return str(patch_set_path)


def _active_patch_ids_from_report(report: dict[str, Any] | None) -> list[str]:
    if not report:
        return []
    for key in ("enabledPatches", "patchIds", "activePatchIds"):
        value = report.get(key)
        if isinstance(value, list):
            return [str(item) for item in value]
    return []


def _safe_resolve(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


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


def _shim_record(record_path: Path) -> dict[str, Any] | None:
    return _read_json_file(record_path)


def _shim_is_installed(record_path: Path) -> bool:
    record = _shim_record(record_path)
    if not record:
        return False
    target = record.get("targetPath")
    try:
        return isinstance(target, str) and current_target_is_installed_shim(Path(target), record)
    except OSError:
        return False


def _status_payload(paths: StatePaths, config) -> dict[str, Any]:
    profile = active_profile(config)
    desired = list(profile.patches)
    report_path, report = _latest_build_report(config.activePatchSet)
    active = _active_patch_ids_from_report(report)
    install_record = _install_record_path(paths)
    current_executable = _current_executable_path(paths.current_path)
    shim_installed = _shim_is_installed(install_record)
    if config.installMode == "shim":
        installed = shim_installed
    else:
        installed = current_executable is not None or shim_installed
    runnable = current_executable is not None
    active_report_missing = config.activePatchSet is not None and report is None
    rebuild_required = desired != active or active_report_missing or (installed and not runnable)
    if not installed:
        status = "not_installed"
    elif rebuild_required or not runnable:
        status = "rebuild_required"
    else:
        status = "ok"
    build_strategy = (
        (report or {}).get("buildStrategy") or (report or {}).get("engine") or "unknown"
    )
    detected_command = _detected_claude_command_path()
    discovered_source = discover_official_claude(config, paths)
    report_source = (report or {}).get("sourceClaudePath")
    return {
        "schemaVersion": 1,
        "status": status,
        "sourceClaudeVersion": (report or {}).get("sourceVersion"),
        "sourceClaudePath": (
            report_source or (str(discovered_source) if discovered_source else None)
        ),
        "officialClaudePath": config.officialClaudePath,
        "discoveredOfficialClaudePath": str(discovered_source) if discovered_source else None,
        "detectedClaudeCommandPath": str(detected_command) if detected_command else None,
        "installMode": config.installMode,
        "shimInstalled": shim_installed,
        "activeProfile": config.activeProfile,
        "activePrompt": profile.prompt,
        "desiredPatchIds": desired,
        "activePatchIds": active,
        "rebuildRequired": rebuild_required,
        "latestBuildReportPath": str(report_path) if report_path is not None else None,
        "activePatchSet": _display_patch_set(config.activePatchSet),
        "currentClaudePath": current_executable,
        "shimTargetPath": _shim_target_from_record(install_record) if shim_installed else None,
        "installRecordPath": str(install_record) if shim_installed else None,
        "buildStrategy": build_strategy,
        "lastBuildStrategy": build_strategy,
        "changedModules": (report or {}).get("changedModules", []),
        "repackSummary": (report or {}).get("repackSummary"),
        "stateDir": str(paths.state_dir),
        "logsDir": str(paths.logs_dir),
        "lastError": None,
    }


def _patch_label(patch_json: Path) -> str:
    raw = _read_json_file(patch_json) or {}
    return str(raw.get("name") or raw.get("label") or patch_json.parent.name)


def _patch_label_from_raw(raw: dict[str, Any], patch_json: Path) -> str:
    return str(raw.get("name") or raw.get("label") or patch_json.parent.name)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_identity_for_patch_status() -> dict[str, Any] | None:
    source = _discover_source(None)
    if source is None or not source.exists():
        return None
    version_output = _source_version_output(source, None)
    version = _source_version(None, version_output)
    if version_output is None or version is None:
        return None
    try:
        size_bytes = source.stat().st_size
    except OSError:
        return None
    return {
        "path": source,
        "claudeVersion": version,
        "versionOutput": version_output,
        "sizeBytes": size_bytes,
        "platform": sys.platform,
        "arch": platform_module.machine() or "unknown",
    }


def _source_status_sha256(source: dict[str, Any]) -> str | None:
    sha = source.get("sha256")
    if isinstance(sha, str):
        return sha
    path = source.get("path")
    if not isinstance(path, Path):
        return None
    try:
        sha = _file_sha256(path)
    except OSError:
        return None
    source["sha256"] = sha
    return sha


def _target_source_identities(raw: dict[str, Any]) -> list[dict[str, Any]]:
    targets = raw.get("targets", [])
    if not isinstance(targets, list):
        return []
    identities: list[dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        identity = target.get("sourceIdentity")
        if isinstance(identity, dict):
            identities.append(identity)
    return identities


def _target_versions(identities: list[dict[str, Any]]) -> str:
    versions = sorted(
        {
            str(identity.get("claudeVersion"))
            for identity in identities
            if identity.get("claudeVersion")
        }
    )
    return ", ".join(versions) if versions else "unknown"


def _patch_compatibility(
    raw: dict[str, Any], source: dict[str, Any] | None
) -> tuple[str, str | None]:
    identities = _target_source_identities(raw)
    if not identities:
        return "unknown", "Patch manifest has no source identity target."
    if source is None:
        return "unknown", "No current Claude source was found to check compatibility."

    current_version = str(source["claudeVersion"])
    same_version = [
        identity for identity in identities if str(identity.get("claudeVersion")) == current_version
    ]
    if not same_version:
        return (
            "version_mismatch",
            f"Package targets Claude {_target_versions(identities)}; "
            f"current source is {current_version}.",
        )

    current_size = int(source["sizeBytes"])
    for identity in same_version:
        target_size = identity.get("sizeBytes")
        if isinstance(target_size, int) and target_size != current_size:
            continue
        if str(identity.get("versionOutput")) != str(source["versionOutput"]):
            continue
        if str(identity.get("platform")) != str(source["platform"]):
            continue
        if str(identity.get("arch")) != str(source["arch"]):
            continue
        target_sha = identity.get("sha256")
        current_sha = _source_status_sha256(source)
        if isinstance(target_sha, str) and current_sha == target_sha:
            return "compatible", f"Compatible with current source {current_version}."

    target = same_version[0]
    current_sha = _source_status_sha256(source)
    expected_sha = str(target.get("sha256") or "unknown")
    expected_size = str(target.get("sizeBytes") or "unknown")
    return (
        "sha_mismatch",
        f"Package targets Claude {current_version}, but source identity differs "
        f"(expected {target.get('versionOutput') or 'unknown'}, "
        f"{target.get('platform') or 'unknown'}/{target.get('arch') or 'unknown'}, "
        f"sha256 {expected_sha[:12]}…, size {expected_size}; "
        f"current {source['versionOutput']}, {source['platform']}/{source['arch']}, "
        f"current sha256 {(current_sha or 'unknown')[:12]}…, size {current_size}).",
    )


def _list_patch_payload(paths: StatePaths, config) -> dict[str, Any]:
    profile = active_profile(config)
    desired = set(profile.patches)
    _, report = _latest_build_report(config.activePatchSet)
    active = set(_active_patch_ids_from_report(report))
    seen: set[str] = set()
    patches: list[dict[str, Any]] = []
    source_identity = _source_identity_for_patch_status()
    for root in _package_roots(paths):
        if not root.exists():
            continue
        for patch_json in sorted(root.glob("*/patch.json")):
            patch_id = patch_json.parent.name
            if patch_id in seen:
                continue
            seen.add(patch_id)
            raw = _read_json_file(patch_json) or {}
            compatibility_status, compatibility_message = _patch_compatibility(raw, source_identity)
            patches.append(
                {
                    "id": patch_id,
                    "label": _patch_label_from_raw(raw, patch_json),
                    "desiredEnabled": patch_id in desired,
                    "activeEnabled": patch_id in active,
                    "available": True,
                    "compatibilityStatus": compatibility_status,
                    "compatibilityMessage": compatibility_message,
                }
            )
    for patch_id in sorted((desired | active) - seen):
        patches.append(
            {
                "id": patch_id,
                "label": patch_id,
                "desiredEnabled": patch_id in desired,
                "activeEnabled": patch_id in active,
                "available": False,
                "compatibilityStatus": "unknown",
            }
        )
    return {"schemaVersion": 1, "patches": patches}


def _list_prompt_payload(paths: StatePaths, config) -> dict[str, Any]:
    profile = active_profile(config)
    prompt_dir = paths.prompts_dir
    prompts: list[dict[str, Any]] = []
    if prompt_dir.exists():
        for prompt_json in sorted(prompt_dir.glob("*.json")):
            raw = _read_json_file(prompt_json) or {}
            prompt_id = str(raw.get("id") or prompt_json.stem)
            source_path = raw.get("sourcePath") or str(prompt_dir / f"{prompt_id}.md")
            prompts.append(
                {
                    "id": prompt_id,
                    "label": str(raw.get("name") or raw.get("label") or prompt_id),
                    "active": profile.prompt == prompt_id,
                    "mode": str(raw.get("mode") or "append"),
                    "sourcePath": str(source_path),
                }
            )
    return {"schemaVersion": 1, "prompts": prompts}


def _kind_root(paths: StatePaths, kind: PackageKind) -> Path:
    if kind is PackageKind.PATCH:
        return paths.patches_dir
    if kind is PackageKind.PROMPT:
        return paths.prompts_dir
    return paths.options_dir


def _enabled_ids_for_kind(config, kind: PackageKind) -> set[str]:
    profile = active_profile(config)
    if kind is PackageKind.PATCH:
        return set(profile.patches)
    if kind is PackageKind.OPTION:
        return set(profile.options)
    return {profile.prompt} if profile.prompt else set()


def _compatibility_status(manifest: PackageManifest) -> str:
    compatibility = manifest.compatibility
    if compatibility is None or not (
        compatibility.claude_versions or compatibility.platforms or compatibility.arches
    ):
        return "unconstrained"
    return "constrained"


def _risk_level(manifest: PackageManifest) -> str:
    return manifest.risk.level if manifest.risk is not None else "unknown"


def _strip_manifest_file_prefix(error: str) -> str:
    if ": " in error and error.split(": ", 1)[0].endswith(".json"):
        return error.split(": ", 1)[1]
    return error


def _invalid_package_errors(package_dir: Path, errors: tuple[str, ...]) -> list[str]:
    formatted: list[str] = []
    for error in errors:
        detail = _strip_manifest_file_prefix(error)
        if "id_must_match_folder" in detail:
            manifest_id = None
            for manifest_path in sorted(package_dir.glob("*.json")):
                raw = _read_json_file(manifest_path)
                if raw is not None and isinstance(raw.get("id"), str):
                    manifest_id = raw["id"]
                    break
            if manifest_id is not None:
                formatted.append(f"id_must_match_folder: {manifest_id} != {package_dir.name}")
                continue
        formatted.append(detail)
    return formatted


def _package_record(manifest: PackageManifest, enabled: set[str]) -> dict[str, Any]:
    record = {
        "id": manifest.id,
        "label": manifest.label,
        "kind": manifest.kind.value,
        "enabled": manifest.id in enabled,
        "valid": True,
        "compatibilityStatus": _compatibility_status(manifest),
        "riskLevel": _risk_level(manifest),
        "errors": [],
    }
    if manifest.risk is not None and manifest.risk.requires_confirmation:
        record["requiresConfirmation"] = True
    if manifest.risk is not None and manifest.risk.status_warning is not None:
        record["statusWarning"] = manifest.risk.status_warning
    return record


def _invalid_package_record(
    package_dir: Path, kind: PackageKind, errors: tuple[str, ...], enabled: set[str]
) -> dict[str, Any]:
    return {
        "id": package_dir.name,
        "label": package_dir.name,
        "kind": kind.value,
        "enabled": package_dir.name in enabled,
        "valid": False,
        "compatibilityStatus": "unknown",
        "riskLevel": "unknown",
        "errors": _invalid_package_errors(package_dir, errors),
    }


def _list_kind_payload(paths: StatePaths, config, kind: PackageKind) -> dict[str, Any]:
    discovered = discover_packages(_kind_root(paths, kind), kind)
    enabled = _enabled_ids_for_kind(config, kind)
    records = [_package_record(manifest, enabled) for manifest in discovered.valid]
    records.extend(
        _invalid_package_record(invalid.package_dir, kind, invalid.errors, enabled)
        for invalid in discovered.invalid
    )
    records.sort(key=lambda item: str(item["id"]))
    collection = {
        PackageKind.PATCH: "patches",
        PackageKind.PROMPT: "prompts",
        PackageKind.OPTION: "options",
    }[kind]
    return {"schemaVersion": 1, collection: records}


def _list_payload(paths: StatePaths, config, kind: PackageKind) -> dict[str, Any]:
    v3_payload = _list_kind_payload(paths, config, kind)
    if kind is PackageKind.PATCH:
        return v3_payload if v3_payload["patches"] else _list_patch_payload(paths, config)
    if kind is PackageKind.PROMPT:
        return v3_payload if v3_payload["prompts"] else _list_prompt_payload(paths, config)
    return v3_payload


def _print_package_ids(payload: dict[str, Any], collection: str) -> None:
    for record in payload[collection]:
        print(record["id"])


def _load_kind_package_or_emit(
    args: argparse.Namespace, paths: StatePaths, package_id: str, kind: PackageKind
):
    try:
        safe_package_id = validate_package_id(package_id)
    except PackageValidationError as exc:
        payload = envelope_error(str(exc), code="invalid_package_id")
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print(str(exc), file=sys.stderr)
        return None
    try:
        return load_package_manifest(_kind_root(paths, kind) / safe_package_id, kind)
    except PackageValidationError as exc:
        payload = envelope_error(str(exc), code="invalid_package")
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print(str(exc), file=sys.stderr)
        return None


def _emit_mutation_error(args: argparse.Namespace, message: str, code: str) -> int:
    if getattr(args, "json", False):
        print_json(envelope_error(message, code=code))
    else:
        print(message, file=sys.stderr)
    return 1


def _option_conflict_id(
    profile: LaunchProfile, option: PackageManifest, paths: StatePaths
) -> str | None:
    if option.option is None:
        return None
    enabled_ids = set(profile.options)
    for conflict_id in option.option.conflicts_with_options:
        if conflict_id in enabled_ids:
            return conflict_id
    for enabled_id in profile.options:
        try:
            safe_enabled_id = validate_package_id(enabled_id)
        except PackageValidationError:
            continue
        try:
            enabled = load_package_manifest(paths.options_dir / safe_enabled_id, PackageKind.OPTION)
        except PackageValidationError:
            continue
        if enabled.option is not None and option.id in enabled.option.conflicts_with_options:
            return enabled_id
    return None


def _load_patch_manifest_or_none(paths: StatePaths, package_id: str) -> PackageManifest | None:
    try:
        safe_id = validate_package_id(package_id)
    except PackageValidationError:
        return None
    try:
        return load_package_manifest(paths.patches_dir / safe_id, PackageKind.PATCH)
    except PackageValidationError:
        return None


def _requires_closure(
    paths: StatePaths, manifest: PackageManifest
) -> tuple[list[str], list[str]]:
    """The transitive `requiresPackages` closure of `manifest`, resolved.

    Returns `(resolved, missing)`: `resolved` is every required patch id
    (direct and transitive, dependency-first, `manifest.id` itself never
    included) that has a valid on-disk manifest; `missing` is every required
    id that could not be loaded at all (unknown id or invalid manifest) --
    the caller must refuse to enable anything when `missing` is non-empty
    rather than half-enabling the closure. Cycle-safe: a required id already
    visited (including `manifest.id` itself) is never re-visited.
    """
    resolved: list[str] = []
    missing: list[str] = []
    visited: set[str] = {manifest.id}

    def visit(current: PackageManifest) -> None:
        for required_id in current.requires_packages:
            if required_id in visited:
                continue
            visited.add(required_id)
            required_manifest = _load_patch_manifest_or_none(paths, required_id)
            if required_manifest is None:
                if required_id not in missing:
                    missing.append(required_id)
                continue
            # Post-order: recurse into `required_id`'s own requirements
            # first, so a deeper dependency (e.g. drawer-dock under
            # mid-layer under top-layer) lands earlier in `resolved` than
            # anything that depends on it -- `handle_enable_patch` appends
            # `resolved` to `profile.patches` in this order, so the eventual
            # build always sees dependencies before their dependents.
            visit(required_manifest)
            if required_id not in resolved:
                resolved.append(required_id)

    visit(manifest)
    return resolved, missing


def _patch_dependents(paths: StatePaths, profile: LaunchProfile, package_id: str) -> list[str]:
    """Currently-enabled patch ids whose `requiresPackages` closure needs
    `package_id` (directly or transitively).

    Used to refuse `disable-patch` on a required package while a dependent
    is still enabled (Task requirement: never leave/create a broken
    selection) -- mirrors `_option_conflict_id`'s "scan the enabled set,
    load each sibling manifest" shape.
    """
    dependents: list[str] = []
    for enabled_id in profile.patches:
        if enabled_id == package_id:
            continue
        enabled_manifest = _load_patch_manifest_or_none(paths, enabled_id)
        if enabled_manifest is None:
            continue
        required_ids, _missing = _requires_closure(paths, enabled_manifest)
        if package_id in required_ids:
            dependents.append(enabled_id)
    return dependents


def handle_enable_patch(args: argparse.Namespace, paths: StatePaths, config) -> int:
    manifest = _load_kind_package_or_emit(args, paths, args.patch_id, PackageKind.PATCH)
    if manifest is None:
        return 1
    required_ids, missing_ids = _requires_closure(paths, manifest)
    if missing_ids:
        return _emit_mutation_error(
            args,
            f"patch {args.patch_id} requires missing package(s): {', '.join(missing_ids)}",
            "missing_required_package",
        )
    profile = active_profile(config)
    newly_added = [req_id for req_id in required_ids if req_id not in profile.patches]
    for req_id in newly_added:
        profile.patches.append(req_id)
    if args.patch_id not in profile.patches:
        profile.patches.append(args.patch_id)
    save_config(paths.config_path, config)
    if newly_added:
        summary = (
            f"enabled {args.patch_id} (+ {', '.join(newly_added)}, required); "
            "rebuild required"
        )
    else:
        summary = f"enabled {args.patch_id}; rebuild required"
    return emit(args, summary, envelope_ok(summary, status="rebuild_required"))


def handle_disable_patch(args: argparse.Namespace, paths: StatePaths, config) -> int:
    profile = active_profile(config)
    dependents = _patch_dependents(paths, profile, args.patch_id)
    if dependents:
        return _emit_mutation_error(
            args,
            f"cannot disable {args.patch_id}: required by {', '.join(dependents)}",
            "required_by_enabled_patches",
        )
    profile.patches = [item for item in profile.patches if item != args.patch_id]
    save_config(paths.config_path, config)
    return emit(
        args,
        f"disabled {args.patch_id}; rebuild required",
        envelope_ok(f"disabled {args.patch_id}; rebuild required", status="rebuild_required"),
    )


def handle_set_prompt_package(args: argparse.Namespace, paths: StatePaths, config) -> int:
    if getattr(args, "from_file", False):
        return handle_set_prompt(args, paths, config)
    if _load_kind_package_or_emit(args, paths, args.prompt, PackageKind.PROMPT) is None:
        return 1
    active_profile(config).prompt = args.prompt
    save_config(paths.config_path, config)
    return emit(args, f"set prompt {args.prompt}", envelope_ok(f"prompt set to {args.prompt}"))


def handle_enable_option(args: argparse.Namespace, paths: StatePaths, config) -> int:
    option = _load_kind_package_or_emit(args, paths, args.option_id, PackageKind.OPTION)
    if option is None:
        return 1
    if option.risk is not None and option.risk.requires_confirmation and not args.confirm:
        return _emit_mutation_error(
            args,
            f"option {args.option_id} requires --confirm",
            "confirmation_required",
        )
    profile = active_profile(config)
    conflict_id = _option_conflict_id(profile, option, paths)
    if conflict_id is not None:
        return _emit_mutation_error(
            args,
            f"option {args.option_id} conflicts with enabled option {conflict_id}",
            "option_conflict",
        )
    profile.options = [item for item in profile.options if item != args.option_id]
    profile.options.append(args.option_id)
    save_config(paths.config_path, config)
    return emit(
        args,
        f"enabled option {args.option_id}",
        envelope_ok(f"enabled option {args.option_id}"),
    )


def handle_disable_option(args: argparse.Namespace, paths: StatePaths, config) -> int:
    profile = active_profile(config)
    profile.options = [item for item in profile.options if item != args.option_id]
    save_config(paths.config_path, config)
    return emit(
        args,
        f"disabled option {args.option_id}",
        envelope_ok(f"disabled option {args.option_id}"),
    )


def _dry_run_install_payload(
    target: Path, *, uninstall: bool = False, state_dir: Path | None = None
) -> Any:
    needs_auth = target_needs_authorization(target)
    action = "uninstall managed claude shim" if uninstall else "install managed claude shim"
    if (
        not uninstall
        and state_dir is not None
        and protected_install_requires_refusal(target, state_dir / "install-record.json")
    ):
        message = f"refusing to overwrite protected existing target without safe restore: {target}"
        return envelope_error(
            message,
            code="protected_restore_unavailable",
            target_path=target,
            authorization_required=needs_auth,
            authorization_method=authorization_method_for_target(target),
            dry_run=True,
            planned_actions=[action],
        )
    if (
        not uninstall
        and state_dir is not None
        and install_target_not_plausible_official(target, state_dir / "install-record.json")
    ):
        message = (
            "refusing to install shim over a target that does not look like a real "
            "Claude binary -- it looks too small to be a real Claude app, more like "
            f"another program's launcher: {target}"
        )
        return envelope_error(
            message,
            code="target_not_plausible_official",
            target_path=target,
            authorization_required=needs_auth,
            authorization_method=authorization_method_for_target(target),
            dry_run=True,
            planned_actions=[action],
        )
    return envelope_ok(
        f"would {action}",
        target_path=target,
        authorization_required=needs_auth,
        authorization_method=authorization_method_for_target(target),
        dry_run=True,
        planned_actions=[action],
    )


def _build_dry_run_payload() -> Any:
    return envelope_ok(
        "planned build; no activation performed",
        dry_run=True,
        planned_actions=[
            "resolve enabled patches",
            "select current build strategy",
            "run source/package preflight if the current builder supports dry-run preflight",
            "build copied Claude binary only when the real build command is confirmed",
            "activate current symlink only after a successful real build",
        ],
    )


BUILD_ERROR_CODES = {
    "source_identity_mismatch": "source_identity_mismatch",
    "module_identity_failed": "module_identity_failed",
    "operation_resolution_failed": "operation_resolution_failed",
    "precondition_failed": "precondition_failed",
    "postcondition_failed": "postcondition_failed",
    "package_manifest_invalid": "package_manifest_invalid",
    "patch_conflict": "patch_conflict",
    "signing_failed": "signing_failed",
    "post_sign_inspection_failed": "post_sign_inspection_failed",
    "smoke_failed": "smoke_failed",
}


def _build_error_code(summary: str) -> str:
    prefix = summary.split(":", 1)[0]
    return BUILD_ERROR_CODES.get(prefix, "build_failed")


def _build_failure_summary(summary: str) -> str:
    if summary.startswith("source_identity_mismatch:"):
        parts = summary.split(":", 2)
        if len(parts) == 3:
            return f"Patch {parts[1]} is not compatible with this Claude Code source. {parts[2]}"
    return summary


def _build_report_json_payload(report: Any, report_path: Path | None = None) -> dict[str, Any]:
    # NOTE: build_patchset_v15 no longer produces "manual_smoke_pending" (the
    # manual-smoke activation gate is disabled — see builder_v15.py). This branch
    # is kept as defensive/backward-compatible handling in case a report ever
    # carries that status (e.g. an older cached build-report.json on disk).
    report_payload = dict(to_jsonable(report))
    ok = report_payload.get("status") in {"verified", "manual_smoke_pending"}
    if (
        report_payload.get("status") == "verified"
        and report_payload.get("activationStatus") == "activated"
    ):
        summary = "Build activated"
    elif report_payload.get("status") == "verified":
        summary = "Build verified; activation not performed"
    elif report_payload.get("status") == "manual_smoke_pending":
        summary = "Build requires manual smoke before activation"
    else:
        summary = _build_failure_summary(
            str(
                report_payload.get("failureReason")
                or report_payload.get("status")
                or "build failed"
            )
        )
    envelope = envelope_ok(
        summary,
        report_path=report_path,
        status="ok" if ok else "error",
        build_strategy=report_payload.get("buildStrategy") or report_payload.get("engine"),
        changed_modules=report_payload.get("changedModules", []),
        repack_summary=report_payload.get("repackSummary"),
    )
    payload = to_jsonable(envelope)
    payload["buildReportStatus"] = report_payload.get("status")
    if not ok:
        payload["ok"] = False
        raw_failure = str(report_payload.get("failureReason") or summary)
        payload["error"] = {"message": summary, "code": _build_error_code(raw_failure)}
    return payload


def _package_roots(paths: StatePaths) -> list[Path]:
    return [paths.patches_dir]


def _resolve_package(package_id_or_path: str, paths: StatePaths) -> Path:
    raw = Path(package_id_or_path).expanduser()
    if raw.exists():
        return raw
    for root in _package_roots(paths):
        candidate = root / package_id_or_path
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"patch package not found: {package_id_or_path}")


def _enabled_package_dirs(args: argparse.Namespace, paths: StatePaths, config) -> list[Path]:
    if args.packages:
        return [_resolve_package(item, paths) for item in args.packages]
    profile = active_profile(config)
    return [_resolve_package(item, paths) for item in profile.patches]


def _detected_claude_command_path() -> Path | None:
    found = shutil.which("claude")
    return Path(found) if found else None


def _discover_source(source_arg: str | None) -> Path | None:
    paths = default_paths()
    config = load_config(paths.config_path)
    if source_arg:
        return Path(source_arg).expanduser()
    return discover_official_claude(config, paths)


def _source_version_output(source: Path, explicit_output: str | None) -> str | None:
    if explicit_output:
        return explicit_output
    result = run_command([str(source), "--version"])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or result.stderr.strip() or None


def _source_version(explicit_version: str | None, version_output: str | None) -> str | None:
    if explicit_version:
        return explicit_version
    if not version_output:
        return None
    first = version_output.split(maxsplit=1)[0]
    return first or None


def _manifest_digests_for_build(package_dirs: list[Path]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for package_dir in package_dirs:
        try:
            manifest = load_package_manifest(package_dir, PackageKind.PATCH)
        except PackageValidationError:
            continue
        digests[manifest.id] = manifest_digest(manifest)
    return digests


def _patch_ids_for_build_snapshot(package_dirs: list[Path]) -> list[str]:
    patch_ids: list[str] = []
    for package_dir in package_dirs:
        try:
            manifest = load_package_manifest(package_dir, PackageKind.PATCH)
        except PackageValidationError:
            patch_ids.append(package_dir.name)
            continue
        patch_ids.append(manifest.id)
    return patch_ids


def _build_input_snapshot(config, package_dirs: list[Path]) -> dict[str, Any]:
    profile = active_profile(config)
    return {
        "patches": _patch_ids_for_build_snapshot(package_dirs),
        "promptAtBuildTime": profile.prompt,
        "optionsAtBuildTime": list(profile.options),
    }


def _default_output_dir(paths: StatePaths, config, source_version: str) -> Path:
    return paths.patchset_dir(source_version, config.activeProfile)


def _print_report_summary(report) -> None:
    print(f"status={report.status}")
    print(f"sourceSha256={report.sourceSha256}")
    print(f"enabledPatches={','.join(report.enabledPatches)}")
    if report.failureReason:
        print(f"failureReason={report.failureReason}")


def handle_build(args: argparse.Namespace, paths: StatePaths, config) -> int:
    if getattr(args, "dry_run", False):
        return emit(args, "planned build; no activation performed", _build_dry_run_payload())
    source = _discover_source(args.source)
    if source is None:
        message = "build requires --source or a claude executable on PATH"
        if args.json:
            print_json(envelope_error(message, code="missing_source"))
        else:
            print(message, file=sys.stderr)
        return 2
    if not source.exists():
        message = f"source does not exist: {source}"
        if args.json:
            print_json(envelope_error(message, code="missing_source"))
        else:
            print(message, file=sys.stderr)
        return 2
    version_output = _source_version_output(source, args.source_version_output)
    source_version = _source_version(args.source_version, version_output)
    if version_output is None or source_version is None:
        message = "build requires --source-version-output/--source-version or a working --version"
        if args.json:
            print_json(envelope_error(message, code="missing_source_version"))
        else:
            print(message, file=sys.stderr)
        return 2
    try:
        package_dirs = _enabled_package_dirs(args, paths, config)
    except FileNotFoundError as exc:
        if args.json:
            print_json(envelope_error(str(exc), code="missing_package"))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    if not package_dirs:
        message = "build requires enabled patches or at least one --package"
        if args.json:
            print_json(envelope_error(message, code="missing_package"))
        else:
            print(message, file=sys.stderr)
        return 2
    output_dir = (
        Path(args.output_dir).expanduser()
        if args.output_dir
        else _default_output_dir(paths, config, source_version)
    )
    report = build_patchset_v15(
        BuildRequestV15(
            source_path=source,
            output_dir=output_dir,
            package_dirs=package_dirs,
            source_version=source_version,
            source_version_output=version_output,
            platform=args.platform,
            arch=args.arch,
            run_signing=not args.skip_signing,
            run_smoke=not args.skip_smoke,
            activate=args.activate,
            current_path=paths.current_path,
            manifest_digests=_manifest_digests_for_build(package_dirs),
            build_input_snapshot=_build_input_snapshot(config, package_dirs),
            on_event=_progress_emitter(getattr(args, "progress", False)),
        )
    )
    if report.status == "verified" and report.activationStatus == "activated":
        config.activePatchSet = str(output_dir)
        save_config(paths.config_path, config)
    if args.json:
        print_json(_build_report_json_payload(report, output_dir / "build-report.json"))
    else:
        _print_report_summary(report)
    return 0 if report.status in {"verified", "manual_smoke_pending"} else 1


def _record_path(args: argparse.Namespace, state_dir: Path) -> Path:
    return Path(args.record).expanduser() if args.record else state_dir / "install-record.json"


def _resolve_cache_or_repair_target(args: argparse.Namespace, state_dir: Path) -> Path | None:
    """`--target` if given, else the current detection state: the install
    record's own `targetPath` (the target HarnessMonkey has previously
    managed, which is what cache-source/repair-shim reason about by
    default).
    """
    if args.target:
        return Path(args.target).expanduser()
    record_path = state_dir / "install-record.json"
    if not record_path.exists():
        return None
    try:
        raw = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    target = raw.get("targetPath") if isinstance(raw, dict) else None
    return Path(target).expanduser() if isinstance(target, str) else None


def handle_cache_source(args: argparse.Namespace, paths: StatePaths) -> int:
    state_dir = Path(args.state_dir).expanduser() if args.state_dir else paths.state_dir
    target = _resolve_cache_or_repair_target(args, state_dir)
    if target is None:
        payload = envelope_error(
            "cache-source requires --target or an install record with targetPath",
            code="missing_target",
        )
        if args.json:
            print_json(payload)
        else:
            print(payload.summary, file=sys.stderr)
        return 2
    try:
        result = cache_source_action(target, state_dir, paths)
    except CacheSourceRefused as exc:
        payload = envelope_error(str(exc), code=exc.code, target_path=target)
        if args.json:
            print_json(payload)
        else:
            print(str(exc), file=sys.stderr)
        return 1
    envelope = envelope_ok(f"cached official source {result['sha256'][:8]}", target_path=target)
    payload = to_jsonable(envelope)
    payload["cachedSourcePath"] = result["cachedSourcePath"]
    payload["sha256"] = result["sha256"]
    payload["sizeBytes"] = result["sizeBytes"]
    payload["version"] = result["version"]
    payload["gcRemovedDigests"] = result["gcRemovedDigests"]
    if args.json:
        print_json(payload)
    else:
        print(f"cachedSourcePath={result['cachedSourcePath']}")
    return 0


def handle_repair_shim(args: argparse.Namespace, paths: StatePaths) -> int:
    state_dir = Path(args.state_dir).expanduser() if args.state_dir else paths.state_dir
    target = _resolve_cache_or_repair_target(args, state_dir)
    if target is None:
        payload = envelope_error(
            "repair-shim requires --target or an install record with targetPath",
            code="missing_target",
        )
        if args.json:
            print_json(payload)
        else:
            print(payload.summary, file=sys.stderr)
        return 2
    try:
        result = repair_shim_action(target, state_dir, paths)
    except RepairRefused as exc:
        auth_required = exc.code == "authorization_required"
        payload = envelope_error(
            str(exc),
            code=exc.code,
            target_path=target,
            authorization_required=auth_required,
            authorization_method=(
                authorization_method_for_target(target) if auth_required else None
            ),
        )
        if args.json:
            print_json(payload)
        else:
            print(str(exc), file=sys.stderr)
        return 1
    reverted_immediately = result["revertedImmediately"]
    if reverted_immediately:
        # Fix 1: honest summary for the field-observed fast-revert loop --
        # the swap genuinely succeeded (see `repaired` below), but something
        # (observed: the official Claude installer's own self-heal) already
        # replaced the target again within seconds, so "repaired" alone
        # would read as a lie once the GUI's next refresh re-shows the
        # notice. Say so up front instead of letting it go silently stale.
        summary = (
            "Shim installed, but another program replaced it again within seconds"
            " -- likely the official Claude updater. It will keep doing this until"
            " that updater is dealt with."
        )
    else:
        summary = "repaired managed claude shim"
    envelope = envelope_ok(summary, target_path=target)
    payload = to_jsonable(envelope)
    payload["repaired"] = result["repaired"]
    payload["previousOfficialSha256"] = result["previousOfficialSha256"]
    payload["newOfficialSha256"] = result["newOfficialSha256"]
    payload["newOfficialVersion"] = result["newOfficialVersion"]
    payload["cachedSourcePath"] = result["cachedSourcePath"]
    payload["gcRemovedDigests"] = result["gcRemovedDigests"]
    payload["revertedImmediately"] = reverted_immediately
    payload["targetLocked"] = result["targetLocked"]
    if args.json:
        print_json(payload)
    else:
        print(f"repaired={str(result['repaired']).lower()}")
    return 0


def _target_from_args_or_record(args: argparse.Namespace, record_path: Path) -> Path | None:
    if args.target:
        return Path(args.target).expanduser()
    if not record_path.exists():
        return None
    try:
        raw = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid install record JSON: {record_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"invalid install record JSON: {record_path}")
    target = raw.get("targetPath")
    return Path(target) if isinstance(target, str) else None


def handle_restore(args: argparse.Namespace, paths: StatePaths) -> int:
    state_dir = Path(args.state_dir).expanduser() if args.state_dir else paths.state_dir
    record_path = _record_path(args, state_dir)
    command_label = "rollback" if args.command == "rollback" else "uninstall-shim"
    try:
        target = _target_from_args_or_record(args, record_path)
    except ValueError as exc:
        if getattr(args, "json", False):
            print_json(envelope_error(str(exc), code="invalid_record"))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    if target is None:
        payload = envelope_error(
            f"{command_label} requires --target or an install record with targetPath",
            code="missing_target",
        )
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print(
                f"{command_label} requires --target or an install record with targetPath",
                file=sys.stderr,
            )
        return 2
    authorization_required = target_needs_authorization(target)
    authorization_method = authorization_method_for_target(target)
    if getattr(args, "dry_run", False):
        payload = _dry_run_install_payload(target, uninstall=True)
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print(f"target={target}")
            print("dryRun=true")
        return 0
    try:
        restored = restore_install_transaction(
            target,
            record_path,
            force=args.force,
            on_event=_progress_emitter(getattr(args, "progress", False)),
        )
    except (AuthorizationRequired, AuthorizationDenied) as exc:
        code = (
            "authorization_denied"
            if isinstance(exc, AuthorizationDenied)
            else "authorization_required"
        )
        payload = envelope_error(
            str(exc),
            code=code,
            target_path=target,
            authorization_required=True,
            authorization_method=exc.method,
        )
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        payload = envelope_error(str(exc), code="filesystem_error", target_path=target)
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        if restored:
            print_json(
                envelope_ok(
                    "uninstalled managed claude shim",
                    target_path=target,
                    authorization_required=authorization_required,
                    authorization_method=authorization_method,
                )
            )
        else:
            print_json(
                envelope_error(
                    "managed shim was not restored", code="restore_failed", target_path=target
                )
            )
    else:
        print(f"restored={str(restored).lower()}")
    return 0 if restored else 1


def handle_set_prompt(args: argparse.Namespace, paths: StatePaths, config) -> int:
    if not args.from_file:
        return handle_set_prompt_package(args, paths, config)

    source_path = Path(args.prompt).expanduser()
    if not source_path.exists():
        message = f"prompt file does not exist: {source_path}"
        if args.json:
            print_json(envelope_error(message, code="missing_prompt_file"))
        else:
            print(message, file=sys.stderr)
        return 2

    try:
        prompt_id = validate_package_id(args.id)
    except PackageValidationError as exc:
        if args.json:
            print_json(envelope_error(str(exc), code="invalid_package_id"))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    package_dir = paths.prompts_dir / prompt_id
    package_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = package_dir / "prompt.md"
    prompt_path.write_text(source_path.read_text())
    manifest_path = package_dir / f"{prompt_id}.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "prompt",
                "id": prompt_id,
                "label": args.name or prompt_id,
                "description": f"Prompt package {prompt_id}",
                "risk": {"level": "low"},
                "prompt": {"mode": args.mode, "source": {"path": "prompt.md"}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    active_profile(config).prompt = prompt_id
    save_config(paths.config_path, config)
    return emit(args, f"set prompt profile {prompt_id}", envelope_ok(f"prompt set to {prompt_id}"))


def _strip_launch_separator(argv: list[str]) -> list[str]:
    if argv[:1] == ["--"]:
        return argv[1:]
    return argv


def _env_preview_delta(env_preview: dict[str, str], process_env: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in env_preview.items()
        if process_env.get(name) != value or value == "<redacted>"
    }


def _launch_preview_payload(
    paths: StatePaths, config, user_argv: list[str], process_env: dict[str, str]
) -> dict[str, Any]:
    result = compute_launch_with_paths(paths, config, user_argv, process_env)
    return {
        "schemaVersion": 1,
        "targetClaudePath": None if result.target.kind == "missing" else str(result.target.path),
        "targetClaudeKind": result.target.kind,
        "argv": result.argv,
        "envPreview": _env_preview_delta(result.env_preview, process_env),
        "skipped": result.skipped,
        "warnings": result.warnings,
        "errors": result.errors,
    }


def handle_launch_preview(args: argparse.Namespace, paths: StatePaths, config) -> int:
    user_argv = _strip_launch_separator(list(args.argv))
    payload = _launch_preview_payload(paths, config, user_argv, dict(os.environ))
    if args.json:
        print_json(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def handle_add_package(args: argparse.Namespace, paths: StatePaths, kind: str) -> int:
    source = Path(args.source_dir).expanduser()
    result = add_package(source, kind, paths.state_dir)
    if args.json:
        print_json(result)
    else:
        print(result["summary"], file=sys.stdout if result["ok"] else sys.stderr)
    return 0 if result["ok"] else 1


def _repo_packages_root() -> Path:
    return Path(__file__).resolve().parents[2] / "packages"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_state_dirs(paths: StatePaths, config) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.bin_dir.mkdir(parents=True, exist_ok=True)
    paths.patches_dir.mkdir(parents=True, exist_ok=True)
    paths.prompts_dir.mkdir(parents=True, exist_ok=True)
    paths.options_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.versions_dir.mkdir(parents=True, exist_ok=True)
    if not paths.config_path.exists():
        save_config(paths.config_path, config)


def _install_package_result(source: Path, paths: StatePaths) -> dict:
    # `install` is the repo -> state sync path: it must refresh packages whose
    # on-disk copy is stale (old schemaVersion, old pins, etc. from an earlier
    # dev install) rather than silently skipping them because the dest dir
    # already exists (BUG 1). `add_package(overwrite=True)` itself reports
    # installed/updated/unchanged per package; bare `add-patch` (handle_add_package)
    # keeps the default `overwrite=False` no-clobber behavior for manual adds.
    return add_package(source, "patch", paths.state_dir, overwrite=True)


def _repo_patch_package_dirs(packages_root: Path) -> list[Path]:
    if not packages_root.exists():
        return []
    return sorted(
        path
        for path in packages_root.iterdir()
        if path.is_dir() and (path / "patch.json").exists()
    )


def handle_install(args: argparse.Namespace, paths: StatePaths, config) -> int:
    _ensure_state_dirs(paths, config)
    packages: dict[str, dict] = {}
    ok = True
    for package_dir in _repo_patch_package_dirs(_repo_packages_root()):
        result = _install_package_result(package_dir, paths)
        packages[package_dir.name] = result
        ok = ok and bool(result.get("ok"))

    launch_payload: dict[str, Any]
    if args.cli:
        launch_payload = {"skipped": True, "ok": True}
    else:
        # BUG 3: a LaunchAgent pointed at the repo venv script dies at Python
        # startup (PermissionError on pyvenv.cfg) when the clone lives under a
        # TCC-protected path like ~/Documents -- launchd-spawned processes get
        # no Documents access, unlike Terminal.app. Provision a dedicated venv
        # at <state_dir>/app (outside any TCC-protected location) and point
        # the LaunchAgent there instead.
        provisioning_warning: str | None = None
        gui_path: Path | None = None
        try:
            launch_agent.provision_app_venv(_repo_root(), paths.state_dir)
            gui_path = launch_agent.app_gui_executable(paths.state_dir)
        except Exception as exc:
            provisioning_warning = (
                f"Could not provision the app runtime ({exc}); falling back to "
                "the repo virtualenv. Login-launch may not work if this repo "
                "lives in a TCC-protected location (e.g. ~/Documents). Run "
                "manually instead: uv run harnessmonkey-gui"
            )
            try:
                gui_path = launch_agent.gui_executable()
            except Exception:
                gui_path = None

        if gui_path is None:
            launch_payload = {
                "skipped": False,
                "ok": False,
                "provisioningWarning": provisioning_warning,
                "error": {
                    "message": provisioning_warning or "no gui executable available",
                    "code": "launch_agent_failed",
                },
            }
            ok = False
        else:
            try:
                result = launch_agent.install_agent(gui_path, home=Path.home())
                agent_ok = result.returncode == 0
                launch_payload = {
                    "skipped": False,
                    "ok": agent_ok,
                    "guiExecutable": str(gui_path),
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
                if provisioning_warning:
                    launch_payload["provisioningWarning"] = provisioning_warning
                ok = ok and agent_ok
            except Exception as exc:
                launch_payload = {
                    "skipped": False,
                    "ok": False,
                    "error": {"message": str(exc), "code": "launch_agent_failed"},
                }
                if provisioning_warning:
                    launch_payload["provisioningWarning"] = provisioning_warning
                ok = False

    payload = {
        "schemaVersion": 1,
        "ok": ok,
        "status": "ok" if ok else "error",
        "summary": "installed HarnessMonkey manager" if ok else "HarnessMonkey install incomplete",
        "stateDir": str(paths.state_dir),
        "packages": packages,
        "launchAgent": launch_payload,
        "nextStep": "Menubar: click the monkey → Install to set up your shim",
    }
    if args.json:
        print_json(payload)
    else:
        for package_id, result in packages.items():
            stream = sys.stdout if result.get("ok") else sys.stderr
            print(f"{package_id}: {result.get('summary')}", file=stream)
        if launch_payload.get("skipped"):
            print("LaunchAgent skipped (--cli)")
        else:
            if launch_payload.get("provisioningWarning"):
                print(f"Warning: {launch_payload['provisioningWarning']}", file=sys.stderr)
            if launch_payload.get("guiExecutable"):
                app_runtime = Path(launch_payload["guiExecutable"]).parent.parent
                print(f"App runtime: {app_runtime}")
            if launch_payload.get("ok"):
                print("LaunchAgent installed")
                # BUG 2: launchd launches in a bare environment; if the app
                # dies before it can open its own log, this is the only
                # diagnostic trail. Always point the user at it, even on the
                # happy path, since a missing menubar icon may not surface as
                # a returncode. Registration succeeding is also not the same
                # as macOS actually showing the icon (BUG 3 handoff): a Login
                # Items & Extensions approval gate can still block it.
                log_path = launch_agent.menubar_log_path(Path.home())
                print(
                    "If the menubar icon doesn't appear, check System "
                    "Settings → General → Login Items & Extensions "
                    f"(macOS approval), and see {log_path}"
                )
            else:
                print(f"LaunchAgent failed: {launch_payload.get('error')}", file=sys.stderr)
        print(payload["nextStep"])
    return 0 if ok else 1


def handle_uninstall(args: argparse.Namespace, paths: StatePaths) -> int:
    try:
        result = launch_agent.uninstall_agent(home=Path.home())
        ok = result.returncode == 0
        launch_payload = {
            "ok": ok,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as exc:
        ok = False
        launch_payload = {
            "ok": False,
            "error": {"message": str(exc), "code": "launch_agent_uninstall_failed"},
        }
    payload = {
        "schemaVersion": 1,
        "ok": ok,
        "status": "ok" if ok else "error",
        "summary": (
            "removed HarnessMonkey LaunchAgent" if ok else "HarnessMonkey uninstall incomplete"
        ),
        "stateDir": str(paths.state_dir),
        "launchAgent": launch_payload,
        "stateDirUntouched": True,
        "shimUntouched": True,
        "nextSteps": [
            "State dir is untouched; delete ~/.harnessmonkey manually for full data removal.",
            "Shim is untouched; run uninstall-shim to restore the claude target.",
        ],
    }
    if args.json:
        print_json(payload)
    else:
        if ok:
            print("LaunchAgent removed")
        else:
            print(f"LaunchAgent removal failed: {launch_payload.get('error')}", file=sys.stderr)
        print("State dir untouched; delete ~/.harnessmonkey manually for full data removal.")
        print("Shim untouched; run uninstall-shim to restore the claude target.")
    return 0 if ok else 1


def _profile_dict(config) -> dict:
    profile = active_profile(config)
    return {
        "prompt": profile.prompt,
        "patches": list(profile.patches),
        "options": list(profile.options),
    }


def handle_remove_package(
    args: argparse.Namespace, paths: StatePaths, config, kind: str, package_id: str
) -> int:
    result = remove_package(package_id, kind, paths.state_dir, _profile_dict(config))
    if args.json:
        print_json(result)
    else:
        print(result["summary"], file=sys.stdout if result["ok"] else sys.stderr)
    return 0 if result["ok"] else 1


def _slugify_prompt_stem(stem: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", stem.lower()).strip("-")


def handle_add_prompt(args: argparse.Namespace, paths: StatePaths) -> int:
    source_path = Path(args.path).expanduser()
    if not source_path.is_file():
        # Important-3 fix: use the same 6-key packages_admin envelope / invalid_package
        # code / exit 1 as every other add-* failure, not the 14-key CommandEnvelope
        # with a bespoke missing_source_file code and exit 2.
        message = f"prompt source file does not exist: {source_path}"
        result = invalid_package_error(message)
        if args.json:
            print_json(result)
        else:
            print(message, file=sys.stderr)
        return 1

    package_id = args.id or _slugify_prompt_stem(source_path.stem)
    try:
        validate_package_id(package_id)
    except PackageValidationError as exc:
        # Critical-1/Critical-2 fix: validate the id (whether from --id or derived
        # via slugify) BEFORE it is ever used to build a filesystem path. This
        # rejects both path-traversal ids (e.g. "../evil") and ids that slugify to
        # "" (e.g. a "###.md" source file, which previously made staging_dir equal
        # the tempdir itself and crashed with a raw FileExistsError).
        message = f"invalid package id {package_id!r} derived from {source_path.name!r}: {exc}"
        result = invalid_package_error(message)
        if args.json:
            print_json(result)
        else:
            print(message, file=sys.stderr)
        return 1

    manifest = scaffold_prompt_package(source_path, package_id, args.name)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp).resolve()
        staging_dir = tmp_root / package_id
        # Defense-in-depth: validate_package_id above already guarantees package_id
        # cannot escape tmp_root when joined, but refuse to proceed if it somehow did.
        if not staging_dir.resolve(strict=False).is_relative_to(tmp_root):
            result = invalid_package_error(f"invalid package id: {package_id!r}")
            if args.json:
                print_json(result)
            else:
                print(result["summary"], file=sys.stderr)
            return 1
        staging_dir.mkdir(parents=True)
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        shutil.copyfile(source_path, staging_dir / "prompt.md")
        result = add_package(staging_dir, "prompt", paths.state_dir)

    if args.json:
        print_json(result)
    else:
        print(result["summary"], file=sys.stdout if result["ok"] else sys.stderr)
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if getattr(os, "geteuid", lambda: 1)() == 0:
        message = (
            "refusing to run harnessmonkey manager as root; use the normal user "
            "process and let HarnessMonkey request narrow authorization for protected "
            "install/restore file operations"
        )
        payload = envelope_error(message, code="root_process_refused")
        if getattr(args, "json", False):
            print_json(payload)
        else:
            print(message, file=sys.stderr)
        return 1
    paths = default_paths()
    config = load_config(paths.config_path)
    if args.command == "launch-preview":
        return handle_launch_preview(args, paths, config)
    if args.command == "install":
        return handle_install(args, paths, config)
    if args.command == "uninstall":
        return handle_uninstall(args, paths)
    if args.command == "list-options":
        payload = _list_payload(paths, config, PackageKind.OPTION)
        if args.json:
            print_json(payload)
        else:
            _print_package_ids(payload, "options")
        return 0
    if args.command == "enable-patch":
        return handle_enable_patch(args, paths, config)
    if args.command == "disable-patch":
        return handle_disable_patch(args, paths, config)
    if args.command == "enable-option":
        return handle_enable_option(args, paths, config)
    if args.command == "disable-option":
        return handle_disable_option(args, paths, config)
    if args.command == "status":
        if args.json:
            print_json(status_payload(paths, config))
        else:
            print(f"stateDir={paths.state_dir}")
            print(f"patchesDir={paths.patches_dir}")
            print(f"activeProfile={config.activeProfile}")
            print(f"activePatchSet={config.activePatchSet}")
            if paths.current_path.exists() or paths.current_path.is_symlink():
                print(f"current={paths.current_path.resolve()}")
        return 0
    if args.command == "enable":
        profile = active_profile(config)
        if args.patch_id not in profile.patches:
            profile.patches.append(args.patch_id)
        save_config(paths.config_path, config)
        return emit(
            args,
            f"enabled {args.patch_id}; rebuild required",
            envelope_ok(f"enabled {args.patch_id}; rebuild required", status="rebuild_required"),
        )
    if args.command == "disable":
        profile = active_profile(config)
        profile.patches = [item for item in profile.patches if item != args.patch_id]
        save_config(paths.config_path, config)
        return emit(
            args,
            f"disabled {args.patch_id}; rebuild required",
            envelope_ok(f"disabled {args.patch_id}; rebuild required", status="rebuild_required"),
        )
    if args.command == "list-patches":
        payload = _list_payload(paths, config, PackageKind.PATCH)
        if args.json:
            print_json(payload)
        else:
            _print_package_ids(payload, "patches")
        return 0
    if args.command == "list-prompts":
        payload = _list_payload(paths, config, PackageKind.PROMPT)
        if args.json:
            print_json(payload)
        else:
            _print_package_ids(payload, "prompts")
        return 0
    if args.command == "set-prompt":
        return handle_set_prompt_package(args, paths, config)
    if args.command == "clear-prompt":
        active_profile(config).prompt = None
        save_config(paths.config_path, config)
        return emit(args, "cleared active prompt profile", envelope_ok("prompt cleared"))
    if args.command == "add-patch":
        return handle_add_package(args, paths, "patch")
    if args.command == "add-option":
        return handle_add_package(args, paths, "option")
    if args.command == "add-prompt":
        return handle_add_prompt(args, paths)
    if args.command == "remove-patch":
        return handle_remove_package(args, paths, config, "patch", args.patch_id)
    if args.command == "remove-option":
        return handle_remove_package(args, paths, config, "option", args.option_id)
    if args.command == "remove-prompt":
        return handle_remove_package(args, paths, config, "prompt", args.prompt_id)
    if args.command == "inspect-binary":
        source = Path(args.source).expanduser()
        payload = inspect_binary_bytes(source.read_bytes(), source_path=str(source))
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"supported={str(payload['supported']).lower()}")
            print(f"modules={len(payload['modules'])}")
        return 0 if payload["ok"] and not payload["validationErrors"] else 1
    if args.command == "validate-package":
        payload = validate_package(
            ValidationRequestV15(
                source_path=Path(args.source).expanduser(),
                package_dir=Path(args.package).expanduser(),
                source_version=args.source_version,
                source_version_output=args.source_version_output,
                platform=args.platform,
                arch=args.arch,
            )
        )
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"ok={str(payload['ok']).lower()}")
        return 0 if payload["ok"] else 1
    if args.command == "build":
        return handle_build(args, paths, config)
    if args.command == "install-shim":
        state_dir = Path(args.state_dir).expanduser() if args.state_dir else paths.state_dir
        if not args.target:
            payload = envelope_error("install-shim requires --target", code="missing_target")
            if args.json:
                print_json(payload)
            else:
                print("install-shim requires --target", file=sys.stderr)
            return 2
        target = Path(args.target).expanduser()
        authorization_required = target_needs_authorization(target)
        authorization_method = authorization_method_for_target(target)
        if args.dry_run:
            payload = _dry_run_install_payload(target, state_dir=state_dir)
            if args.json:
                print_json(payload)
            else:
                if getattr(payload, "ok", False):
                    print(f"installRecord={state_dir / 'install-record.json'}")
                    print("dryRun=true")
                else:
                    print(payload.summary, file=sys.stderr)
            return 0 if getattr(payload, "ok", False) else 1
        install_kwargs: dict[str, Any] = {}
        progress_emitter = _progress_emitter(getattr(args, "progress", False))
        if progress_emitter is not None:
            install_kwargs["on_event"] = progress_emitter
        try:
            record = install_shim_transaction(target, state_dir, dry_run=False, **install_kwargs)
        except ProtectedTargetRestoreUnavailable as exc:
            payload = envelope_error(
                str(exc),
                code="protected_restore_unavailable",
                target_path=target,
                authorization_required=authorization_required,
                authorization_method=authorization_method,
            )
            if args.json:
                print_json(payload)
            else:
                print(str(exc), file=sys.stderr)
            return 1
        except TargetNotPlausibleOfficial as exc:
            payload = envelope_error(
                str(exc),
                code="target_not_plausible_official",
                target_path=target,
                authorization_required=authorization_required,
                authorization_method=authorization_method,
            )
            if args.json:
                print_json(payload)
            else:
                print(str(exc), file=sys.stderr)
            return 1
        except (AuthorizationRequired, AuthorizationDenied) as exc:
            code = (
                "authorization_denied"
                if isinstance(exc, AuthorizationDenied)
                else "authorization_required"
            )
            payload = envelope_error(
                str(exc),
                code=code,
                target_path=target,
                authorization_required=True,
                authorization_method=exc.method,
            )
            if args.json:
                print_json(payload)
            else:
                print(str(exc), file=sys.stderr)
            return 1
        except OSError as exc:
            if args.json:
                print_json(envelope_error(str(exc), code="filesystem_error", target_path=target))
            else:
                print(str(exc), file=sys.stderr)
            return 1
        if args.json:
            payload = to_jsonable(
                envelope_ok(
                    "installed managed claude shim",
                    target_path=target,
                    authorization_required=authorization_required,
                    authorization_method=authorization_method,
                )
            )
            # Shim lock feature: additive `targetLocked` field. Read back
            # from the install record itself rather than changing
            # `install_shim_transaction`'s return type -- every existing
            # caller/test relies on it returning `record_path` (a Path).
            record_data = json.loads(record.read_text()) if record.exists() else {}
            payload["targetLocked"] = record_data.get("targetLocked", False)
            print_json(payload)
        else:
            print(f"installRecord={record}")
            print("dryRun=false")
        return 0
    if args.command in {"uninstall-shim", "rollback"}:
        return handle_restore(args, paths)
    if args.command == "cache-source":
        return handle_cache_source(args, paths)
    if args.command == "repair-shim":
        return handle_repair_shim(args, paths)
    if args.command == "use-official":
        if not args.official:
            message = "use-official requires --official"
            if args.json:
                print_json(envelope_error(message, code="missing_official"))
            else:
                print(message, file=sys.stderr)
            return 2
        official = Path(args.official).expanduser()
        if not official.exists():
            message = f"official path does not exist: {official}"
            if args.json:
                print_json(envelope_error(message, code="missing_official"))
            else:
                print(message, file=sys.stderr)
            return 2
        official = official.resolve()
        use_official(paths.current_path, official)
        config.activePatchSet = None
        config.officialClaudePath = str(official)
        save_config(paths.config_path, config)
        if args.json:
            print_json(envelope_ok("using official Claude binary", target_path=official))
        else:
            print(f"current={paths.current_path.resolve()}")
        return 0
    if args.command == "doctor":
        print(f"stateDir={paths.state_dir}")
        print(f"sourceDiscovery={_discover_source(None) or 'missing'}")
        recorded = recorded_source_path(paths)
        if config.officialClaudePath and recorded is not None:
            configured = Path(config.officialClaudePath).expanduser().resolve(strict=False)
            if configured != recorded:
                print(
                    "warning: config officialClaudePath differs from the shim "
                    f"install record's source\n  config:  {configured}\n"
                    f"  record:  {recorded}\n"
                    "  builds use the config value; if the recorded source is newer, "
                    "update officialClaudePath (use-official) or re-run install-shim"
                )
        return 0
    parser.print_help()
    return 0
