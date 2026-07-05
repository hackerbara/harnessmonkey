from __future__ import annotations

from pathlib import Path

import pytest
from tests.fixtures_bun import (
    MODULE_PATH_0,
    MODULE_PATH_1,
    build_aligned_macho_fixture,
)

from harnessmonkey.binary_inspect import inspect_binary_bytes
from harnessmonkey.bun_graph import parse_bun_section
from harnessmonkey.macho import find_macho_layout
from harnessmonkey.repack import repack_changed_modules


def test_repack_changed_modules_updates_module_and_preserves_inspectability():
    source, _ = build_aligned_macho_fixture()
    layout = find_macho_layout(source)
    graph = parse_bun_section(
        source[layout.bun_section.offset : layout.bun_section.offset + layout.bun_section.size]
    )
    new_module = b"function render(){NEW_RENDER_LONGER}\nfunction after(){return 1}\n"
    result = repack_changed_modules(source, {MODULE_PATH_0: new_module})
    assert result.delta > 0
    inspected = inspect_binary_bytes(result.output_bytes, source_path="fixture-output")
    assert inspected["ok"] is True
    assert inspected["validationErrors"] == []
    layout2 = find_macho_layout(result.output_bytes)
    graph2 = parse_bun_section(
        result.output_bytes[
            layout2.bun_section.offset : layout2.bun_section.offset + layout2.bun_section.size
        ]
    )
    assert graph2.module_by_path(MODULE_PATH_0).content == new_module
    assert graph2.declared_payload_len == graph.declared_payload_len + result.delta


def test_repack_changed_modules_is_deterministic_for_two_modules():
    source, _ = build_aligned_macho_fixture()
    changed = {
        MODULE_PATH_1: b"x=1;\n",
        MODULE_PATH_0: b"function render(){NEW_RENDER_LONGER}\nfunction after(){return 1}\n",
    }
    first = repack_changed_modules(source, changed)
    second = repack_changed_modules(source, dict(reversed(list(changed.items()))))
    assert first.output_bytes == second.output_bytes
    inspected = inspect_binary_bytes(first.output_bytes, source_path="fixture-output")
    assert inspected["ok"] is True


def test_repack_plus_one_preserves_aligned_segment_and_linkedit_offsets():
    source, _ = build_aligned_macho_fixture()
    layout = find_macho_layout(source)
    graph = parse_bun_section(
        source[layout.bun_section.offset : layout.bun_section.offset + layout.bun_section.size]
    )
    module = graph.module_by_path(MODULE_PATH_0)

    result = repack_changed_modules(source, {MODULE_PATH_0: module.content + b"X"})

    reparsed = find_macho_layout(result.output_bytes)
    assert result.delta == 1
    assert reparsed.bun_section.size == layout.bun_section.size + 1
    assert reparsed.bun_segment.filesize % 0x4000 == 0
    assert reparsed.bun_segment.vmsize % 0x4000 == 0
    assert reparsed.linkedit_segment.fileoff % 0x4000 == 0
    assert reparsed.linkedit_segment.vmaddr % 0x4000 == 0
    assert reparsed.linkedit_segment.fileoff == layout.linkedit_segment.fileoff


def test_real_spike_plus_one_preserves_linkedit_alignment_if_artifact_exists():
    root = Path(__file__).resolve().parents[1]
    artifact = (
        root
        / ".development"
        / "repack-spike-20260702-codex"
        / "artifacts"
        / "claude-2.1.198.graph-repack-floating-blue-box-v4-grow16384"
    )
    if not artifact.exists():
        pytest.skip("local real repack spike artifact is not present")
    data = artifact.read_bytes()
    layout = find_macho_layout(data)
    graph = parse_bun_section(
        data[layout.bun_section.offset : layout.bun_section.offset + layout.bun_section.size]
    )
    module = graph.module_by_path(MODULE_PATH_0)

    result = repack_changed_modules(data, {MODULE_PATH_0: module.content + b"X"})

    reparsed = find_macho_layout(result.output_bytes)
    assert result.delta == 1
    assert reparsed.bun_section.size == layout.bun_section.size + 1
    assert reparsed.bun_segment.filesize % 0x4000 == 0
    assert reparsed.linkedit_segment.fileoff % 0x4000 == 0
