from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest

from tests.harnessmonkey_binary import win_claude_bin

from harnessmonkey.builder_v15 import load_manifest_v2

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "packages" / "capybara-onsen-win"

EXPECTED_SOURCE_SHA = "fb804ee019bfbb8d7e85abf965e528e53b5aa5a4e4ebc0f164139dc10a9e0320"
EXPECTED_SOURCE_SIZE = 241591968
EXPECTED_MODULE_PATH = "B:/~BUN/root/src/entrypoints/cli.js"
EXPECTED_MODULE_SHA = "63154b978bb29a873e54fa8a622a5f5bce3b5cd3461cfa926cce010cabced1e2"
EXPECTED_MODULE_LENGTH = 18745538


def _manifest() -> dict:
    return json.loads((PACKAGE_DIR / "patch.json").read_text())


def test_capybara_onsen_win_manifest_shape_and_pins():
    manifest = _manifest()
    assert manifest["schemaVersion"] == 1
    assert manifest["kind"] == "patch"
    assert manifest["id"] == "capybara-onsen-win"
    assert manifest["patch"]["engine"] == "bun_graph_repack"

    targets = manifest["patch"]["targets"]
    assert len(targets) == 1
    target = targets[0]
    assert target["requiredBinaryFormat"] == "bun_standalone_pe64"
    assert target["sourceIdentity"]["platform"] == "win32"
    assert target["sourceIdentity"]["arch"] == "x64"
    assert target["sourceIdentity"]["sha256"] == EXPECTED_SOURCE_SHA
    assert target["sourceIdentity"]["sizeBytes"] == EXPECTED_SOURCE_SIZE

    module = target["modules"][0]
    assert module["path"] == EXPECTED_MODULE_PATH
    assert module["contentSha256"] == EXPECTED_MODULE_SHA
    assert module["contentLength"] == EXPECTED_MODULE_LENGTH

    operations = module["operations"]
    assert len(operations) == 8
    for op in operations:
        assert op["type"] == "replace_exact"
        assert op["oldRangeSha256"]
        assert isinstance(op["oldRangeLength"], int)

    # And the manifest parses cleanly through the real loader used by the builder.
    parsed = load_manifest_v2(PACKAGE_DIR)
    assert parsed.id == "capybara-onsen-win"
    for parsed_target in parsed.targets:
        assert parsed_target.required_binary_format == "bun_standalone_pe64"


def test_capybara_onsen_win_payloads_match_hashes_and_are_mojibake_safe():
    manifest = _manifest()
    operations = manifest["patch"]["targets"][0]["modules"][0]["operations"]
    joined = ""
    for op in operations:
        data = (PACKAGE_DIR / op["replacement"]["path"]).read_bytes()
        assert data, f"empty payload {op['opId']}"
        assert hashlib.sha256(data).hexdigest() == op["replacement"]["sha256"]
        text = data.decode("utf-8")
        # v1 mojibake rule: no literal half-block glyph or ESC byte in source
        assert "▀" not in text, f"literal half-block in {op['opId']}"
        assert "\x1b" not in text, f"literal ESC byte in {op['opId']}"
        joined += "\n" + text

    assert "String.fromCharCode(9600)" in joined  # half-block generated at runtime
    assert "function __coCenterProviderV4" in joined
    assert "__CodexCapyOnsenMainWindowV4" in joined


def test_capybara_onsen_win_builds_against_live_2_1_201_binary(tmp_path):
    src = win_claude_bin()
    if not src.exists():
        pytest.skip(f"missing pinned Windows claude.exe fixture: {src}")

    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from scripts.win_spike_driver import build_spike

    from harnessmonkey.bun_graph import parse_bun_section
    from harnessmonkey.pe import find_pe_layout, pe_checksum

    out = build_spike(src, PACKAGE_DIR, tmp_path)
    assert out.name == "claude.exe"
    data = out.read_bytes()

    # Structurally valid PE: Authenticode stripped, .bun last-in-file.
    layout = find_pe_layout(data)
    assert layout.security_rva == 0
    assert layout.bun_section.raw_pointer + layout.bun_section.raw_size == len(data)

    # Self-consistent checksum.
    check = bytearray(data)
    struct.pack_into("<I", check, layout.checksum_offset, 0)
    assert pe_checksum(bytes(check)) == struct.unpack_from("<I", data, layout.checksum_offset)[0]

    # The repacked .bun section re-parses cleanly.
    declared = struct.unpack_from("<Q", data, layout.bun_section.raw_pointer)[0]
    section = data[layout.bun_section.raw_pointer:layout.bun_section.raw_pointer + 8 + declared]
    graph = parse_bun_section(section)
    assert graph.validation_errors == []

    cli = graph.module_by_path(EXPECTED_MODULE_PATH)
    assert b"__CodexCapyOnsenMainWindowV4" in cli.content
    assert b"function __coCenterProviderV4" in cli.content
