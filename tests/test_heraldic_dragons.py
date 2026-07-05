from __future__ import annotations

import json
from pathlib import Path

import pytest

from harnessmonkey.builder_v15 import ValidationRequestV15, validate_package
from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "packages" / "heraldic-dragons"
LIVE_SOURCE = claude_version_path("2.1.201")

EXPECTED_SOURCE_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"


def _manifest() -> dict:
    return json.loads((PACKAGE_DIR / "patch.json").read_text())


def _joined_payload_text() -> str:
    manifest = _manifest()
    operations = manifest["patch"]["targets"][0]["modules"][0]["operations"]
    return "\n".join(
        (PACKAGE_DIR / op["replacement"]["path"]).read_text(encoding="utf-8")
        for op in operations
    )


def test_heraldic_dragons_manifest_shape_and_pins():
    manifest = _manifest()
    assert manifest["id"] == "heraldic-dragons"
    assert manifest["schemaVersion"] == 1
    assert manifest["kind"] == "patch"
    assert manifest["patch"]["engine"] == "bun_graph_repack"
    target = manifest["patch"]["targets"][0]
    assert target["requiredEngine"] == "bun_graph_repack"
    assert target["requiredBinaryFormat"] == "bun_standalone_macho64"
    assert target["sourceIdentity"]["sha256"] == EXPECTED_SOURCE_SHA
    assert target["sourceIdentity"]["claudeVersion"] == "2.1.201"
    assert target["manualSmoke"]["required"] is True

    module = target["modules"][0]
    assert module["path"] == "/$bunfs/root/src/entrypoints/cli.js"
    assert module["contentSha256"] == EXPECTED_MODULE_SHA
    assert module["contentLength"] > 0

    operations = module["operations"]
    assert [op["opId"] for op in operations] == [
        "heraldic-dragons-context-frame-helpers-before-vko-2-1-201",
        "heraldic-dragons-center-columns-a-2-1-201",
        "heraldic-dragons-main-window-me-2-1-201",
        "heraldic-dragons-bottom-stack-de-2-1-201",
        "heraldic-dragons-fullscreen-modal-center-fe-2-1-201",
        "heraldic-dragons-qde-bottom-stack-ee-2-1-201",
        "heraldic-dragons-qde-overlay-center-te-2-1-201",
        "heraldic-dragons-fallback-window-v-2-1-201",
    ]
    for op in operations:
        assert op["type"] == "replace_exact"
        assert op["oldRangeSha256"] and op["oldRangeLength"] is not None


def test_heraldic_dragons_payloads_match_hashes_and_are_mojibake_safe():
    manifest = _manifest()
    operations = manifest["patch"]["targets"][0]["modules"][0]["operations"]
    import hashlib
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

    # the scene contract lives entirely in the payloads
    assert "function __CodexHeraldicSpriteSceneV11" in joined
    assert "function __hdCenterProviderV4" in joined
    assert "function __CodexHeraldicMainWindowV4" in joined
    assert "function __CodexHeraldicBottomStackV4" in joined
    assert "__hdResponsiveBreakpointV6=140" in joined
    assert "__hdClipColsV7=2" in joined
    assert "__hdW=__hdArtW-__hdClipColsV7" in joined
    assert "function __hdCropRunsV7" in joined
    assert "function __hdRightWidthV6" in joined
    assert "codex-heraldic-v12-right-responsive" in joined
    assert "codex-heraldic-v12-tower-right-responsive" in joined
    assert "A=__hdCenterColumns(T,f)" in joined
    assert "a=n!==void 0||r!==void 0,l=a?Xd.jsx(t4,{value:i,children:o}):o" in joined
    assert '"ink-raw-ansi"' in joined
    assert "String.fromCharCode(9600)" in joined       # half-block generated at runtime
    assert "String.fromCharCode(27)" in joined         # ESC generated at runtime
    assert "setInterval(()=>setPh" in joined           # fire animation tick
    assert "codex-heraldic-v11-scene" in joined
    assert "codex-heraldic-v12-main-window" in joined
    assert "codex-heraldic-v12-bottom-stack" in joined


def test_heraldic_dragons_center_provider_memoizes_context_values():
    """Regression test for the same class of bug fixed in capybara-onsen
    (see test_capybara_onsen_center_provider_memoizes_context_values).

    heraldic-dragons shares the same __hdCenterProviderV4 pattern: it
    re-provides the app's real `fde` (useTerminalSize) around the main
    window and bottom stack, and still re-provides `t4` (modal/scrollbox)
    for real modal paths. Recreating the value objects on every render meant
    descendants were forced to re-render on heraldic-dragons' own 95ms fire
    animation tick, forever, regardless of user interaction. Memoizing the
    provider values keeps their identity stable across pure animation
    re-renders, so descendants only re-render when the terminal actually
    resizes.
    """
    joined = _joined_payload_text()
    assert "A_.useMemo(()=>({rows:e,columns:t}),[e,t])" in joined
    assert "A_.useMemo(()=>({rows:e,columns:t,scrollRef:n??null,claimScrollBox:r??null}),[e,t,n,r])" in joined
    assert "let s={rows:e,columns:t},i={rows:e,columns:t,scrollRef:n??null,claimScrollBox:r??null}" not in joined


def test_heraldic_dragons_footer_drawer_overlays_are_not_clipped_or_fake_modal():
    """Heraldic shares capy's app-shell provider shape, so keep the same drawer guard."""
    joined = _joined_payload_text()
    assert "Xd.jsx(fde,{value:s,children:Xd.jsx(t4,{value:i,children:o})})" not in joined
    assert "a=n!==void 0||r!==void 0,l=a?Xd.jsx(t4,{value:i,children:o}):o" in joined

    start = joined.index("function __CodexHeraldicBottomStackV4")
    end = joined.index("function __CodexHeraldicModalProviderV4")
    bottom_stack_helper = joined[start:end]
    assert 'overflow:"hidden"' not in bottom_stack_helper


def test_heraldic_dragons_validates_against_live_2_1_201_source():
    if not LIVE_SOURCE.exists():
        pytest.skip(f"local Claude Code 2.1.201 source missing: {LIVE_SOURCE}")
    result = validate_package(
        ValidationRequestV15(
            source_path=LIVE_SOURCE,
            package_dir=PACKAGE_DIR,
            source_version="2.1.201",
            source_version_output="2.1.201 (Claude Code)",
            platform="darwin",
            arch="arm64",
        )
    )
    assert result["ok"] is True, result
    assert result["operationsResolved"]
