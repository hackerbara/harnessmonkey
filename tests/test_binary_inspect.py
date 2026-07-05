from __future__ import annotations

from tests.fixtures_bun import MODULE_PATH_0, TRAILER, build_macho_fixture

from harnessmonkey.binary_inspect import inspect_binary_bytes


def test_inspect_binary_bytes_reports_bun_modules():
    data, _ = build_macho_fixture()
    report = inspect_binary_bytes(data, source_path="fixture-claude")
    assert report["ok"] is True
    assert report["format"] == "macho64"
    assert report["bun"]["moduleRecordSize"] == 52
    assert report["modules"][0]["path"] == MODULE_PATH_0
    assert report["validationErrors"] == []


def test_inspect_binary_bytes_marks_duplicate_module_paths_not_ok():
    data, _ = build_macho_fixture()
    binary = bytearray(data)
    from harnessmonkey.macho import find_macho_layout

    layout = find_macho_layout(binary)
    section_start = layout.bun_section.offset
    section = bytearray(binary[section_start : section_start + layout.bun_section.size])
    trailer_off = bytes(section[8:]).rfind(TRAILER)
    offsets_off = 8 + trailer_off - 32
    modules_offset = int.from_bytes(section[offsets_off + 8 : offsets_off + 12], "little")
    first_record = 8 + modules_offset
    second_record = first_record + 52
    section[second_record : second_record + 8] = section[first_record : first_record + 8]
    binary[section_start : section_start + layout.bun_section.size] = section

    report = inspect_binary_bytes(bytes(binary), source_path="duplicate-path-fixture")

    assert report["ok"] is False
    assert any("duplicate_module_path" in item for item in report["validationErrors"])
