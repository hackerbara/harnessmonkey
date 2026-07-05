from __future__ import annotations

from tests.fixtures_bun import build_macho_fixture

from harnessmonkey.macho import find_macho_layout


def test_find_macho_layout_locates_bun_and_linkedit():
    data, offsets = build_macho_fixture()
    layout = find_macho_layout(data)
    assert layout.bun_segment.fileoff == offsets.bun_fileoff
    assert layout.bun_section.offset == offsets.bun_fileoff
    assert layout.linkedit_segment.fileoff == offsets.linkedit_fileoff
    assert layout.code_signature.dataoff == offsets.code_signature_offset


def test_shift_layout_grows_bun_and_moves_linkedit():
    data, offsets = build_macho_fixture()
    from harnessmonkey.macho import shift_macho_after_bun_change

    shifted, updates = shift_macho_after_bun_change(
        data, insert_abs=offsets.bun_fileoff + 32, delta=64
    )
    layout = find_macho_layout(shifted)
    assert layout.bun_segment.filesize == offsets.bun_size + 64
    assert layout.bun_section.size == offsets.bun_size + 64
    assert layout.linkedit_segment.fileoff == offsets.linkedit_fileoff + 64
    assert layout.code_signature.dataoff == offsets.code_signature_offset + 64
    assert any(item["field"] == "LC_CODE_SIGNATURE.dataoff" for item in updates)
