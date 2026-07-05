import pytest
from tests.fixtures_bun import build_payload
from tests.fixtures_pe import build_pe_fixture

from harnessmonkey.binary_format import detect_binary_format, locate_bun_section


def test_detect_pe():
    section, _ = build_payload()
    data = build_pe_fixture(section)
    assert detect_binary_format(data) == "pe"


def test_detect_macho():
    from tests.fixtures_bun import build_aligned_macho_fixture
    data, _ = build_aligned_macho_fixture()
    assert detect_binary_format(data) == "macho"


def test_detect_unknown():
    with pytest.raises(ValueError):
        detect_binary_format(b"\x7fELF" + b"\x00" * 100)


def test_locate_bun_section_pe_matches_payload():
    section, _ = build_payload()
    data = build_pe_fixture(section)
    start, length = locate_bun_section(data)
    assert data[start:start + length] == section
