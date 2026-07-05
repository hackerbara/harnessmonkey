from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

HEX_DIGITS = set("0123456789abcdefABCDEF")
SUPPORTED_ENGINES = {"bun_graph_repack"}
SUPPORTED_BINARY_FORMATS = {"bun_standalone_macho64", "bun_standalone_pe64"}
SUPPORTED_OPERATION_TYPES = {
    "replace_between",
    "replace_exact",
    "insert_before",
    "insert_after",
    "replace_substring_within",
}
SUPPORTED_ASSERTION_TYPES = {
    "module_must_contain",
    "module_must_not_contain",
    "binary_must_contain",
    "binary_must_not_contain",
}
FORBIDDEN_FIELDS = {"binaryShape", "padding", "allowGrowth", "strategy"}


class ManifestV2Error(ValueError):
    pass


@dataclass(frozen=True)
class SourceIdentityV2:
    claude_version: str
    version_output: str
    sha256: str
    size_bytes: int
    platform: str
    arch: str


@dataclass(frozen=True)
class PayloadRefV2:
    inline: str | None = None
    path: str | None = None
    sha256: str | None = None
    encoding: Literal["utf-8", "base64"] = "utf-8"


@dataclass(frozen=True)
class ModuleOperationV2:
    op_id: str
    label: str
    type: str
    start_marker: str | None
    end_marker: str | None
    exact: str | None
    expected_start_marker_count: int
    expected_end_marker_count: int
    require_within_range: tuple[str, ...]
    old_range_sha256: str | None
    old_range_length: int | None
    replacement: PayloadRefV2
    known_behavior_change: str | None
    anchor: str | None = None
    insert_order: int | None = None
    expected_anchor_count: int = 1
    sub_exact: str | None = None
    expected_sub_exact_count: int = 1
    context_sha256: str | None = None
    seam_hint: str | None = None


@dataclass(frozen=True)
class ModuleTargetV2:
    path: str
    content_sha256: str
    content_length: int
    operations: tuple[ModuleOperationV2, ...]


@dataclass(frozen=True)
class AssertionV2:
    type: str
    module_path: str | None
    value: str


@dataclass(frozen=True)
class ManualSmokeV2:
    required: bool
    reason: str | None


@dataclass(frozen=True)
class TargetV2:
    source_identity: SourceIdentityV2
    required_engine: str
    required_binary_format: str
    modules: tuple[ModuleTargetV2, ...]
    preconditions: tuple[AssertionV2, ...]
    postconditions: tuple[AssertionV2, ...]
    manual_smoke: ManualSmokeV2


@dataclass(frozen=True)
class ManifestV2:
    schema_version: int
    id: str
    name: str
    description: str
    package_version: str
    targets: tuple[TargetV2, ...]
    raw: dict[str, Any]
    requires_packages: tuple[str, ...] = ()
    conflicts_with_packages: tuple[str, ...] = ()


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestV2Error(f"{label} must be an object")
    for field in FORBIDDEN_FIELDS:
        if field in value:
            raise ManifestV2Error(f"unsupported V1.5 field: {field}")
    return value


def require_string(obj: dict[str, Any], field: str) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or value == "":
        raise ManifestV2Error(f"{field} must be a non-empty string")
    return value


def optional_string(obj: dict[str, Any], field: str) -> str | None:
    value = obj.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestV2Error(f"{field} must be a string")
    return value


def require_int(obj: dict[str, Any], field: str) -> int:
    value = obj.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestV2Error(f"{field} must be an integer")
    return value


def optional_non_negative_int(obj: dict[str, Any], field: str) -> int | None:
    value = obj.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestV2Error(f"{field} must be a non-negative integer")
    return value


def optional_string_list(obj: dict[str, Any], field: str) -> tuple[str, ...]:
    value = obj.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ManifestV2Error(f"{field} must be a list of strings")
    return tuple(value)


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ManifestV2Error(f"{field} must be a string")
    if len(value) != 64 or any(ch not in HEX_DIGITS for ch in value):
        raise ManifestV2Error(f"{field} must be 64 hex characters")
    return value


def optional_sha256(obj: dict[str, Any], field: str) -> str | None:
    value = obj.get(field)
    if value is None:
        return None
    return require_sha256(value, field)


def parse_payload(value: Any) -> PayloadRefV2:
    payload = require_mapping(value, "replacement")
    inline = payload.get("inline")
    path = payload.get("path")
    sha256 = payload.get("sha256")
    encoding = payload.get("encoding", "utf-8")
    if encoding not in {"utf-8", "base64"}:
        raise ManifestV2Error("replacement.encoding must be utf-8 or base64")
    if inline is not None and not isinstance(inline, str):
        raise ManifestV2Error("replacement.inline must be a string")
    if path is not None and not isinstance(path, str):
        raise ManifestV2Error("replacement.path must be a string")
    if (inline is None) == (path is None):
        raise ManifestV2Error("replacement must provide exactly one of inline or path")
    if path is not None and sha256 is None:
        raise ManifestV2Error("replacement.path requires replacement.sha256")
    return PayloadRefV2(
        inline=inline,
        path=path,
        sha256=require_sha256(sha256, "replacement.sha256") if sha256 is not None else None,
        encoding=encoding,
    )


def parse_source_identity(value: Any) -> SourceIdentityV2:
    item = require_mapping(value, "sourceIdentity")
    return SourceIdentityV2(
        claude_version=require_string(item, "claudeVersion"),
        version_output=require_string(item, "versionOutput"),
        sha256=require_sha256(item.get("sha256"), "sha256"),
        size_bytes=require_int(item, "sizeBytes"),
        platform=require_string(item, "platform"),
        arch=require_string(item, "arch"),
    )


def parse_operation(value: Any) -> ModuleOperationV2:
    op = require_mapping(value, "operation")
    op_type = require_string(op, "type")
    if op_type not in SUPPORTED_OPERATION_TYPES:
        raise ManifestV2Error(f"unsupported operation type: {op_type}")
    require_within = optional_string_list(op, "requireWithinRange")
    operation = ModuleOperationV2(
        op_id=require_string(op, "opId"),
        label=require_string(op, "label"),
        type=op_type,
        start_marker=optional_string(op, "startMarker"),
        end_marker=optional_string(op, "endMarker"),
        exact=optional_string(op, "exact"),
        expected_start_marker_count=require_int(op, "expectedStartMarkerCount")
        if "expectedStartMarkerCount" in op
        else 1,
        expected_end_marker_count=require_int(op, "expectedEndMarkerCount")
        if "expectedEndMarkerCount" in op
        else 1,
        require_within_range=require_within,
        old_range_sha256=optional_sha256(op, "oldRangeSha256"),
        old_range_length=optional_non_negative_int(op, "oldRangeLength"),
        replacement=parse_payload(op.get("replacement")),
        known_behavior_change=optional_string(op, "knownBehaviorChange"),
        anchor=optional_string(op, "anchor"),
        insert_order=optional_non_negative_int(op, "insertOrder"),
        expected_anchor_count=require_int(op, "expectedAnchorCount")
        if "expectedAnchorCount" in op
        else 1,
        sub_exact=optional_string(op, "subExact"),
        expected_sub_exact_count=require_int(op, "expectedSubExactCount")
        if "expectedSubExactCount" in op
        else 1,
        context_sha256=optional_sha256(op, "contextSha256"),
        seam_hint=optional_string(op, "seamHint"),
    )
    _validate_operation_shape(operation)
    return operation


def _require_supported_marker_counts(operation: ModuleOperationV2) -> None:
    if operation.expected_start_marker_count != 1:
        raise ManifestV2Error(
            f"{operation.op_id}: expectedStartMarkerCount must be 1 (other values unsupported)"
        )
    if operation.expected_end_marker_count != 1:
        raise ManifestV2Error(
            f"{operation.op_id}: expectedEndMarkerCount must be 1 (other values unsupported)"
        )


def _validate_operation_shape(operation: ModuleOperationV2) -> None:
    if operation.type in {"insert_before", "insert_after"}:
        if operation.anchor is None:
            raise ManifestV2Error(f"{operation.op_id}: {operation.type} requires anchor")
        if operation.expected_anchor_count != 1:
            raise ManifestV2Error(
                f"{operation.op_id}: expectedAnchorCount must be 1 (other values unsupported)"
            )
        if (operation.start_marker is None) != (operation.end_marker is None):
            raise ManifestV2Error(
                f"{operation.op_id}: context markers must be provided together"
            )
        if operation.context_sha256 is not None and operation.start_marker is None:
            raise ManifestV2Error(
                f"{operation.op_id}: contextSha256 requires context markers"
            )
        if operation.start_marker is not None:
            _require_supported_marker_counts(operation)
        if operation.exact is not None or operation.sub_exact is not None:
            raise ManifestV2Error(
                f"{operation.op_id}: exact/subExact not allowed on insertions"
            )
        if (
            operation.require_within_range
            or operation.old_range_sha256 is not None
            or operation.old_range_length is not None
        ):
            raise ManifestV2Error(
                f"{operation.op_id}: old-range evidence not allowed on insertions"
            )
    elif operation.type == "replace_substring_within":
        if operation.start_marker is None or operation.end_marker is None:
            raise ManifestV2Error(
                f"{operation.op_id}: replace_substring_within requires startMarker and endMarker"
            )
        if operation.sub_exact is None:
            raise ManifestV2Error(
                f"{operation.op_id}: replace_substring_within requires subExact"
            )
        _require_supported_marker_counts(operation)
        if operation.expected_sub_exact_count != 1:
            raise ManifestV2Error(
                f"{operation.op_id}: expectedSubExactCount must be 1 (other values unsupported)"
            )
        if (
            operation.anchor is not None
            or operation.insert_order is not None
            or operation.exact is not None
        ):
            raise ManifestV2Error(
                f"{operation.op_id}: anchor/insertOrder/exact not allowed on "
                "replace_substring_within"
            )
    else:
        if operation.expected_anchor_count != 1:
            raise ManifestV2Error(
                f"{operation.op_id}: expectedAnchorCount must be 1 (other values unsupported)"
            )
        if operation.expected_sub_exact_count != 1:
            raise ManifestV2Error(
                f"{operation.op_id}: expectedSubExactCount must be 1 (other values unsupported)"
            )
        if (
            operation.anchor is not None
            or operation.insert_order is not None
            or operation.sub_exact is not None
            or operation.context_sha256 is not None
            or operation.seam_hint is not None
        ):
            raise ManifestV2Error(
                f"{operation.op_id}: structured-splice fields not allowed on {operation.type}"
            )


def parse_module(value: Any) -> ModuleTargetV2:
    module = require_mapping(value, "module")
    operations = module.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ManifestV2Error("operations must be a non-empty list")
    return ModuleTargetV2(
        path=require_string(module, "path"),
        content_sha256=require_sha256(module.get("contentSha256"), "contentSha256"),
        content_length=require_int(module, "contentLength"),
        operations=tuple(parse_operation(item) for item in operations),
    )


def parse_assertion(value: Any) -> AssertionV2:
    assertion = require_mapping(value, "assertion")
    assertion_type = require_string(assertion, "type")
    if assertion_type not in SUPPORTED_ASSERTION_TYPES:
        raise ManifestV2Error(f"unsupported assertion type: {assertion_type}")
    module_path = optional_string(assertion, "modulePath")
    if assertion_type.startswith("module_") and module_path is None:
        raise ManifestV2Error("module assertion requires modulePath")
    if assertion_type.startswith("binary_") and module_path is not None:
        raise ManifestV2Error("binary assertion must not include modulePath")
    return AssertionV2(
        type=assertion_type,
        module_path=module_path,
        value=require_string(assertion, "value"),
    )


def parse_manual_smoke(value: Any) -> ManualSmokeV2:
    if value is None:
        return ManualSmokeV2(required=False, reason=None)
    smoke = require_mapping(value, "manualSmoke")
    required = smoke.get("required", False)
    if not isinstance(required, bool):
        raise ManifestV2Error("manualSmoke.required must be a boolean")
    reason = optional_string(smoke, "reason")
    if required and not reason:
        raise ManifestV2Error("manualSmoke.reason is required when manual smoke is required")
    return ManualSmokeV2(required=required, reason=reason)


def _optional_assertions(target: dict[str, Any], field: str) -> tuple[AssertionV2, ...]:
    raw = target.get(field, [])
    if not isinstance(raw, list):
        raise ManifestV2Error(f"{field} must be a list")
    return tuple(parse_assertion(item) for item in raw)


def parse_target(value: Any) -> TargetV2:
    target = require_mapping(value, "target")
    engine = require_string(target, "requiredEngine")
    if engine not in SUPPORTED_ENGINES:
        raise ManifestV2Error(f"unsupported requiredEngine: {engine}")
    binary_format = require_string(target, "requiredBinaryFormat")
    if binary_format not in SUPPORTED_BINARY_FORMATS:
        raise ManifestV2Error(f"unsupported requiredBinaryFormat: {binary_format}")
    modules_raw = target.get("modules")
    if not isinstance(modules_raw, list) or not modules_raw:
        raise ManifestV2Error("modules must be a non-empty list")
    return TargetV2(
        source_identity=parse_source_identity(target.get("sourceIdentity")),
        required_engine=engine,
        required_binary_format=binary_format,
        modules=tuple(parse_module(item) for item in modules_raw),
        preconditions=_optional_assertions(target, "preconditions"),
        postconditions=_optional_assertions(target, "postconditions"),
        manual_smoke=parse_manual_smoke(target.get("manualSmoke")),
    )


def load_manifest_v2_dict(data: dict[str, Any]) -> ManifestV2:
    top = require_mapping(data, "manifest")
    schema = top.get("schemaVersion")
    if schema == 1:
        raise ManifestV2Error("schema_v1_migration_required")
    if schema != 2:
        raise ManifestV2Error("schemaVersion must be 2")
    targets = top.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ManifestV2Error("targets must be a non-empty list")
    parsed_targets = tuple(parse_target(item) for item in targets)
    seen_ops: set[str] = set()
    for target in parsed_targets:
        seen_modules: set[str] = set()
        for module in target.modules:
            if module.path in seen_modules:
                raise ManifestV2Error(f"duplicate module path: {module.path}")
            seen_modules.add(module.path)
            for operation in module.operations:
                if operation.op_id in seen_ops:
                    raise ManifestV2Error(f"duplicate opId: {operation.op_id}")
                seen_ops.add(operation.op_id)
    return ManifestV2(
        schema_version=2,
        id=require_string(top, "id"),
        name=require_string(top, "name"),
        description=require_string(top, "description"),
        package_version=require_string(top, "packageVersion"),
        targets=parsed_targets,
        raw=data,
        requires_packages=optional_string_list(top, "requiresPackages"),
        conflicts_with_packages=optional_string_list(top, "conflictsWithPackages"),
    )
