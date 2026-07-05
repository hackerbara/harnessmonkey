from __future__ import annotations

import hashlib

import pytest

from harnessmonkey.manifest_v2 import ModuleOperationV2, PayloadRefV2
from harnessmonkey.module_patch import (
    ModulePatchError,
    plan_module_operations,
    render_changed_module,
    verify_insertions,
)

MODULE = b"function render(){OLD_RENDER}\nfunction after(){return 1}\n"


def op(replacement: bytes) -> ModuleOperationV2:
    old = MODULE[: MODULE.index(b"function after(){")]
    return ModuleOperationV2(
        op_id="replace-renderer",
        label="Replace renderer",
        type="replace_between",
        start_marker="function render(){",
        end_marker="function after(){",
        exact=None,
        expected_start_marker_count=1,
        expected_end_marker_count=1,
        require_within_range=("OLD_RENDER",),
        old_range_sha256=hashlib.sha256(old).hexdigest(),
        old_range_length=len(old),
        replacement=PayloadRefV2(inline=replacement.decode("utf-8")),
        known_behavior_change=None,
    )


def test_plan_module_operations_allows_growth_without_padding():
    replacement = b"function render(){NEW_RENDER_LONGER}\n"
    planned = plan_module_operations(
        "pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, [(op(replacement), replacement)]
    )
    assert planned[0].module_start == 0
    assert planned[0].module_end == MODULE.index(b"function after(){")
    assert planned[0].old_len < planned[0].new_len
    changed = render_changed_module(MODULE, planned)
    assert replacement in changed
    assert len(changed) > len(MODULE)


def test_plan_module_operations_rejects_old_range_hash_mismatch():
    operation = op(b"function render(){NEW}\n")
    operation = ModuleOperationV2(**{**operation.__dict__, "old_range_sha256": "0" * 64})
    with pytest.raises(ModulePatchError, match="old range sha256 mismatch"):
        plan_module_operations(
            "pkg",
            "/$bunfs/root/src/entrypoints/cli.js",
            MODULE,
            [(operation, b"function render(){NEW}\n")],
        )


def test_plan_module_operations_rejects_overlaps():
    first = op(b"function render(){NEW}\n")
    second = ModuleOperationV2(
        **{
            **first.__dict__,
            "op_id": "overlap",
            "start_marker": "OLD",
            "end_marker": "after",
            "old_range_sha256": None,
            "old_range_length": None,
        }
    )
    with pytest.raises(ModulePatchError, match="patch_conflict:range_overlap"):
        plan_module_operations(
            "pkg",
            "/$bunfs/root/src/entrypoints/cli.js",
            MODULE,
            [(first, b"function render(){NEW}\n"), (second, b"NEW")],
        )



def make_op(**overrides) -> ModuleOperationV2:
    base = dict(
        op_id="insert-entry",
        label="Insert entry",
        type="insert_after",
        start_marker=None,
        end_marker=None,
        exact=None,
        expected_start_marker_count=1,
        expected_end_marker_count=1,
        require_within_range=(),
        old_range_sha256=None,
        old_range_length=None,
        replacement=PayloadRefV2(inline=",NEW_ENTRY"),
        known_behavior_change=None,
        anchor="OLD_RENDER",
        insert_order=None,
    )
    base.update(overrides)
    return ModuleOperationV2(**base)


def test_insert_after_plans_zero_width_point_after_anchor():
    replacement = b",NEW_ENTRY"
    planned = plan_module_operations(
        "pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, [(make_op(), replacement)]
    )
    point = MODULE.index(b"OLD_RENDER") + len(b"OLD_RENDER")
    item = planned[0]
    assert item.kind == "insertion"
    assert item.op_type == "insert_after"
    assert (item.module_start, item.module_end) == (point, point)
    assert item.old_len == 0
    assert item.new_len == len(replacement)
    assert item.delta == len(replacement)
    anchor_start = MODULE.index(b"OLD_RENDER")
    assert (anchor_start, anchor_start + len(b"OLD_RENDER")) in item.evidence_spans
    changed = render_changed_module(MODULE, planned)
    assert b"OLD_RENDER,NEW_ENTRY" in changed
    assert len(changed) == len(MODULE) + len(replacement)


def test_insert_before_plans_point_at_anchor_start():
    replacement = b"PREFIX_"
    planned = plan_module_operations(
        "pkg",
        "/$bunfs/root/src/entrypoints/cli.js",
        MODULE,
        [(make_op(type="insert_before"), replacement)],
    )
    assert planned[0].module_start == MODULE.index(b"OLD_RENDER")
    changed = render_changed_module(MODULE, planned)
    assert b"PREFIX_OLD_RENDER" in changed


def test_insertion_rejects_ambiguous_anchor():
    with pytest.raises(ModulePatchError, match="anchor count 2"):
        plan_module_operations(
            "pkg",
            "/$bunfs/root/src/entrypoints/cli.js",
            MODULE,
            [(make_op(anchor="function"), b",X")],
        )


def test_insertion_context_bounds_anchor_search():
    # "return 1" appears once; "n" appears many times. Context makes "n 1" unique scope.
    operation = make_op(
        anchor="return 1",
        start_marker="function after(){",
        end_marker="}",
        expected_end_marker_count=1,
    )
    planned = plan_module_operations(
        "pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, [(operation, b";EXTRA()")]
    )
    item = planned[0]
    ctx_start = MODULE.index(b"function after(){")
    assert item.context_start == ctx_start
    assert item.context_end is not None and item.context_end > ctx_start
    changed = render_changed_module(MODULE, planned)
    assert b"return 1;EXTRA()" in changed


def test_insertion_missing_anchor_in_context_fails():
    operation = make_op(
        anchor="OLD_RENDER",
        start_marker="function after(){",
        end_marker="}",
    )
    with pytest.raises(ModulePatchError, match="anchor count 0"):
        plan_module_operations(
            "pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, [(operation, b",X")]
        )



def test_replace_substring_within_claims_only_subspan():
    operation = make_op(
        op_id="sub",
        type="replace_substring_within",
        anchor=None,
        start_marker="function render(){",
        end_marker="}",
        expected_end_marker_count=2,
        sub_exact="OLD_RENDER",
        replacement=PayloadRefV2(inline="OLD_RENDER,EXTRA_FLAG"),
    )
    replacement = b"OLD_RENDER,EXTRA_FLAG"
    planned = plan_module_operations(
        "pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, [(operation, replacement)]
    )
    item = planned[0]
    assert item.kind == "subspan_replacement"
    assert item.module_start == MODULE.index(b"OLD_RENDER")
    assert item.module_end == item.module_start + len(b"OLD_RENDER")
    assert item.context_start == MODULE.index(b"function render(){")
    changed = render_changed_module(MODULE, planned)
    assert b"function render(){OLD_RENDER,EXTRA_FLAG}" in changed
    # bytes outside the subspan are untouched stock
    assert changed.endswith(b"function after(){return 1}\n")


def test_replace_substring_within_rejects_non_unique_subspan():
    operation = make_op(
        op_id="sub-dup",
        type="replace_substring_within",
        anchor=None,
        start_marker="function render(){",
        end_marker="return 1}",
        expected_end_marker_count=1,
        sub_exact="function",  # appears twice inside this context
        replacement=PayloadRefV2(inline="fn"),
    )
    with pytest.raises(ModulePatchError, match="subExact count"):
        plan_module_operations(
            "pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, [(operation, b"fn")]
        )


def test_replace_substring_within_context_sha_mismatch_fails():
    operation = make_op(
        op_id="sub-ctx",
        type="replace_substring_within",
        anchor=None,
        start_marker="function render(){",
        end_marker="}",
        expected_end_marker_count=2,
        sub_exact="OLD_RENDER",
        context_sha256="0" * 64,
        replacement=PayloadRefV2(inline="NEW"),
    )
    with pytest.raises(ModulePatchError, match="context sha256 mismatch"):
        plan_module_operations(
            "pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, [(operation, b"NEW")]
        )


def test_replace_substring_within_old_range_applies_to_subspan():
    old = b"OLD_RENDER"
    operation = make_op(
        op_id="sub-old",
        type="replace_substring_within",
        anchor=None,
        start_marker="function render(){",
        end_marker="}",
        expected_end_marker_count=2,
        sub_exact="OLD_RENDER",
        old_range_sha256=hashlib.sha256(old).hexdigest(),
        old_range_length=len(old),
        replacement=PayloadRefV2(inline="NEW"),
    )
    planned = plan_module_operations(
        "pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, [(operation, b"NEW")]
    )
    assert planned[0].old_len == len(old)




def _plan(ops):
    return plan_module_operations("pkg", "/$bunfs/root/src/entrypoints/cli.js", MODULE, ops)


def test_shared_point_insertions_merge_in_insert_order():
    a = make_op(op_id="a", insert_order=200, replacement=PayloadRefV2(inline=",SECOND"))
    b = make_op(op_id="b", insert_order=100, replacement=PayloadRefV2(inline=",FIRST"))
    planned = _plan([(a, b",SECOND"), (b, b",FIRST")])
    changed = render_changed_module(MODULE, planned)
    assert b"OLD_RENDER,FIRST,SECOND" in changed


def test_shared_point_duplicate_insert_order_fails():
    a = make_op(op_id="a", insert_order=100)
    b = make_op(op_id="b", insert_order=100)
    with pytest.raises(ModulePatchError, match="patch_conflict:insert_order_duplicate"):
        _plan([(a, b",X"), (b, b",Y")])


def test_shared_point_missing_insert_order_fails():
    a = make_op(op_id="a", insert_order=100)
    b = make_op(op_id="b")  # insert_order=None
    with pytest.raises(ModulePatchError, match="patch_conflict:insert_order_required"):
        _plan([(a, b",X"), (b, b",Y")])


def test_single_insertion_needs_no_insert_order():
    planned = _plan([(make_op(), b",ONLY")])
    assert planned[0].insert_order is None


def test_insertion_inside_claimed_range_fails():
    # replacement claims [render-start, "function after(){"); insertion point lands inside it
    replacement_op = op(b"function render(){NEW}\n")  # existing replace_between helper
    inside = make_op(
        op_id="inside",
        anchor="function render(){",  # insert_after -> point inside claimed range
    )
    with pytest.raises(ModulePatchError, match="patch_conflict:insert_inside_claimed_range"):
        _plan([(replacement_op, b"function render(){NEW}\n"), (inside, b",X")])


def test_insertion_anchor_inside_claimed_range_fails():
    # anchor "OLD_RENDER" lies INSIDE the replacement's claimed range, but the
    # insert_after point would be at offset 28 which is also inside; use an anchor
    # whose END coincides with the claimed range END so the point is at the boundary:
    # claimed range end is at index of "function after(){"; anchor ends exactly there.
    end = MODULE.index(b"function after(){")
    anchor_text = MODULE[end - 10 : end].decode()  # last 10 bytes of the claimed range
    replacement_op = op(b"function render(){NEW}\n")
    boundary = make_op(op_id="boundary", anchor=anchor_text)
    with pytest.raises(
        ModulePatchError, match="patch_conflict:insert_anchor_inside_claimed_range"
    ):
        _plan([(replacement_op, b"function render(){NEW}\n"), (boundary, b",X")])


def test_replacement_overlap_reports_range_overlap_code():
    first = op(b"function render(){NEW}\n")
    second = ModuleOperationV2(
        **{
            **first.__dict__,
            "op_id": "overlap",
            "start_marker": "OLD",
            "end_marker": "after",
            "old_range_sha256": None,
            "old_range_length": None,
        }
    )
    with pytest.raises(ModulePatchError, match="patch_conflict:range_overlap"):
        _plan([(first, b"function render(){NEW}\n"), (second, b"NEW")])


def test_insertion_at_replacement_end_boundary_with_outside_anchor_is_allowed():
    # anchor entirely OUTSIDE the claimed range, point at/after boundary: allowed
    replacement_op = op(b"function render(){NEW}\n")
    after = make_op(op_id="after-fn", anchor="function after(){return 1}")
    planned = _plan([(replacement_op, b"function render(){NEW}\n"), (after, b"/*T*/")])
    changed = render_changed_module(MODULE, planned)
    assert b"function after(){return 1}/*T*/" in changed
    assert b"function render(){NEW}" in changed




def test_render_orders_same_point_insertions_by_insert_order_not_list_order():
    a = make_op(op_id="a", insert_order=300, replacement=PayloadRefV2(inline=",LAST"))
    b = make_op(op_id="b", insert_order=100, replacement=PayloadRefV2(inline=",FIRST"))
    c = make_op(op_id="c", insert_order=200, replacement=PayloadRefV2(inline=",MID"))
    planned = _plan([(a, b",LAST"), (b, b",FIRST"), (c, b",MID")])
    changed = render_changed_module(MODULE, planned)
    assert b"OLD_RENDER,FIRST,MID,LAST" in changed
    # determinism: shuffled input order produces identical bytes
    planned_shuffled = _plan([(c, b",MID"), (a, b",LAST"), (b, b",FIRST")])
    assert render_changed_module(MODULE, planned_shuffled) == changed


def test_verify_insertions_reports_final_offsets():
    a = make_op(op_id="a", insert_order=100, replacement=PayloadRefV2(inline=",FIRST"))
    b = make_op(op_id="b", insert_order=200, replacement=PayloadRefV2(inline=",SECOND"))
    planned = _plan([(a, b",FIRST"), (b, b",SECOND")])
    rendered = render_changed_module(MODULE, planned)
    results = verify_insertions(rendered, planned)
    assert len(results) == 2
    assert all(item["insertionVerified"] for item in results)
    by_op = {item["opId"]: item for item in results}
    point = MODULE.index(b"OLD_RENDER") + len(b"OLD_RENDER")
    assert by_op["a"]["finalOffset"] == point
    assert by_op["b"]["finalOffset"] == point + len(b",FIRST")


def test_verify_insertions_detects_corrupt_render():
    planned = _plan([(make_op(op_id="a"), b",ENTRY")])
    rendered = render_changed_module(MODULE, planned)
    corrupted = rendered.replace(b",ENTRY", b",WRONGX")
    results = verify_insertions(corrupted, planned)
    assert results[0]["insertionVerified"] is False
