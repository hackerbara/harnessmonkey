import struct
from pathlib import Path

import pytest
from tests.harnessmonkey_binary import win_claude_bin

from harnessmonkey.bun_graph import parse_bun_section
from harnessmonkey.pe import find_pe_layout

FIXTURE_PKG = Path(__file__).parent / "fixtures_win_package"


def test_pe_pipeline_end_to_end(tmp_path):
    src = win_claude_bin()
    if not src.exists():
        pytest.skip(f"missing Windows claude.exe fixture: {src}")
    from scripts.win_spike_driver import build_spike
    out = build_spike(src, FIXTURE_PKG, tmp_path)
    assert out.name == "claude.exe"
    data = out.read_bytes()

    # Structurally valid PE with .bun last-in-file, Authenticode stripped.
    layout = find_pe_layout(data)
    assert layout.security_rva == 0
    assert layout.bun_section.raw_pointer + layout.bun_section.raw_size == len(data)

    # Valid checksum.
    check = bytearray(data)
    struct.pack_into("<I", check, layout.checksum_offset, 0)
    from harnessmonkey.pe import pe_checksum
    assert pe_checksum(bytes(check)) == struct.unpack_from("<I", data, layout.checksum_offset)[0]

    # The real length-changing edit is present and the graph re-parses cleanly.
    declared = struct.unpack_from("<Q", data, layout.bun_section.raw_pointer)[0]
    section = data[layout.bun_section.raw_pointer:layout.bun_section.raw_pointer + 8 + declared]
    graph = parse_bun_section(section)
    assert graph.validation_errors == []
    cli = graph.module_by_path("B:/~BUN/root/src/entrypoints/cli.js")
    assert b"/*__WIN_SPIKE_MARKER__*/" in cli.content
    assert cli.content_size == 18745538 + len(b"/*__WIN_SPIKE_MARKER__*/")
