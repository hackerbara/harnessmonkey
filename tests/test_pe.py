import struct

import pytest
from tests.harnessmonkey_binary import win_claude_bin
from tests.fixtures_bun import MODULE_PATH_0, build_payload
from tests.fixtures_pe import build_pe_fixture

from harnessmonkey.bun_graph import parse_bun_section
from harnessmonkey.pe import PEError, find_pe_layout, pe_checksum, repack_changed_modules


def test_find_pe_layout_on_fixture():
    section, _ = build_payload()
    data = build_pe_fixture(section)
    layout = find_pe_layout(data)
    assert layout.bun_section.name == ".bun"
    assert layout.bun_section.index == layout.num_sections - 1
    assert layout.bun_section.raw_pointer + layout.bun_section.raw_size == len(data)
    assert layout.security_rva == 0  # no Authenticode on plain fixture


def test_find_pe_layout_detects_authenticode():
    section, _ = build_payload()
    data = build_pe_fixture(section, with_authenticode=True)
    layout = find_pe_layout(data)
    assert layout.security_rva != 0 and layout.security_size != 0


def test_rejects_non_pe():
    with pytest.raises(PEError):
        find_pe_layout(b"\x00" * 512)


def test_rejects_truncated_optional_header():
    # Valid MZ/e_lfanew/PE signature and PE32+ magic present, but the buffer
    # is cut off before the Security DataDirectory entry in the optional
    # header. Must raise PEError, not struct.error.
    section, _ = build_payload()
    data = build_pe_fixture(section)
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    opt = e_lfanew + 24
    truncated = data[:opt + 40]
    with pytest.raises(PEError):
        find_pe_layout(truncated)


def test_rejects_truncated_section_table():
    # Full, valid optional header present, but cut off partway through the
    # first section header. Must raise PEError, not struct.error.
    section, _ = build_payload()
    data = build_pe_fixture(section)
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    size_opt = struct.unpack_from("<H", data, e_lfanew + 20)[0]
    st = e_lfanew + 24 + size_opt
    truncated = data[:st + 10]
    with pytest.raises(PEError):
        find_pe_layout(truncated)


def test_find_pe_layout_on_real_windows_binary():
    src = win_claude_bin()
    if not src.exists():
        pytest.skip(f"missing Windows claude.exe fixture: {src}")
    data = src.read_bytes()
    layout = find_pe_layout(data)
    assert layout.bun_section.name == ".bun"
    assert layout.bun_section.raw_pointer == 0x4F3F200
    assert layout.bun_section.raw_size == 0x9724C00
    assert layout.security_rva == 0xE663E00
    assert layout.security_size == 0x28A0
    # stored checksum lives at checksum_offset
    assert struct.unpack_from("<I", data, layout.checksum_offset)[0] == 0xE67537E


def test_pe_checksum_matches_real_binary():
    src = win_claude_bin()
    if not src.exists():
        pytest.skip(f"missing Windows claude.exe fixture: {src}")
    data = bytearray(src.read_bytes())
    layout = find_pe_layout(data)
    struct.pack_into("<I", data, layout.checksum_offset, 0)
    assert pe_checksum(bytes(data)) == 0xE67537E


def _bun_section_bytes(data):
    layout = find_pe_layout(data)
    b = layout.bun_section
    return data[b.raw_pointer:b.raw_pointer + b.raw_size]


def test_repack_grows_module_on_fixture():
    section, _ = build_payload()
    data = build_pe_fixture(section, with_authenticode=True)
    original = parse_bun_section(section)
    mod0 = original.module_by_path(MODULE_PATH_0)
    new_content = mod0.content + b"// PADDING TO GROW THE MODULE"
    result = repack_changed_modules(bytes(data), {MODULE_PATH_0: new_content})

    out = result.output_bytes
    layout = find_pe_layout(out)
    # Authenticode stripped: security dir zeroed, .bun now genuinely last.
    assert layout.security_rva == 0
    assert layout.bun_section.raw_pointer + layout.bun_section.raw_size == len(out)
    # Edited payload re-parses and carries the grown module.
    graph = parse_bun_section(_bun_section_bytes(out))
    assert graph.validation_errors == []
    assert graph.module_by_path(MODULE_PATH_0).content == new_content
    assert result.delta == len(new_content) - mod0.content_size
    # Checksum is valid for the emitted file.
    check = bytearray(out)
    struct.pack_into("<I", check, layout.checksum_offset, 0)
    assert pe_checksum(bytes(check)) == struct.unpack_from("<I", out, layout.checksum_offset)[0]


def test_repack_shrinks_module_on_fixture():
    section, _ = build_payload()
    data = build_pe_fixture(section)
    original = parse_bun_section(section)
    mod0 = original.module_by_path(MODULE_PATH_0)
    new_content = mod0.content[: max(1, mod0.content_size - 4)]
    result = repack_changed_modules(bytes(data), {MODULE_PATH_0: new_content})
    graph = parse_bun_section(_bun_section_bytes(result.output_bytes))
    assert graph.module_by_path(MODULE_PATH_0).content == new_content
    assert graph.validation_errors == []
