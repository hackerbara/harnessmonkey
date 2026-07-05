from __future__ import annotations

import hashlib
from dataclasses import dataclass

from harnessmonkey.manifest_v2 import ModuleOperationV2


class ModulePatchError(ValueError):
    pass


@dataclass(frozen=True)
class PlannedModuleOperation:
    package_id: str
    op_id: str
    label: str
    module_path: str
    module_start: int
    module_end: int
    old_len: int
    new_len: int
    delta: int
    old_sha256: str
    replacement: bytes
    op_type: str = "replace_exact"
    insert_order: int | None = None
    context_start: int | None = None
    context_end: int | None = None
    evidence_spans: tuple[tuple[int, int], ...] = ()
    anchor: str | None = None
    seam_hint: str | None = None

    @property
    def kind(self) -> str:
        return kind_for_operation_type(self.op_type)


def kind_for_operation_type(op_type: str) -> str:
    if op_type in {"replace_between", "replace_exact"}:
        return "replacement"
    if op_type in {"insert_before", "insert_after"}:
        return "insertion"
    if op_type == "replace_substring_within":
        return "subspan_replacement"
    return "unknown"


def _b(value: str) -> bytes:
    return value.encode("utf-8")


def _count(source: bytes, needle: bytes) -> int:
    if needle == b"":
        return 0
    count = 0
    pos = 0
    while True:
        found = source.find(needle, pos)
        if found < 0:
            return count
        count += 1
        pos = found + 1


@dataclass(frozen=True)
class _Resolved:
    start: int
    end: int
    context_start: int | None = None
    context_end: int | None = None
    evidence_spans: tuple[tuple[int, int], ...] = ()


def _resolve_context(
    module: bytes, operation: ModuleOperationV2
) -> tuple[int, int, tuple[tuple[int, int], ...]]:
    """Resolve a context span: start of startMarker through END of endMarker."""
    if operation.start_marker is None or operation.end_marker is None:
        raise ModulePatchError(f"{operation.op_id}: context requires startMarker and endMarker")
    start_marker = _b(operation.start_marker)
    end_marker = _b(operation.end_marker)
    start_count = _count(module, start_marker)
    if start_count != operation.expected_start_marker_count:
        raise ModulePatchError(
            f"{operation.op_id}: start marker count {start_count} "
            f"!= {operation.expected_start_marker_count}"
        )
    start = module.find(start_marker)
    tail = module[start + len(start_marker) :]
    end_count = _count(tail, end_marker)
    if end_count != operation.expected_end_marker_count:
        raise ModulePatchError(
            f"{operation.op_id}: end marker count {end_count} "
            f"!= {operation.expected_end_marker_count}"
        )
    end_marker_start = module.find(end_marker, start + len(start_marker))
    end = end_marker_start + len(end_marker)
    spans = ((start, start + len(start_marker)), (end_marker_start, end))
    return start, end, spans


def _resolve_operation(module: bytes, operation: ModuleOperationV2) -> _Resolved:
    if operation.type == "replace_between":
        if operation.start_marker is None or operation.end_marker is None:
            raise ModulePatchError(
                f"{operation.op_id}: replace_between requires startMarker and endMarker"
            )
        start_marker = _b(operation.start_marker)
        end_marker = _b(operation.end_marker)
        start_count = _count(module, start_marker)
        if start_count != operation.expected_start_marker_count:
            raise ModulePatchError(
                f"{operation.op_id}: start marker count {start_count} "
                f"!= {operation.expected_start_marker_count}"
            )
        start = module.find(start_marker)
        tail = module[start + len(start_marker) :]
        end_count = _count(tail, end_marker)
        if end_count != operation.expected_end_marker_count:
            raise ModulePatchError(
                f"{operation.op_id}: end marker count {end_count} "
                f"!= {operation.expected_end_marker_count}"
            )
        end = module.find(end_marker, start + len(start_marker))
    elif operation.type == "replace_exact":
        if operation.exact is None:
            raise ModulePatchError(f"{operation.op_id}: replace_exact requires exact")
        exact = _b(operation.exact)
        exact_count = _count(module, exact)
        if exact_count != 1:
            raise ModulePatchError(f"{operation.op_id}: exact marker count {exact_count} != 1")
        start = module.find(exact)
        end = start + len(exact)
    elif operation.type in {"insert_before", "insert_after"}:
        if operation.anchor is None:
            raise ModulePatchError(f"{operation.op_id}: insertion requires anchor")
        anchor = _b(operation.anchor)
        if operation.start_marker is not None:
            ctx_start, ctx_end, ctx_spans = _resolve_context(module, operation)
        else:
            ctx_start, ctx_end, ctx_spans = None, None, ()
        scope_base = ctx_start if ctx_start is not None else 0
        scope = module[ctx_start:ctx_end] if ctx_start is not None else module
        anchor_count = _count(scope, anchor)
        if anchor_count != 1:
            raise ModulePatchError(f"{operation.op_id}: anchor count {anchor_count} != 1")
        found = scope_base + scope.find(anchor)
        point = found if operation.type == "insert_before" else found + len(anchor)
        return _Resolved(
            start=point,
            end=point,
            context_start=ctx_start,
            context_end=ctx_end,
            evidence_spans=ctx_spans + ((found, found + len(anchor)),),
        )
    elif operation.type == "replace_substring_within":
        if operation.sub_exact is None:
            raise ModulePatchError(
                f"{operation.op_id}: replace_substring_within requires subExact"
            )
        ctx_start, ctx_end, _ctx_spans = _resolve_context(module, operation)
        sub = _b(operation.sub_exact)
        scope = module[ctx_start:ctx_end]
        sub_count = _count(scope, sub)
        if sub_count != 1:
            raise ModulePatchError(f"{operation.op_id}: subExact count {sub_count} != 1")
        start = ctx_start + scope.find(sub)
        return _Resolved(
            start=start,
            end=start + len(sub),
            context_start=ctx_start,
            context_end=ctx_end,
        )
    else:
        raise ModulePatchError(f"{operation.op_id}: unsupported operation type {operation.type}")
    if start < 0 or end < 0 or end < start:
        raise ModulePatchError(f"{operation.op_id}: invalid module range [{start},{end})")
    return _Resolved(start, end)


def plan_module_operations(
    package_id: str,
    module_path: str,
    module_content: bytes,
    operations: list[tuple[ModuleOperationV2, bytes]],
) -> list[PlannedModuleOperation]:
    planned: list[PlannedModuleOperation] = []
    for operation, replacement in operations:
        resolved = _resolve_operation(module_content, operation)
        start, end = resolved.start, resolved.end
        old = module_content[start:end]
        for required in operation.require_within_range:
            if _b(required) not in old:
                raise ModulePatchError(
                    f"{operation.op_id}: required bytes missing from range: {required}"
                )
        if operation.old_range_length is not None and operation.old_range_length != len(old):
            raise ModulePatchError(f"{operation.op_id}: old range length mismatch")
        old_sha = hashlib.sha256(old).hexdigest()
        if operation.old_range_sha256 is not None and operation.old_range_sha256 != old_sha:
            raise ModulePatchError(f"{operation.op_id}: old range sha256 mismatch")
        if (
            operation.context_sha256 is not None
            and resolved.context_start is not None
            and resolved.context_end is not None
        ):
            context = module_content[resolved.context_start : resolved.context_end]
            if hashlib.sha256(context).hexdigest() != operation.context_sha256:
                raise ModulePatchError(f"{operation.op_id}: context sha256 mismatch")
        planned.append(
            PlannedModuleOperation(
                package_id=package_id,
                op_id=operation.op_id,
                label=operation.label,
                module_path=module_path,
                module_start=start,
                module_end=end,
                old_len=len(old),
                new_len=len(replacement),
                delta=len(replacement) - len(old),
                old_sha256=old_sha,
                replacement=replacement,
                op_type=operation.type,
                insert_order=operation.insert_order,
                context_start=resolved.context_start,
                context_end=resolved.context_end,
                evidence_spans=resolved.evidence_spans,
                anchor=operation.anchor,
                seam_hint=operation.seam_hint,
            )
        )
    planned.sort(key=planned_operation_render_order)
    check_planned_conflicts(planned)
    return planned


def planned_operation_render_order(item: PlannedModuleOperation) -> tuple:
    return (
        item.module_start,
        item.module_end,
        item.insert_order if item.insert_order is not None else 0,
        item.package_id,
        item.op_id,
    )


def shared_insertion_points(
    planned: list[PlannedModuleOperation],
) -> dict[int, list[PlannedModuleOperation]]:
    points: dict[int, list[PlannedModuleOperation]] = {}
    for item in sorted(planned, key=planned_operation_render_order):
        if item.kind == "insertion":
            points.setdefault(item.module_start, []).append(item)
    return points


def check_planned_conflicts(planned: list[PlannedModuleOperation]) -> None:
    ordered = sorted(planned, key=planned_operation_render_order)
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.module_end > right.module_start:
            if "insertion" in (left.kind, right.kind):
                inserter, owner = (left, right) if left.kind == "insertion" else (right, left)
                raise ModulePatchError(
                    "patch_conflict:insert_inside_claimed_range:"
                    f"{inserter.package_id}:{inserter.op_id}:{owner.package_id}:{owner.op_id}"
                )
            raise ModulePatchError(
                "patch_conflict:range_overlap:"
                f"{left.package_id}:{left.op_id}:{right.package_id}:{right.op_id}"
            )
    for offset, items in sorted(shared_insertion_points(ordered).items()):
        if len(items) < 2:
            continue
        if any(item.insert_order is None for item in items):
            raise ModulePatchError(
                f"patch_conflict:insert_order_required:{items[0].module_path}:{offset}"
            )
        seen_orders: set[int] = set()
        for item in items:
            assert item.insert_order is not None
            if item.insert_order in seen_orders:
                raise ModulePatchError(
                    f"patch_conflict:insert_order_duplicate:"
                    f"{item.module_path}:{offset}:{item.insert_order}"
                )
            seen_orders.add(item.insert_order)
    claimed = [item for item in ordered if item.module_end > item.module_start]
    for item in ordered:
        if item.kind != "insertion":
            continue
        for evidence_start, evidence_end in item.evidence_spans:
            for owner in claimed:
                if evidence_start < owner.module_end and owner.module_start < evidence_end:
                    raise ModulePatchError(
                        f"patch_conflict:insert_anchor_inside_claimed_range:"
                        f"{item.package_id}:{item.op_id}:{owner.package_id}:{owner.op_id}"
                    )


def render_changed_module(module_content: bytes, planned: list[PlannedModuleOperation]) -> bytes:
    output = bytearray()
    cursor = 0
    for item in sorted(planned, key=planned_operation_render_order):
        output.extend(module_content[cursor : item.module_start])
        output.extend(item.replacement)
        cursor = item.module_end
    output.extend(module_content[cursor:])
    return bytes(output)


def verify_insertions(
    rendered: bytes, planned: list[PlannedModuleOperation]
) -> list[dict]:
    results: list[dict] = []
    delta = 0
    for item in sorted(planned, key=planned_operation_render_order):
        final_start = item.module_start + delta
        if item.kind == "insertion":
            verified = rendered[final_start : final_start + item.new_len] == item.replacement
            results.append(
                {
                    "packageId": item.package_id,
                    "opId": item.op_id,
                    "finalOffset": final_start,
                    "insertionVerified": verified,
                }
            )
        delta += item.delta
    return results
