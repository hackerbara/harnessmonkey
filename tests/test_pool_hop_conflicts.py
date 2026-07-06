"""The pool-hop text hook must never overlap fable-fallback's claimed range.

Byte-level regression: resolves both packages' claims in the real 2.1.201
module and asserts ordering. Complements builder-level check_planned_conflicts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
LIVE_SOURCE = claude_version_path("2.1.201")

OTHER_PACKAGE_IDS = [
    "drawer-dock",
    "hidden-context-drawer",
    "reminders-drawer",
    "thinking-drawer",
]


def _module_text() -> str:
    import sys

    sys.path.insert(0, str(ROOT / "examples"))
    from art_package_emitter import module_content  # reuse the generator's extractor

    source_bytes = LIVE_SOURCE.read_bytes()
    return module_content(source_bytes).decode("utf-8")


def test_hook_anchor_sits_strictly_before_fable_fallback_claim():
    if not LIVE_SOURCE.exists():
        pytest.skip(f"local Claude Code 2.1.201 source missing: {LIVE_SOURCE}")
    module = _module_text()

    capy = json.loads((ROOT / "packages/capybara-onsen/patch.json").read_text())
    capy_ops = capy["patch"]["targets"][0]["modules"][0]["operations"]
    hook = next(op for op in capy_ops if op["opId"].startswith("capy-onsen-assistant-text-hook"))
    anchor = hook["exact"]
    assert module.count(anchor) == 1, "hook anchor no longer unique in module"
    hook_end = module.find(anchor) + len(anchor)

    fable = json.loads((ROOT / "packages/fable-fallback/patch.json").read_text())
    fable_ops = fable["patch"]["targets"][0]["modules"][0]["operations"]
    banner = next(op for op in fable_ops if op["opId"] == "gcm-assistant-fallback-banner")
    start_marker = banner["startMarker"]
    assert module.count(start_marker) == 1, "fable-fallback start marker no longer unique"
    fable_start = module.find(start_marker)

    assert hook_end <= fable_start, (
        f"pool-hop hook range end {hook_end} overlaps fable-fallback claim start {fable_start}"
    )


def test_note_sink_anchor_unique_and_does_not_overlap_other_packages():
    """The pool-break note-sink anchor must not collide with any other

    active-profile package's claimed byte range. Byte-level regression,
    complementing check_planned_conflicts at the builder level.
    """
    if not LIVE_SOURCE.exists():
        pytest.skip(f"local Claude Code 2.1.201 source missing: {LIVE_SOURCE}")
    module = _module_text()
    module_bytes = module.encode("utf-8")

    capy = json.loads((ROOT / "packages/capybara-onsen/patch.json").read_text())
    capy_ops = capy["patch"]["targets"][0]["modules"][0]["operations"]
    note_op = next(
        op for op in capy_ops if op["opId"].startswith("capy-onsen-note-sink-after-dwc")
    )
    anchor = note_op["exact"]
    assert module.count(anchor) == 1, "note-sink anchor no longer unique in module"
    note_start = module.find(anchor)
    note_end = note_start + len(anchor)

    from harnessmonkey.manifest_v2 import parse_operation
    from harnessmonkey.module_patch import plan_module_operations

    capy_module_sha = capy["patch"]["targets"][0]["modules"][0]["contentSha256"]
    for package_id in OTHER_PACKAGE_IDS:
        manifest = json.loads((ROOT / "packages" / package_id / "patch.json").read_text())
        module_target = manifest["patch"]["targets"][0]["modules"][0]
        assert module_target["contentSha256"] == capy_module_sha, (
            f"{package_id}: pinned to a different module than capybara-onsen"
        )
        raw_ops = module_target["operations"]
        operations = [(parse_operation(op), b"") for op in raw_ops]
        planned = plan_module_operations(
            package_id, module_target["path"], module_bytes, operations
        )
        for item in planned:
            overlaps = item.module_start < note_end and note_start < item.module_end
            assert not overlaps, (
                f"note-sink anchor [{note_start},{note_end}) overlaps {package_id}:"
                f"{item.op_id} [{item.module_start},{item.module_end})"
            )
