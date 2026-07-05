from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATUS_LABELS = {
    "ok": "OK",
    "warning": "Warning",
    "rebuild_required": "Rebuild Required",
    "error": "Error",
    "not_installed": "Not Installed",
    "unknown": "Unknown",
}
COMMAND_STATUSES = {"ok", "rebuild_required", "error", "not_installed", "unknown"}
AUTHORIZATION_METHODS = {None, "macos_gui", "sudo", "not_available"}


@dataclass(frozen=True)
class ErrorInfo:
    message: str
    code: str | None = None


@dataclass(frozen=True)
class CommandEnvelope:
    ok: bool
    status: str
    summary: str
    report_path: Path | None
    target_path: Path | None
    authorization_required: bool
    authorization_method: str | None
    dry_run: bool
    planned_actions: tuple[str, ...]
    error: ErrorInfo | None


@dataclass(frozen=True)
class PatchMenuItem:
    patch_id: str
    label: str
    checked: bool
    active_enabled: bool
    available: bool
    compatibility_status: str
    compatibility_message: str | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromptMenuItem:
    prompt_id: str
    label: str
    checked: bool
    mode: str
    source_path: Path | None


@dataclass(frozen=True)
class OptionMenuItem:
    option_id: str
    label: str
    enabled: bool
    valid: bool
    compatibility_status: str
    risk_level: str
    requires_confirmation: bool = False
    errors: tuple[str, ...] = ()
    status_warning: str | None = None


@dataclass(frozen=True)
class HighRiskOptionSummary:
    option_id: str
    label: str
    warning: str

    @property
    def id(self) -> str:
        return self.option_id


@dataclass(frozen=True)
class MenuState:
    status: str
    status_label: str
    source_claude_version: str | None
    source_claude_path: Path | None
    detected_claude_command_path: Path | None
    install_mode: str
    shim_installed: bool
    active_profile: str | None
    active_prompt: str | None
    desired_patch_ids: tuple[str, ...]
    active_patch_ids: tuple[str, ...]
    rebuild_required: bool
    latest_build_report_path: Path | None
    active_patch_set: str | None
    current_claude_path: Path | None
    shim_target_path: Path | None
    install_record_path: Path | None
    last_build_strategy: str
    changed_modules: tuple[dict[str, Any], ...]
    repack_summary: dict[str, Any] | None
    state_dir: Path
    logs_dir: Path
    last_error: ErrorInfo | None
    patch_items: tuple[PatchMenuItem, ...]
    prompt_items: tuple[PromptMenuItem, ...]
    built_patch_ids: tuple[str, ...] = ()
    patched_build_active: bool = False
    target_claude_kind: str = "unknown"
    active_option_ids: tuple[str, ...] = ()
    high_risk_options: tuple[HighRiskOptionSummary, ...] = ()
    compatibility_status: str = "unknown"
    manifest_compatibility_status: str = "unknown"
    source_identity_status: str = "unknown"
    last_build_compatibility_status: str = "unknown"
    live_validation_status: str = "unknown"
    compatibility_warnings: tuple[str, ...] = ()
    option_items: tuple[OptionMenuItem, ...] = ()
    high_risk_warnings: tuple[str, ...] = ()
    # shim-update-resilience stage 1 (spec 2026-07-04 section 1): additive,
    # optional fields describing whether the managed shim target was
    # replaced by an official Claude update. All default to the "nothing
    # detected" shape so older/partial status payloads parse unchanged.
    shim_previously_managed: bool = False
    target_replaced_by_official: bool = False
    detected_official_sha256: str | None = None
    detected_official_version: str | None = None
    shim_repair_available: bool = False
    rollout_required: bool = False
    # Opportunistic: `lastManagedTargetPath` is a CLI-side field landing in a
    # parallel worktree (not present in this worktree's CLI output yet).
    # Parsed here if present, tolerating absence, so the GUI can name the
    # concrete repair target as soon as the CLI starts emitting it -- see
    # `window_model.repair_target_path` / the GUI report's "repair target"
    # investigation for why no *other* status field is a reliable stand-in
    # today.
    last_managed_target_path: Path | None = None
    # Shim lock feature: additive, optional. Mirrors `shimInstalled`'s own
    # opportunistic-parse pattern above -- defaults to False so status
    # payloads from before this field existed (or from non-mac hosts) parse
    # unchanged.
    shim_locked: bool = False


def _optional_path(value: Any) -> Path | None:
    return Path(str(value)).expanduser() if value else None


def parse_error(raw: Any) -> ErrorInfo | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw.get("message"):
        raise ValueError("error must be null or object with non-empty message")
    code = raw.get("code")
    return ErrorInfo(message=str(raw["message"]), code=str(code) if code is not None else None)


def _required_bool(raw: dict[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def _optional_bool(raw: dict[str, Any], key: str, default: bool = False) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def _bool_if_present(raw: dict[str, Any], key: str) -> bool | None:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def _planned_actions(raw: dict[str, Any]) -> tuple[str, ...]:
    value = raw.get("plannedActions", [])
    if not isinstance(value, list):
        raise ValueError("plannedActions must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ValueError("plannedActions items must be strings")
    return tuple(value)


def _require_schema(raw: dict[str, Any]) -> None:
    if raw.get("schemaVersion") != 1:
        raise ValueError("schemaVersion must be 1")


def _authorization_method(raw: dict[str, Any]) -> str | None:
    value = raw.get("authorizationMethod")
    if value is not None and not isinstance(value, str):
        raise ValueError("authorizationMethod must be null, macos_gui, sudo, or not_available")
    if value not in AUTHORIZATION_METHODS:
        raise ValueError("authorizationMethod must be null, macos_gui, sudo, or not_available")
    return value


def _string_list(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} items must be strings")
    return tuple(value)


def _dict_list(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} items must be objects")
    return value


def parse_command_envelope(raw: dict[str, Any]) -> CommandEnvelope:
    _require_schema(raw)
    error = parse_error(raw.get("error"))
    ok = _required_bool(raw, "ok")
    if ok and error is not None:
        raise ValueError("ok envelope must have error=null")
    if not ok and error is None:
        raise ValueError("failed envelope must include error.message")
    status = str(raw.get("status", "unknown"))
    if status not in COMMAND_STATUSES:
        raise ValueError(f"unsupported status: {status}")
    if ok and status == "error":
        raise ValueError("ok envelope cannot have error status")
    if not ok and status == "ok":
        raise ValueError("failed envelope cannot have ok status")
    return CommandEnvelope(
        ok=ok,
        status=status,
        summary=str(raw.get("summary", "")),
        report_path=_optional_path(raw.get("reportPath")),
        target_path=_optional_path(raw.get("targetPath")),
        authorization_required=_optional_bool(raw, "authorizationRequired", False),
        authorization_method=_authorization_method(raw),
        dry_run=_optional_bool(raw, "dryRun", False),
        planned_actions=_planned_actions(raw),
        error=error,
    )


def normalize_status(raw_status: str, rebuild_required: bool, last_error: ErrorInfo | None) -> str:
    if last_error is not None or raw_status == "error":
        return "error"
    if raw_status == "not_installed":
        return "not_installed"
    if rebuild_required or raw_status == "rebuild_required":
        return "rebuild_required"
    if raw_status == "warning":
        return "warning"
    if raw_status == "ok":
        return "ok"
    return "unknown"


def _high_risk_options(raw: dict[str, Any]) -> tuple[HighRiskOptionSummary, ...]:
    return tuple(
        HighRiskOptionSummary(
            option_id=str(item["id"]),
            label=str(item.get("label", item["id"])),
            warning=str(item["warning"]),
        )
        for item in _dict_list(raw, "highRiskOptions")
    )


def _high_risk_warnings(raw: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(item["warning"]) for item in _dict_list(raw, "highRiskOptions"))


def _prompt_source_path(item: dict[str, Any]) -> Path | None:
    if "sourcePath" not in item or item.get("sourcePath") in {None, ""}:
        return None
    return Path(str(item["sourcePath"])).expanduser()


def _option_items(options_raw: dict[str, Any] | None) -> tuple[OptionMenuItem, ...]:
    if options_raw is None:
        return ()
    _require_schema(options_raw)
    return tuple(
        OptionMenuItem(
            option_id=str(item["id"]),
            label=str(item.get("label", item["id"])),
            enabled=_required_bool(item, "enabled"),
            valid=_required_bool(item, "valid"),
            compatibility_status=str(item.get("compatibilityStatus", "unknown")),
            risk_level=str(item.get("riskLevel", "unknown")),
            requires_confirmation=_optional_bool(item, "requiresConfirmation", False),
            errors=_string_list(item, "errors"),
            status_warning=str(item["statusWarning"]) if item.get("statusWarning") else None,
        )
        for item in _dict_list(options_raw, "options")
    )


def _patch_checked(raw: dict[str, Any], desired_patch_ids: tuple[str, ...]) -> bool:
    desired = _bool_if_present(raw, "desiredEnabled")
    if desired is not None:
        return desired
    enabled = _bool_if_present(raw, "enabled")
    if enabled is not None:
        return enabled
    return str(raw["id"]) in desired_patch_ids


def _patch_active_enabled(raw: dict[str, Any], active_patch_ids: tuple[str, ...]) -> bool:
    active = _bool_if_present(raw, "activeEnabled")
    if active is not None:
        return active
    return str(raw["id"]) in active_patch_ids


def _patch_available(raw: dict[str, Any]) -> bool:
    available = _bool_if_present(raw, "available")
    if available is None:
        available = True
    valid = _bool_if_present(raw, "valid")
    if valid is False:
        return False
    return available


def _prompt_checked(raw: dict[str, Any], active_prompt: Any) -> bool:
    active = _bool_if_present(raw, "active")
    if active is None:
        active = _bool_if_present(raw, "enabled")
    checked = bool(active) if active is not None else False
    return checked or str(raw["id"]) == active_prompt


def parse_menu_state(
    status_raw: dict[str, Any],
    patches_raw: dict[str, Any],
    prompts_raw: dict[str, Any],
    options_raw: dict[str, Any] | None = None,
) -> MenuState:
    _require_schema(status_raw)
    _require_schema(patches_raw)
    _require_schema(prompts_raw)
    last_error = parse_error(status_raw.get("lastError"))
    rebuild_required = _required_bool(status_raw, "rebuildRequired")
    status = normalize_status(
        str(status_raw.get("status", "unknown")), rebuild_required, last_error
    )
    rebuild_required = rebuild_required or status == "rebuild_required"
    desired_patch_ids = _string_list(status_raw, "desiredPatchIds")
    active_patch_ids = _string_list(status_raw, "activePatchIds")
    active_prompt = status_raw.get("activePrompt")
    patch_items = tuple(
        PatchMenuItem(
            patch_id=str(item["id"]),
            label=str(item.get("label", item["id"])),
            checked=_patch_checked(item, desired_patch_ids),
            active_enabled=_patch_active_enabled(item, active_patch_ids),
            available=_patch_available(item),
            compatibility_status=str(item.get("compatibilityStatus", "unknown")),
            compatibility_message=str(item["compatibilityMessage"])
            if item.get("compatibilityMessage")
            else None,
            errors=_string_list(item, "errors"),
        )
        for item in _dict_list(patches_raw, "patches")
    )
    prompt_items = tuple(
        PromptMenuItem(
            prompt_id=str(item["id"]),
            label=str(item.get("label", item["id"])),
            checked=_prompt_checked(item, active_prompt),
            mode=str(item.get("mode", "append")),
            source_path=_prompt_source_path(item),
        )
        for item in _dict_list(prompts_raw, "prompts")
    )
    return MenuState(
        status=status,
        status_label=STATUS_LABELS[status],
        source_claude_version=status_raw.get("sourceClaudeVersion"),
        source_claude_path=_optional_path(status_raw.get("sourceClaudePath")),
        detected_claude_command_path=_optional_path(status_raw.get("detectedClaudeCommandPath")),
        install_mode=str(status_raw.get("installMode", "shim")),
        shim_installed=_optional_bool(status_raw, "shimInstalled", False),
        active_profile=status_raw.get("activeProfile"),
        active_prompt=active_prompt,
        desired_patch_ids=desired_patch_ids,
        active_patch_ids=active_patch_ids,
        rebuild_required=rebuild_required,
        latest_build_report_path=_optional_path(status_raw.get("latestBuildReportPath")),
        active_patch_set=status_raw.get("activePatchSet"),
        current_claude_path=_optional_path(status_raw.get("currentClaudePath")),
        shim_target_path=_optional_path(status_raw.get("shimTargetPath")),
        install_record_path=_optional_path(status_raw.get("installRecordPath")),
        last_build_strategy=str(
            status_raw.get("lastBuildStrategy") or status_raw.get("buildStrategy") or "unknown"
        ),
        changed_modules=tuple(_dict_list(status_raw, "changedModules")),
        repack_summary=status_raw.get("repackSummary"),
        state_dir=Path(str(status_raw["stateDir"])).expanduser(),
        logs_dir=Path(str(status_raw["logsDir"])).expanduser(),
        last_error=last_error,
        patch_items=patch_items,
        prompt_items=prompt_items,
        built_patch_ids=_string_list(status_raw, "builtPatchIds"),
        patched_build_active=_optional_bool(status_raw, "patchedBuildActive", False),
        target_claude_kind=str(status_raw.get("targetClaudeKind", "unknown")),
        active_option_ids=_string_list(status_raw, "activeOptionIds"),
        high_risk_options=_high_risk_options(status_raw),
        compatibility_status=str(status_raw.get("compatibilityStatus", "unknown")),
        manifest_compatibility_status=str(
            status_raw.get("manifestCompatibilityStatus", "unknown")
        ),
        source_identity_status=str(status_raw.get("sourceIdentityStatus", "unknown")),
        last_build_compatibility_status=str(
            status_raw.get("lastBuildCompatibilityStatus", "unknown")
        ),
        live_validation_status=str(status_raw.get("liveValidationStatus", "unknown")),
        compatibility_warnings=_string_list(status_raw, "compatibilityWarnings"),
        option_items=_option_items(options_raw),
        high_risk_warnings=_high_risk_warnings(status_raw),
        shim_previously_managed=_optional_bool(status_raw, "shimPreviouslyManaged", False),
        target_replaced_by_official=_optional_bool(status_raw, "targetReplacedByOfficial", False),
        detected_official_sha256=status_raw.get("detectedOfficialSha256"),
        detected_official_version=status_raw.get("detectedOfficialVersion"),
        shim_repair_available=_optional_bool(status_raw, "shimRepairAvailable", False),
        rollout_required=_optional_bool(status_raw, "rolloutRequired", False),
        last_managed_target_path=_optional_path(status_raw.get("lastManagedTargetPath")),
        shim_locked=_optional_bool(status_raw, "shimLocked", False),
    )
