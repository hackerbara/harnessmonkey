from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

PROMPT_FLAGS = {
    "--system-prompt",
    "--system-prompt-file",
    "--append-system-prompt",
    "--append-system-prompt-file",
}
TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "kind",
    "id",
    "label",
    "description",
    "packageVersion",
    "requiresPackages",
    "conflictsWithPackages",
    "risk",
    "compatibility",
    "prompt",
    "option",
    "patch",
}
RISK_LEVELS = {"low", "medium", "high"}
PROMPT_MODES = {"append", "replace"}
ENV_CONFLICT_POLICIES = {"override", "error"}
SUPPORTED_PATCH_ENGINES = {"bun_graph_repack"}


class PackageKind(StrEnum):
    PATCH = "patch"
    PROMPT = "prompt"
    OPTION = "option"


class PackageValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Risk:
    level: str
    notes: str | None = None
    requires_confirmation: bool = False
    status_warning: str | None = None


@dataclass(frozen=True)
class Compatibility:
    claude_versions: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    arches: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class PromptSource:
    path: Path
    sha256: str | None = None


@dataclass(frozen=True)
class PromptPackage:
    mode: str
    source: PromptSource


@dataclass(frozen=True)
class EnvValue:
    value: str | None = None
    value_from_env: str | None = None
    secret: bool = False
    allow_override_process_env: bool = False


@dataclass(frozen=True)
class EnvConflict:
    name: str
    policy: str


@dataclass(frozen=True)
class OptionPackage:
    argv: tuple[str, ...]
    env: dict[str, EnvValue]
    conflicts_with_argv: tuple[str, ...]
    conflicts_with_options: tuple[str, ...]
    conflicts_with_env: tuple[EnvConflict, ...]


@dataclass(frozen=True)
class PatchPackage:
    engine: str
    targets: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PackageManifest:
    schema_version: int
    kind: PackageKind
    id: str
    label: str
    description: str
    package_version: str
    package_dir: Path
    manifest_path: Path | None
    risk: Risk | None
    compatibility: Compatibility | None
    prompt: PromptPackage | None
    option: OptionPackage | None
    patch: PatchPackage | None
    raw: dict[str, Any]
    requires_packages: tuple[str, ...] = ()
    conflicts_with_packages: tuple[str, ...] = ()


@dataclass(frozen=True)
class InvalidPackage:
    package_dir: Path
    errors: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryResult:
    valid: tuple[PackageManifest, ...]
    invalid: tuple[InvalidPackage, ...]


def option_forbidden_prompt_flag(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return value in PROMPT_FLAGS or any(value.startswith(f"{flag}=") for flag in PROMPT_FLAGS)


def _fail(message: str) -> None:
    raise PackageValidationError(message)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label}_must_be_object")
    return value


def _require_string(obj: dict[str, Any], field: str) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or value == "":
        _fail(f"{field}_must_be_non_empty_string")
    return value


def _optional_string(obj: dict[str, Any], field: str) -> str | None:
    value = obj.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        _fail(f"{field}_must_be_string")
    return value


def _require_string_list(obj: dict[str, Any], field: str) -> tuple[str, ...]:
    value = obj.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _fail(f"{field}_must_be_string_list")
    return tuple(value)


def _optional_bool(obj: dict[str, Any], field: str) -> bool:
    value = obj.get(field, False)
    if not isinstance(value, bool):
        _fail(f"{field}_must_be_boolean")
    return value


def _validate_slug(value: str, field: str) -> None:
    if not SLUG_RE.fullmatch(value):
        _fail(f"{field}_invalid_slug")


def validate_package_id(value: str) -> str:
    if not isinstance(value, str) or value == "":
        _fail("id_must_be_non_empty_string")
    _validate_slug(value, "id")
    return value


def _validate_env_name(value: str, field: str) -> None:
    if not ENV_RE.fullmatch(value):
        _fail(f"{field}_invalid_env_name")


def _validate_sha(value: str, field: str) -> None:
    if not SHA256_RE.fullmatch(value):
        _fail(f"{field}_invalid_sha256")


def _inside_package(package_dir: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(package_dir)
        return True
    except ValueError:
        return False


def _package_local_path(package_dir: Path, raw_path: Any, field: str) -> Path:
    if not isinstance(raw_path, str) or raw_path == "":
        _fail(f"{field}_must_be_non_empty_string")
    root = package_dir.resolve()
    candidate = (package_dir / raw_path).resolve(strict=False)
    if not _inside_package(root, candidate):
        _fail("package_path_escape")
    if candidate.exists():
        real_candidate = candidate.resolve()
        if not _inside_package(root, real_candidate):
            _fail("package_path_escape")
        candidate = real_candidate
    return candidate


def _parse_risk(value: Any) -> Risk | None:
    if value is None:
        return None
    risk = _require_mapping(value, "risk")
    level = _require_string(risk, "level")
    if level not in RISK_LEVELS:
        _fail("risk_level_invalid")
    return Risk(
        level=level,
        notes=_optional_string(risk, "notes"),
        requires_confirmation=_optional_bool(risk, "requiresConfirmation"),
        status_warning=_optional_string(risk, "statusWarning"),
    )


def _parse_compatibility(value: Any) -> Compatibility | None:
    if value is None:
        return None
    compatibility = _require_mapping(value, "compatibility")
    return Compatibility(
        claude_versions=_require_string_list(compatibility, "claudeVersions"),
        platforms=_require_string_list(compatibility, "platforms"),
        arches=_require_string_list(compatibility, "arches"),
        notes=_optional_string(compatibility, "notes"),
    )


def _parse_prompt(value: Any, package_dir: Path) -> PromptPackage:
    prompt = _require_mapping(value, "prompt")
    mode = _require_string(prompt, "mode")
    if mode not in PROMPT_MODES:
        _fail("prompt_mode_invalid")
    source = _require_mapping(prompt.get("source"), "prompt_source")
    resolved_path = _package_local_path(package_dir, source.get("path"), "prompt.source.path")
    sha256 = source.get("sha256")
    if sha256 is not None:
        if not isinstance(sha256, str):
            _fail("prompt.source.sha256_must_be_string")
        _validate_sha(sha256, "prompt.source.sha256")
        if not resolved_path.is_file():
            _fail("prompt_source_missing")
        actual = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
        if actual.lower() != sha256.lower():
            _fail("prompt_source_sha256_mismatch")
    return PromptPackage(mode=mode, source=PromptSource(path=resolved_path, sha256=sha256))


def _parse_env_value(name: str, value: Any) -> EnvValue:
    _validate_env_name(name, f"env.{name}")
    if isinstance(value, str):
        return EnvValue(value=value)
    item = _require_mapping(value, f"env.{name}")
    has_value = "value" in item
    has_value_from_env = "valueFromEnv" in item
    if has_value == has_value_from_env:
        _fail("env_value_source_exclusive")
    env_value = None
    value_from_env = None
    if has_value:
        env_value = _require_string(item, "value")
    if has_value_from_env:
        value_from_env = _require_string(item, "valueFromEnv")
        _validate_env_name(value_from_env, "env.valueFromEnv")
    return EnvValue(
        value=env_value,
        value_from_env=value_from_env,
        secret=_optional_bool(item, "secret"),
        allow_override_process_env=_optional_bool(item, "allowOverrideProcessEnv"),
    )


def _parse_env_conflict(value: Any) -> EnvConflict:
    if isinstance(value, str):
        _validate_env_name(value, "conflictsWithEnv")
        return EnvConflict(name=value, policy="override")
    conflict = _require_mapping(value, "conflictsWithEnv")
    name = _require_string(conflict, "name")
    _validate_env_name(name, "conflictsWithEnv.name")
    policy = conflict.get("policy", "override")
    if not isinstance(policy, str):
        _fail("conflictsWithEnv.policy_must_be_string")
    if policy not in ENV_CONFLICT_POLICIES:
        _fail("env_conflict_policy_invalid")
    return EnvConflict(name=name, policy=policy)


def _parse_option(value: Any) -> OptionPackage:
    option = _require_mapping(value, "option")
    argv = _require_string_list(option, "argv")
    for item in argv:
        if option_forbidden_prompt_flag(item):
            _fail("forbidden_prompt_flag")
    env_raw = option.get("env", {})
    if not isinstance(env_raw, dict):
        _fail("env_must_be_object")
    env = {name: _parse_env_value(name, env_value) for name, env_value in env_raw.items()}
    conflicts_env_raw = option.get("conflictsWithEnv", [])
    if not isinstance(conflicts_env_raw, list):
        _fail("conflictsWithEnv_must_be_list")
    return OptionPackage(
        argv=argv,
        env=env,
        conflicts_with_argv=_require_string_list(option, "conflictsWithArgv"),
        conflicts_with_options=_require_string_list(option, "conflictsWithOptions"),
        conflicts_with_env=tuple(_parse_env_conflict(item) for item in conflicts_env_raw),
    )


def _validate_patch_replacement_paths(value: Any, package_dir: Path) -> None:
    if isinstance(value, dict):
        replacement = value.get("replacement")
        if isinstance(replacement, dict) and "path" in replacement:
            _package_local_path(package_dir, replacement.get("path"), "replacement.path")
            if "sha256" not in replacement:
                _fail("replacement.sha256_required")
            sha256 = replacement.get("sha256")
            if not isinstance(sha256, str):
                _fail("replacement.sha256_must_be_string")
            _validate_sha(sha256, "replacement.sha256")
        for item in value.values():
            _validate_patch_replacement_paths(item, package_dir)
    elif isinstance(value, list):
        for item in value:
            _validate_patch_replacement_paths(item, package_dir)


def _parse_patch(value: Any, package_dir: Path) -> PatchPackage:
    patch = _require_mapping(value, "patch")
    engine = _require_string(patch, "engine")
    if engine not in SUPPORTED_PATCH_ENGINES:
        _fail("patch_engine_unsupported")
    targets = patch.get("targets")
    if not isinstance(targets, list) or not all(isinstance(item, dict) for item in targets):
        _fail("patch.targets_must_be_object_list")
    _validate_patch_replacement_paths(targets, package_dir)
    return PatchPackage(engine=engine, targets=tuple(targets))



def _kind(value: Any) -> PackageKind:
    if not isinstance(value, str):
        _fail("kind_must_be_string")
    try:
        return PackageKind(value)
    except ValueError:
        _fail("kind_invalid")


def load_package_manifest_from_dict(
    data: dict[str, Any],
    package_dir: Path,
    expected_kind: PackageKind,
    manifest_path: Path | None = None,
) -> PackageManifest:
    top = _require_mapping(data, "manifest")
    schema_version = top.get("schemaVersion")
    if isinstance(schema_version, bool) or schema_version != 1:
        _fail("schemaVersion_must_be_1")
    unknown = sorted(
        field for field in top if field not in TOP_LEVEL_FIELDS and not field.startswith("x-")
    )
    if unknown:
        _fail(f"unknown_top_level_field:{unknown[0]}")
    package_id = _require_string(top, "id")
    validate_package_id(package_id)
    folder_slug = package_dir.name
    _validate_slug(folder_slug, "folder")
    if package_id != folder_slug:
        _fail("id_must_match_folder")
    kind = _kind(top.get("kind"))
    if kind is not expected_kind:
        _fail("kind_must_match_bucket")

    prompt = option = patch = None
    if kind is PackageKind.PROMPT:
        if "prompt" not in top:
            _fail("prompt_required")
        prompt = _parse_prompt(top.get("prompt"), package_dir)
    elif kind is PackageKind.OPTION:
        if "option" not in top:
            _fail("option_required")
        option = _parse_option(top.get("option"))
    elif kind is PackageKind.PATCH:
        if "patch" not in top:
            _fail("patch_required")
        patch = _parse_patch(top.get("patch"), package_dir)

    return PackageManifest(
        schema_version=schema_version,
        kind=kind,
        id=package_id,
        label=_require_string(top, "label"),
        description=_require_string(top, "description"),
        package_version=(
            _optional_string(top, "packageVersion")
            or _optional_string(top, "x-packageVersion")
            or "0.0.0"
        ),
        package_dir=package_dir,
        manifest_path=manifest_path,
        risk=_parse_risk(top.get("risk")),
        compatibility=_parse_compatibility(top.get("compatibility")),
        prompt=prompt,
        option=option,
        patch=patch,
        raw=data,
        requires_packages=_require_string_list(top, "requiresPackages"),
        conflicts_with_packages=_require_string_list(top, "conflictsWithPackages"),
    )


def load_package_manifest(package_dir: Path, expected_kind: PackageKind) -> PackageManifest:
    package_dir = Path(package_dir)
    json_paths = sorted(path for path in package_dir.glob("*.json") if path.is_file())
    if not json_paths:
        _fail("manifest_json_missing")
    valid: list[PackageManifest] = []
    errors: list[str] = []
    for manifest_path in json_paths:
        try:
            with manifest_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            valid.append(
                load_package_manifest_from_dict(data, package_dir, expected_kind, manifest_path)
            )
        except (OSError, json.JSONDecodeError, PackageValidationError) as exc:
            errors.append(f"{manifest_path.name}: {exc}")
    if len(valid) > 1:
        _fail("multiple_valid_manifests")
    if valid:
        return valid[0]
    _fail("; ".join(errors) if errors else "manifest_invalid")


def discover_packages(root: Path, expected_kind: PackageKind) -> DiscoveryResult:
    root = Path(root)
    valid: list[PackageManifest] = []
    invalid: list[InvalidPackage] = []
    if not root.exists():
        return DiscoveryResult(valid=(), invalid=())
    for package_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            valid.append(load_package_manifest(package_dir, expected_kind))
        except PackageValidationError as exc:
            invalid.append(InvalidPackage(package_dir=package_dir, errors=(str(exc),)))
    return DiscoveryResult(valid=tuple(valid), invalid=tuple(invalid))


def manifest_digest(manifest: PackageManifest) -> str:
    payload = json.dumps(manifest.raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
