from __future__ import annotations

import base64
import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from harnessmonkey.binary_format import (
    detect_binary_format,
    locate_bun_section,
    repack_for_format,
)
from harnessmonkey.binary_inspect import inspect_binary_bytes
from harnessmonkey.bun_graph import BunGraphError, parse_bun_section
from harnessmonkey.install import use_official
from harnessmonkey.macho import MachOError
from harnessmonkey.manifest_v2 import (
    AssertionV2,
    ManifestV2,
    ManifestV2Error,
    PayloadRefV2,
    TargetV2,
    load_manifest_v2_dict,
)
from harnessmonkey.module_patch import (
    ModulePatchError,
    PlannedModuleOperation,
    check_planned_conflicts,
    plan_module_operations,
    planned_operation_render_order,
    render_changed_module,
    shared_insertion_points,
    verify_insertions,
)
from harnessmonkey.package_model import PackageKind, PackageValidationError, load_package_manifest
from harnessmonkey.progress import StageTracker
from harnessmonkey.reports_v2 import BuildReportV2
from harnessmonkey.smoke import (
    CommandResult,
    codesign_sign,
    codesign_verify,
    run_command,
    smoke_claude_code_version_and_help,
)

CommandRunner = Callable[[list[str]], CommandResult]

BUILD_STAGES: tuple[tuple[str, str], ...] = (
    ("resolve", "Resolve patches"),
    ("repack", "Repack binary"),
    ("sign", "Sign"),
    ("inspect", "Inspect signed binary"),
    ("smoke", "Smoke test"),
    ("activate", "Activate"),
)


@dataclass(frozen=True)
class ValidationRequestV15:
    source_path: Path
    package_dir: Path
    source_version: str
    source_version_output: str
    platform: str
    arch: str


@dataclass(frozen=True)
class BuildRequestV15:
    source_path: Path
    output_dir: Path
    package_dirs: list[Path]
    source_version: str
    source_version_output: str
    platform: str
    arch: str
    run_signing: bool = True
    run_smoke: bool = True
    activate: bool = False
    current_path: Path | None = None
    command_runner: CommandRunner = run_command
    manifest_digests: dict[str, str] | None = None
    build_input_snapshot: dict[str, Any] | None = None
    on_event: Callable[[dict], None] | None = None


def _v3_manifest_as_v2_dict(package_dir: Path) -> dict[str, Any]:
    manifest = load_package_manifest(package_dir, PackageKind.PATCH)
    if manifest.patch is None:
        raise ManifestV2Error("patch_required")
    return {
        "schemaVersion": 2,
        "id": manifest.id,
        "name": manifest.label,
        "description": manifest.description,
        "packageVersion": manifest.package_version,
        "targets": list(manifest.patch.targets),
        "requiresPackages": list(manifest.requires_packages),
        "conflictsWithPackages": list(manifest.conflicts_with_packages),
    }


def load_manifest_v2(package_dir: Path) -> ManifestV2:
    patch_json = package_dir / "patch.json"
    if patch_json.exists():
        try:
            data = json.loads(patch_json.read_text())
        except json.JSONDecodeError as exc:
            raise ManifestV2Error(f"patch.json malformed_json: {exc.msg}") from exc
        except OSError as exc:
            raise ManifestV2Error(f"patch.json read_error: {type(exc).__name__}: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestV2Error("patch.json must be an object")
        if data.get("schemaVersion") != 1 or "kind" not in data:
            raise ManifestV2Error("unsupported_manifest_format: expected schemaVersion 1 with kind")
    return load_manifest_v2_dict(_v3_manifest_as_v2_dict(package_dir))


def load_payload(ref: PayloadRefV2, package_dir: Path) -> bytes:
    if ref.inline is not None:
        data = (
            ref.inline.encode("utf-8") if ref.encoding == "utf-8" else base64.b64decode(ref.inline)
        )
    else:
        assert ref.path is not None
        data = (package_dir / ref.path).read_bytes()
    if ref.sha256 is not None and hashlib.sha256(data).hexdigest() != ref.sha256:
        raise ValueError("replacement sha256 mismatch")
    return data


def target_matches(
    target: TargetV2, request: ValidationRequestV15 | BuildRequestV15, source: bytes
) -> bool:
    ident = target.source_identity
    return (
        ident.claude_version == request.source_version
        and ident.version_output == request.source_version_output
        and ident.sha256 == hashlib.sha256(source).hexdigest()
        and ident.size_bytes == len(source)
        and ident.platform == request.platform
        and ident.arch == request.arch
    )


def _validation_failure(package_id: str | None, error_code: str, message: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "ok": False,
        "packageId": package_id,
        "errorCode": error_code,
        "errors": [message],
    }


def validate_package(request: ValidationRequestV15) -> dict[str, Any]:
    try:
        source = request.source_path.read_bytes()
        manifest = load_manifest_v2(request.package_dir)
        matching_targets = [
            target for target in manifest.targets if target_matches(target, request, source)
        ]
        if len(matching_targets) != 1:
            return {
                "schemaVersion": 1,
                "ok": False,
                "packageId": manifest.id,
                "errorCode": "source_identity_mismatch",
                "errors": ["source identity did not match exactly"],
            }
        target = matching_targets[0]
        start, length = locate_bun_section(source)
        graph = parse_bun_section(source[start : start + length])
        if graph.validation_errors:
            return {
                "schemaVersion": 1,
                "ok": False,
                "packageId": manifest.id,
                "errorCode": "bun_graph_invalid",
                "errors": graph.validation_errors,
            }
        resolved: list[PlannedModuleOperation] = []
        changed_modules: dict[str, bytes] = {}
        for module_target in target.modules:
            module = graph.module_by_path(module_target.path)
            if (
                hashlib.sha256(module.content).hexdigest() != module_target.content_sha256
                or module.content_size != module_target.content_length
            ):
                return {
                    "schemaVersion": 1,
                    "ok": False,
                    "packageId": manifest.id,
                    "errorCode": "module_identity_failed",
                    "errors": [module_target.path],
                }
            operation_inputs = [
                (operation, load_payload(operation.replacement, request.package_dir))
                for operation in module_target.operations
            ]
            planned = plan_module_operations(
                manifest.id, module_target.path, module.content, operation_inputs
            )
            resolved.extend(planned)
            changed_modules[module_target.path] = render_changed_module(module.content, planned)
        return {
            "schemaVersion": 1,
            "ok": True,
            "packageId": manifest.id,
            "sourceMatched": True,
            "modulesMatched": True,
            "operationsResolved": [
                {
                    "modulePath": item.module_path,
                    "opId": item.op_id,
                    "moduleStart": item.module_start,
                    "moduleEnd": item.module_end,
                    "oldLen": item.old_len,
                    "newLen": item.new_len,
                    "delta": item.delta,
                }
                for item in resolved
            ],
            "manualSmokeRequired": target.manual_smoke.required,
            "errors": [],
        }
    except ManifestV2Error as exc:
        return _validation_failure(None, str(exc), str(exc))
    except MachOError as exc:
        return _validation_failure(None, str(exc), str(exc))
    except BunGraphError as exc:
        return _validation_failure(None, str(exc), str(exc))
    except ModulePatchError as exc:
        return _validation_failure(None, "operation_resolution_failed", str(exc))
    except PackageValidationError as exc:
        return _validation_failure(None, "package_manifest_invalid", str(exc))
    except OSError as exc:
        return _validation_failure(None, "filesystem_error", f"{type(exc).__name__}: {exc}")
    except ValueError as exc:
        return _validation_failure(None, "validation_failed", str(exc))


def _command_result_dict(result: CommandResult) -> dict[str, Any]:
    return asdict(result)


def _exception_result(argv: list[str], exc: Exception) -> CommandResult:
    return CommandResult(
        argv=argv,
        returncode=127,
        stdout="",
        stderr=f"{type(exc).__name__}: {exc}",
    )


def _safe_runner(runner: CommandRunner) -> CommandRunner:
    def wrapped(argv: list[str]) -> CommandResult:
        try:
            return runner(argv)
        except Exception as exc:
            return _exception_result(argv, exc)

    return wrapped


def _base_report(request: BuildRequestV15, source: bytes | None = None) -> BuildReportV2:
    source_bytes = source if source is not None else b""
    source_sha = hashlib.sha256(source_bytes).hexdigest() if source is not None else ""
    source_size = len(source_bytes) if source is not None else 0
    source_identity = {
        "claudeVersion": request.source_version,
        "versionOutput": request.source_version_output,
        "sha256": source_sha,
        "sizeBytes": source_size,
        "platform": request.platform,
        "arch": request.arch,
    }
    return BuildReportV2(
        sourceClaudePath=str(request.source_path),
        sourceVersion=request.source_version,
        sourceVersionOutput=request.source_version_output,
        sourceSha256=source_sha,
        sourceSizeBytes=source_size,
        packageManifestDigests=dict(request.manifest_digests or {}),
        sourceIdentity=source_identity,
        buildInputSnapshot=dict(request.build_input_snapshot or {}),
        compatibility={"status": "compatible", "warnings": []},
    )


def _write_failed(
    request: BuildRequestV15,
    report_path: Path,
    reason: str,
    *,
    source: bytes | None = None,
    enabled: list[str] | None = None,
    compatibility_status: str | None = None,
) -> BuildReportV2:
    report = _base_report(request, source)
    report.status = "failed"
    report.automatedStatus = "failed"
    report.enabledPatches = enabled or []
    report.failureReason = reason
    if reason.startswith("source_identity_mismatch:"):
        report.compatibility = {
            "status": compatibility_status or "source_sha_mismatch",
            "warnings": [],
        }
    elif reason.startswith("package_manifest_invalid:"):
        report.compatibility = {"status": "package_manifest_invalid", "warnings": []}
    report.activationEligible = False
    report.activationStatus = "blocked" if request.activate else "skipped"
    _write_report(report, report_path)
    return report


def _write_report(report: BuildReportV2, report_path: Path) -> None:
    try:
        report.write(report_path)
    except OSError as exc:
        write_error = f"report_write_failed:{type(exc).__name__}: {exc}"
        report.status = "failed"
        report.automatedStatus = "failed"
        report.activationEligible = False
        if report.failureReason:
            report.failureReason = f"{report.failureReason}; {write_error}"
        else:
            report.failureReason = write_error


def _assert_condition_v2(
    assertion: AssertionV2,
    *,
    modules: dict[str, bytes],
    binary: bytes | None,
) -> dict[str, Any]:
    if assertion.type.startswith("module_"):
        if assertion.module_path is None:
            raise ValueError("module_assertion_requires_modulePath")
        haystack = modules.get(assertion.module_path)
        if haystack is None:
            raise ValueError(f"module_assertion_missing_module:{assertion.module_path}")
    elif assertion.type.startswith("binary_"):
        if binary is None:
            raise ValueError("binary_assertion_requires_binary")
        haystack = binary
    else:
        raise ValueError(f"unsupported_assertion_type:{assertion.type}")
    needle = assertion.value.encode("utf-8")
    found = needle in haystack
    passed = found if assertion.type.endswith("_must_contain") else not found
    return {
        "type": assertion.type,
        "modulePath": assertion.module_path,
        "value": assertion.value,
        "passed": passed,
    }


def _short_sha(value: str) -> str:
    return f"{value[:12]}…"


def _source_identity_mismatch_reason(
    manifest: ManifestV2, request: BuildRequestV15, source: bytes
) -> str:
    source_sha = hashlib.sha256(source).hexdigest()
    current = (
        f"current source is Claude {request.source_version} "
        f"({request.source_version_output}), {request.platform}/{request.arch}, "
        f"sha256 {_short_sha(source_sha)}, size {len(source)} bytes"
    )
    targets = [
        (
            f"Claude {target.source_identity.claude_version} "
            f"({target.source_identity.version_output}), "
            f"{target.source_identity.platform}/{target.source_identity.arch}, "
            f"sha256 {_short_sha(target.source_identity.sha256)}, "
            f"size {target.source_identity.size_bytes} bytes"
        )
        for target in manifest.targets
    ]
    target_summary = "; ".join(targets) if targets else "none"
    return f"source_identity_mismatch:{manifest.id}: {current}; package targets {target_summary}"


BUILD_IDENTITY_MISMATCH_PRIORITY = {
    "source_sha_mismatch": 0,
    "source_size_mismatch": 1,
    "platform_mismatch": 2,
    "arch_mismatch": 3,
    "version_mismatch": 4,
    "unknown": 5,
}


def _build_identity_mismatch_status(
    manifest: ManifestV2, request: BuildRequestV15, source: bytes
) -> str:
    statuses = [
        _target_identity_mismatch_status(target, request, source) for target in manifest.targets
    ]
    if not statuses:
        return "unknown"
    return min(
        statuses,
        key=lambda status: BUILD_IDENTITY_MISMATCH_PRIORITY.get(status, 99),
    )


def _target_identity_mismatch_status(
    target: TargetV2, request: BuildRequestV15, source: bytes
) -> str:
    identity = target.source_identity
    if identity.claude_version != request.source_version:
        return "version_mismatch"
    if identity.version_output != request.source_version_output:
        return "version_mismatch"
    if identity.platform != request.platform:
        return "platform_mismatch"
    if identity.arch != request.arch:
        return "arch_mismatch"
    if identity.sha256 != hashlib.sha256(source).hexdigest():
        return "source_sha_mismatch"
    if identity.size_bytes != len(source):
        return "source_size_mismatch"
    return "unknown"


def _apply_signing_v15(
    report: BuildReportV2,
    output: Path,
    runner: CommandRunner,
    *,
    source_bytes: bytes | None = None,
) -> bool:
    fmt = detect_binary_format(source_bytes) if source_bytes is not None else "macho"
    if fmt == "pe":
        report.signingResult = {"status": "skipped", "reason": "pe_no_signing"}
        return True
    safe_runner = _safe_runner(runner)
    sign = codesign_sign(output, safe_runner)
    verify = codesign_verify(output, safe_runner)
    passed = sign.returncode == 0 and verify.returncode == 0
    report.signingResult = {
        "status": "passed" if passed else "failed",
        "sign": _command_result_dict(sign),
        "verify": _command_result_dict(verify),
    }
    if not passed:
        report.status = "failed"
        report.automatedStatus = "failed"
        report.failureReason = "signing_failed"
    return passed


def _select_packages(
    request: BuildRequestV15, source: bytes, report_path: Path
) -> tuple[list[tuple[Path, ManifestV2, TargetV2]], BuildReportV2 | None]:
    selected: list[tuple[Path, ManifestV2, TargetV2]] = []
    enabled: list[str] = []
    seen_ids: set[str] = set()
    for package_dir in request.package_dirs:
        try:
            manifest = load_manifest_v2(package_dir)
        except PackageValidationError as exc:
            return selected, _write_failed(
                request,
                report_path,
                f"package_manifest_invalid:{package_dir.name}: {exc}",
                source=source,
                enabled=[*enabled, package_dir.name],
            )
        except ManifestV2Error as exc:
            reason = str(exc)
            if reason != "schema_v1_migration_required":
                reason = f"manifest_v2_invalid:{reason}"
            return selected, _write_failed(
                request, report_path, reason, source=source, enabled=enabled
            )
        if manifest.id in seen_ids:
            return selected, _write_failed(
                request,
                report_path,
                f"duplicate_package_id:{manifest.id}:{package_dir.name}",
                source=source,
                enabled=enabled,
            )
        seen_ids.add(manifest.id)
        enabled.append(manifest.id)
        matching = [
            target for target in manifest.targets if target_matches(target, request, source)
        ]
        if len(matching) != 1:
            return selected, _write_failed(
                request,
                report_path,
                _source_identity_mismatch_reason(manifest, request, source),
                source=source,
                enabled=enabled,
                compatibility_status=_build_identity_mismatch_status(manifest, request, source),
            )
        selected.append((package_dir, manifest, matching[0]))
    return selected, None


def build_patchset_v15(request: BuildRequestV15) -> BuildReportV2:
    tracker = StageTracker(request.on_event)
    tracker.plan(BUILD_STAGES)
    tracker.start("resolve")
    request.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = request.output_dir / "build-report.json"
    source = request.source_path.read_bytes()
    selected, failure = _select_packages(request, source, report_path)
    if failure is not None:
        tracker.fail(failure.failureReason)
        return failure

    report = _base_report(request, source)
    report.enabledPatches = [manifest.id for _, manifest, _ in selected]
    try:
        enabled_ids = {manifest.id for _, manifest, _ in selected}
        for _, manifest, _ in selected:
            for required in sorted(manifest.requires_packages):
                if required not in enabled_ids:
                    raise ValueError(
                        f"patch_conflict:required_package_missing:{manifest.id}:{required}"
                    )
            for conflict in sorted(manifest.conflicts_with_packages):
                if conflict in enabled_ids:
                    raise ValueError(
                        f"patch_conflict:package_conflict:{manifest.id}:{conflict}"
                    )
        start, length = locate_bun_section(source)
        graph = parse_bun_section(source[start : start + length])
        if graph.validation_errors:
            raise ValueError(f"bun_graph_invalid:{graph.validation_errors}")
        original_modules = {module.path: module.content for module in graph.modules}
        planned_by_module: dict[str, list[PlannedModuleOperation]] = {}
        verification_results: list[dict[str, Any]] = []
        manual_required = False
        manual_reasons: list[str] = []
        for package_dir, manifest, target in selected:
            manual_required = manual_required or target.manual_smoke.required
            if target.manual_smoke.reason:
                manual_reasons.append(target.manual_smoke.reason)
            for assertion in target.preconditions:
                result = _assert_condition_v2(assertion, modules=original_modules, binary=source)
                verification_results.append({"packageId": manifest.id, **result})
                if not result["passed"]:
                    raise ValueError(f"precondition_failed:{manifest.id}")
            for module_target in target.modules:
                module = graph.module_by_path(module_target.path)
                module_sha = hashlib.sha256(module.content).hexdigest()
                if (
                    module_sha != module_target.content_sha256
                    or module.content_size != module_target.content_length
                ):
                    raise ValueError(f"module_identity_failed:{module_target.path}")
                operation_inputs = [
                    (operation, load_payload(operation.replacement, package_dir))
                    for operation in module_target.operations
                ]
                planned = plan_module_operations(
                    manifest.id, module_target.path, module.content, operation_inputs
                )
                planned_by_module.setdefault(module_target.path, []).extend(planned)
        shared_anchors_by_module: dict[str, set[str]] = {}
        for module_path, planned in planned_by_module.items():
            check_planned_conflicts(planned)
            for items in shared_insertion_points(planned).values():
                if len(items) > 1:
                    shared_anchors_by_module.setdefault(module_path, set()).update(
                        item.anchor for item in items if item.anchor
                    )
        if shared_anchors_by_module:
            all_shared_anchors = {
                anchor for anchors in shared_anchors_by_module.values() for anchor in anchors
            }
            for _, manifest, target in selected:
                for assertion in target.postconditions:
                    if assertion.module_path is None:
                        anchors = all_shared_anchors
                    else:
                        anchors = shared_anchors_by_module.get(assertion.module_path, set())
                    if any(anchor in assertion.value for anchor in anchors):
                        raise ValueError(
                            "postcondition_composition_sensitive:"
                            f"{manifest.id}:{assertion.value[:60]}"
                        )
        changed_modules: dict[str, bytes] = {}
        insertion_evidence: dict[tuple[str, str], dict[str, Any]] = {}
        for module_path, planned in planned_by_module.items():
            changed_modules[module_path] = render_changed_module(
                original_modules[module_path], planned
            )
            for evidence in verify_insertions(changed_modules[module_path], planned):
                if not evidence["insertionVerified"]:
                    raise ValueError(
                        f"insertion_evidence_failed:{evidence['packageId']}:{evidence['opId']}"
                    )
                insertion_evidence[(evidence["packageId"], evidence["opId"])] = evidence
        if not changed_modules:
            raise ValueError("no_module_changes")
        tracker.done()
        tracker.start("repack")
        repack = repack_for_format(source, changed_modules)
        for _, manifest, target in selected:
            for assertion in target.postconditions:
                result = _assert_condition_v2(
                    assertion,
                    modules={**original_modules, **changed_modules},
                    binary=repack.output_bytes,
                )
                verification_results.append({"packageId": manifest.id, **result})
                if not result["passed"]:
                    raise ValueError(f"postcondition_failed:{manifest.id}")
        output_name = "claude.exe" if detect_binary_format(source) == "pe" else "claude"
        output = request.output_dir / output_name
        output.write_bytes(repack.output_bytes)
        shutil.copymode(request.source_path, output)
        report.outputPath = str(output)
        report.operationsApplied = [
            {
                "packageId": item.package_id,
                "opId": item.op_id,
                "label": item.label,
                "modulePath": item.module_path,
                "moduleStart": item.module_start,
                "moduleEnd": item.module_end,
                "oldLen": item.old_len,
                "newLen": item.new_len,
                "delta": item.delta,
                "oldSha256": item.old_sha256,
                "type": item.op_type,
                "kind": item.kind,
                "insertOrder": item.insert_order,
                "anchor": item.anchor,
                "seamHint": item.seam_hint,
                "contextStart": item.context_start,
                "contextEnd": item.context_end,
                **insertion_evidence.get((item.package_id, item.op_id), {}),
            }
            for item in sorted(
                (item for planned in planned_by_module.values() for item in planned),
                key=planned_operation_render_order,
            )
        ]
        report.changedModules = [
            {
                "modulePath": path,
                "oldSize": len(original_modules[path]),
                "newSize": len(new_bytes),
                "delta": len(new_bytes) - len(original_modules[path]),
                "oldSha256": hashlib.sha256(original_modules[path]).hexdigest(),
                "newSha256": hashlib.sha256(new_bytes).hexdigest(),
            }
            for path, new_bytes in changed_modules.items()
        ]
        report.bunGraphUpdates = repack.bun_graph_updates
        report.machoUpdates = repack.macho_updates
        report.machoUpdateDetails = repack.macho_update_details
        report.verificationResults = verification_results
        tracker.done()
        blockers: list[str] = []
        if request.run_signing:
            tracker.start("sign")
            if not _apply_signing_v15(
                report, output, request.command_runner, source_bytes=source
            ):
                tracker.fail("signing failed")
                _write_report(report, report_path)
                return report
            tracker.done()
        else:
            report.signingResult = {"status": "skipped"}
            report.skippedGates.append("signing")
            blockers.append("signing_skipped")
            tracker.skip("sign", "signing skipped")
        tracker.start("inspect")
        output_bytes = output.read_bytes()
        report.outputSha256 = hashlib.sha256(output_bytes).hexdigest()
        report.outputSizeBytes = len(output_bytes)
        post_sign = inspect_binary_bytes(output_bytes, source_path=str(output))
        report.postSignInspection = {
            "bunGraphValid": bool(post_sign["ok"]),
            "validationErrors": post_sign["validationErrors"],
        }
        if not post_sign["ok"] or post_sign["validationErrors"]:
            report.status = "failed"
            report.automatedStatus = "failed"
            report.failureReason = "post_sign_inspection_failed"
            tracker.fail("post-sign inspection failed")
            _write_report(report, report_path)
            return report
        tracker.done()
        if request.run_smoke:
            tracker.start("smoke")
            smoke_result = smoke_claude_code_version_and_help(
                output, request.source_version_output, _safe_runner(request.command_runner)
            )
            report.smokeTestResults = [smoke_result]
            if not smoke_result["passed"]:
                report.status = "failed"
                report.automatedStatus = "failed"
                report.failureReason = "smoke_failed"
                tracker.fail("smoke test failed")
                _write_report(report, report_path)
                return report
            tracker.done()
        else:
            report.skippedGates.append("smoke")
            blockers.append("smoke_skipped")
            tracker.skip("smoke", "smoke skipped")
        if manual_required:
            # manual-smoke gate disabled for now: no GUI affordance exists to perform
            # manual smoke/activation, so requiring it made a successful build a dead
            # end (build finishes but never activates, with no way to unblock it from
            # the GUI). Per product decision, a successful build (automated validation
            # passing) now activates directly instead of stalling here. Re-enable by
            # restoring `blockers.append("manual_smoke_pending")` below once a rollout
            # UX for manual smoke lands.
            # blockers.append("manual_smoke_pending")
            report.manualSmoke = {
                "required": True,
                "status": "bypassed",
                "reason": "; ".join(manual_reasons) if manual_reasons else None,
            }
        else:
            report.manualSmoke = {"required": False, "status": "not_required", "reason": None}
        report.automatedStatus = "passed" if not report.skippedGates else "skipped"
        report.activationBlockers = blockers
        report.activationEligible = not blockers and report.automatedStatus == "passed"
        if report.activationEligible:
            report.status = "verified"
        elif "manual_smoke_pending" in blockers and report.automatedStatus == "passed":
            report.status = "manual_smoke_pending"
        else:
            report.status = "skipped_gates"
        if request.activate:
            tracker.start("activate")
            if report.activationEligible and request.current_path is not None:
                use_official(request.current_path, output)
                report.activationStatus = "activated"
                tracker.done()
            else:
                if request.current_path is None and report.activationEligible:
                    report.activationBlockers.append("activation_requires_current_path")
                    report.activationEligible = False
                report.activationStatus = "blocked"
                tracker.fail("activation blocked: " + ", ".join(report.activationBlockers))
        else:
            report.activationStatus = "skipped"
            tracker.skip("activate", "activation not requested")
        _write_report(report, report_path)
        return report
    except Exception as exc:
        tracker.fail(str(exc))
        report.status = "failed"
        report.automatedStatus = "failed"
        report.failureReason = str(exc)
        report.activationEligible = False
        _write_report(report, report_path)
        return report
