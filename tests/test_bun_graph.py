from __future__ import annotations

import pytest
from tests.fixtures_bun import MODULE_PATH_0, TRAILER, build_payload

from harnessmonkey.bun_graph import BunGraphError, parse_bun_section


def test_parse_bun_section_lists_modules():
    section, _ = build_payload()
    graph = parse_bun_section(section)
    assert graph.declared_payload_len == len(section) - 8
    assert graph.module_record_size == 52
    assert graph.modules[0].path == MODULE_PATH_0
    assert graph.modules[0].content.startswith(b"function render")
    assert graph.validation_errors == []


def test_parse_bun_section_rejects_bad_trailer():
    section, _ = build_payload()
    bad = section.replace(TRAILER, b"\n---- Bad! ----\n")
    with pytest.raises(BunGraphError, match="trailer"):
        parse_bun_section(bad)


def test_replace_module_content_updates_graph_and_shifts_later_offsets():
    section, offsets = build_payload()
    graph = parse_bun_section(section)
    old_module1_offset = graph.modules[1].content_offset
    changed = graph.replace_module_content(
        MODULE_PATH_0, b"function render(){NEW_RENDER_LONGER}\nfunction after(){return 1}\n"
    )
    reparsed = parse_bun_section(changed.section_bytes)
    assert (
        reparsed.module_by_path(MODULE_PATH_0).content
        == b"function render(){NEW_RENDER_LONGER}\nfunction after(){return 1}\n"
    )
    assert reparsed.modules[1].content_offset > old_module1_offset
    assert changed.delta > 0
    assert changed.validation_errors == []


def test_module_by_path_requires_unique_path():
    section, _ = build_payload()
    graph = parse_bun_section(section)
    with pytest.raises(BunGraphError, match="module_not_found"):
        graph.module_by_path("/$bunfs/root/src/missing.js")


def test_parse_bun_section_rejects_module_table_size_not_divisible_by_52():
    section, _ = build_payload()
    payload = bytearray(section)
    trailer_off = bytes(payload[8:]).rfind(TRAILER)
    offsets_off = 8 + trailer_off - 32
    # modules_size is at offsets struct + 12. Make it invalid.
    payload[offsets_off + 12 : offsets_off + 16] = (53).to_bytes(4, "little")
    with pytest.raises(BunGraphError, match="bun_module_table_invalid"):
        parse_bun_section(bytes(payload))


def test_parse_bun_section_rejects_pointer_out_of_bounds():
    section, _ = build_payload()
    payload = bytearray(section)
    trailer_off = bytes(payload[8:]).rfind(TRAILER)
    offsets_off = 8 + trailer_off - 32
    modules_offset = int.from_bytes(payload[offsets_off + 8 : offsets_off + 12], "little")
    first_record = 8 + modules_offset
    payload[first_record + 8 : first_record + 12] = (999999).to_bytes(4, "little")
    with pytest.raises(BunGraphError, match="pointer_out_of_bounds"):
        parse_bun_section(bytes(payload))


def test_parse_bun_section_does_not_apply_content_plus_8_assumption():
    section, _ = build_payload()
    graph = parse_bun_section(section)
    module = graph.module_by_path(MODULE_PATH_0)
    assert module.content.startswith(b"function render")
    assert not module.content[0:1] == b" "


def test_parse_bun_section_reports_duplicate_module_paths():
    section, _ = build_payload()
    payload = bytearray(section)
    trailer_off = bytes(payload[8:]).rfind(TRAILER)
    offsets_off = 8 + trailer_off - 32
    modules_offset = int.from_bytes(payload[offsets_off + 8 : offsets_off + 12], "little")
    first_record = 8 + modules_offset
    second_record = first_record + 52
    payload[second_record : second_record + 8] = payload[first_record : first_record + 8]

    graph = parse_bun_section(bytes(payload))

    assert any("duplicate_module_path" in item for item in graph.validation_errors)
