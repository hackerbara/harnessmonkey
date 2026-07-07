# ruff: noqa: E501
import hashlib
import json
import subprocess
import textwrap
from pathlib import Path

from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "hidden-context-drawer"
LIVE_2_1_201 = claude_version_path("2.1.201")
EXPECTED_BINARY_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_BINARY_SIZE = 231708784
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"
EXPECTED_MODULE_LENGTH = 18700756
MODULE_DUMP = ROOT / ".development" / "artifacts" / "claude-2.1.201-framework-source-module0.js"


def read_rel(path: str) -> str:
    return (PACKAGE / path).read_text(encoding="utf-8")


def manifest_json() -> dict:
    return json.loads((PACKAGE / "patch.json").read_text(encoding="utf-8"))


def payloads_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted((PACKAGE / "payloads").glob("*.js")))


def test_hidden_context_drawer_targets_claude_2_1_201() -> None:
    manifest = manifest_json()
    target = manifest["patch"]["targets"][0]
    identity = target["sourceIdentity"]
    module = target["modules"][0]
    assert identity == {
        "claudeVersion": "2.1.201",
        "versionOutput": "2.1.201 (Claude Code)",
        "sha256": EXPECTED_BINARY_SHA,
        "sizeBytes": EXPECTED_BINARY_SIZE,
        "platform": "darwin",
        "arch": "arm64",
    }
    assert module["path"] == "/$bunfs/root/src/entrypoints/cli.js"
    assert module["contentSha256"] == EXPECTED_MODULE_SHA
    assert module["contentLength"] == EXPECTED_MODULE_LENGTH
    if LIVE_2_1_201.exists():
        assert hashlib.sha256(LIVE_2_1_201.read_bytes()).hexdigest() == EXPECTED_BINARY_SHA


def test_hidden_context_drawer_real_target_panel_keeps_x_only_contract() -> None:
    manifest = manifest_json()
    assert manifest["requiresPackages"] == ["drawer-dock"]
    ops = manifest["patch"]["targets"][0]["modules"][0]["operations"]
    op_ids = {op["opId"] for op in ops}
    assert {"projection-helpers-before-ypr", "yt-projection-list-drawer-frame", "hidden-context-panel-real-target"}.issubset(op_ids)
    assert "hidden-context-register-footer-drawer" not in op_ids
    helper_op = next(op for op in ops if op["opId"] == "projection-helpers-before-ypr")
    assert helper_op["type"] == "insert_before"
    assert helper_op["anchor"] == "function Ypr(e){"
    assert helper_op["insertOrder"] == 100
    helper_payload = read_rel("payloads/01-projection-helpers-before-ypr-2.1.201.js")
    assert "function Ypr(e){" not in helper_payload
    assert "function Jur(e){" not in helper_payload
    text = payloads_text()
    assert "__codexFDDrawers" not in text
    assert ".register" not in text
    assert 'id:"hiddenContext"' not in text
    assert "__CODEX_FOOTER_DRAWERS_V1__" not in text
    assert "openId" not in text
    assert "inputOwnsEscape" not in text
    assert "escape" not in text.lower()
    panel = read_rel("payloads/17-panel-real-target.js")
    assert "function __codexNCHCPanel" in panel
    assert "__CODEX_HIDDEN_CONTEXT_DRAWER_SELECTED_V13__===!0&&globalThis.__CODEX_HIDDEN_CONTEXT_DRAWER_OPEN_V13__===!0" in panel
    assert "__codexFDRenderDrawerPanel" in panel
    assert 'title:"Hidden Context"' in panel
    assert 'borderColor:"warning"' in panel
    assert 'scrollGlobal:"__CODEX_HIDDEN_CONTEXT_DRAWER_SCROLL_V13__"' in panel
    assert "x closes" not in panel
    assert "lines??" not in panel


def test_hidden_context_frame_exposes_shared_render_blocks() -> None:
    helper = read_rel("payloads/01-projection-helpers-before-ypr-2.1.201.js")
    script = textwrap.dedent(
        f"""
        {helper}
        function assert(cond, msg) {{ if (!cond) throw new Error(msg); }}
        const frame = __codexNCHCDrawerFrameFromList([{{
          type: 'attachment',
          uuid: 'row-1',
          timestamp: '2026-07-05T12:34:56Z',
          attachment: {{
            type: 'hook_additional_context',
            hookName: 'PostToolUse',
            content: ['first hidden line', 'second hidden line']
          }}
        }}]);
        assert(Array.isArray(frame.blocks), 'hidden context frame should expose render blocks');
        assert(frame.blocks.length === 1, 'one hidden context row should produce one box');
        assert(frame.blocks[0].header.includes('PostToolUse hook'), 'block header should preserve hidden context label');
        assert(frame.blocks[0].header.includes('attachment:hook_additional_context'), 'block header should preserve source label');
        assert(frame.blocks[0].bodyLines.some(line => line.includes('first hidden line')), 'block body should contain projection text');
        assert(frame.cardCount === frame.blocks.length, 'cardCount should track shared card blocks');
        assert(frame.blocks[0].key === 'row-1', 'stable card key should preserve attachment identity');
        """
    )
    subprocess.run(["node", "-e", script], check=True)


def test_hidden_context_operations_match_source_and_payload_hashes() -> None:
    source = MODULE_DUMP.read_text(encoding="utf-8") if MODULE_DUMP.exists() else None
    module = manifest_json()["patch"]["targets"][0]["modules"][0]
    for op in module["operations"]:
        payload = PACKAGE / op["replacement"]["path"]
        assert payload.exists(), op["opId"]
        assert payload.read_bytes().isascii(), op["opId"]
        assert op["replacement"]["sha256"] == hashlib.sha256(payload.read_bytes()).hexdigest(), op["opId"]
        if source is None:
            continue
        if op["type"] == "replace_exact":
            exact = op["exact"]
            assert source.count(exact) == 1, op["opId"]
            assert op["oldRangeLength"] == len(exact.encode("utf-8")), op["opId"]
            assert op["oldRangeSha256"] == hashlib.sha256(exact.encode("utf-8")).hexdigest(), op["opId"]
        elif op["type"] in {"insert_before", "insert_after"}:
            assert source.count(op["anchor"]) == op.get("expectedAnchorCount", 1), op["opId"]
        else:
            raise AssertionError(op)


if __name__ == "__main__":
    test_hidden_context_drawer_targets_claude_2_1_201()
    test_hidden_context_drawer_real_target_panel_keeps_x_only_contract()
    test_hidden_context_frame_exposes_shared_render_blocks()
    test_hidden_context_operations_match_source_and_payload_hashes()
    print("hidden-context drawer package checks passed")
