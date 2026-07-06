# ruff: noqa: E501
import hashlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "thinking-drawer"
LIVE_2_1_201 = claude_version_path("2.1.201")

EXPECTED_BINARY_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_BINARY_SIZE = 231708784
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"
EXPECTED_MODULE_LENGTH = 18700756
EXPECTED_OPERATION_IDS = {
    "thinking-helpers-before-ypr",
    "thinking-message-start-turn-collector",
    "thinking-message-stop-turn-collector",
    "thinking-live-delta-collector",
    "thinking-signature-collector",
    "thinking-parent-structured-collector",
    "thinking-system-token-estimate",
    "thinking-cancel-salvage-collector",
    "thinking-panel-real-target",
}


def source_module_text() -> str | None:
    source_path = ROOT / ".development" / "artifacts" / "claude-2.1.201-thinking-drawer-source-module0.js"
    if source_path.exists():
        return source_path.read_text(encoding="utf-8")
    if not LIVE_2_1_201.exists():
        return None
    sys.path.insert(0, str(ROOT / "src"))
    from harnessmonkey.bun_graph import parse_bun_section
    from harnessmonkey.macho import find_macho_layout

    raw = LIVE_2_1_201.read_bytes()
    layout = find_macho_layout(raw)
    section = raw[layout.bun_section.offset : layout.bun_section.offset + layout.bun_section.size]
    graph = parse_bun_section(section)
    module = graph.module_by_path("/$bunfs/root/src/entrypoints/cli.js")
    return module.content.decode("utf-8")


def read_rel(path: str) -> str:
    return (PACKAGE / path).read_text(encoding="utf-8")


def payloads_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted((PACKAGE / "payloads").glob("*.js")))


def manifest_json() -> dict:
    return json.loads((PACKAGE / "patch.json").read_text(encoding="utf-8"))


def patch_targets() -> list[dict]:
    manifest = manifest_json()
    return manifest["patch"]["targets"]


def test_thinking_text_drawer_payload_ui_literals_are_ascii_safe() -> None:
    offenders = []
    for path in sorted((PACKAGE / "payloads").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(ord(ch) > 127 for ch in line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}:{line!r}")

    assert offenders == []


def test_thinking_text_drawer_is_v3_patch_package() -> None:
    manifest = manifest_json()

    assert manifest["schemaVersion"] == 1
    assert manifest["kind"] == "patch"
    assert manifest["id"] == "thinking-drawer"
    assert manifest["label"] == "Thinking Drawer"
    assert manifest["patch"]["engine"] == "bun_graph_repack"

    sys.path.insert(0, str(ROOT / "src"))
    from harnessmonkey.builder_v15 import load_manifest_v2
    from harnessmonkey.package_model import PackageKind, load_package_manifest

    loaded = load_package_manifest(PACKAGE, PackageKind.PATCH)
    assert loaded.id == "thinking-drawer"
    assert loaded.patch is not None
    assert loaded.patch.engine == "bun_graph_repack"
    assert len(loaded.patch.targets) == 1

    bridged = load_manifest_v2(PACKAGE)
    assert bridged.id == "thinking-drawer"
    assert len(bridged.targets[0].modules[0].operations) == len(EXPECTED_OPERATION_IDS)
    assert bridged.requires_packages == ("drawer-dock",)


def test_thinking_text_drawer_targets_claude_2_1_201() -> None:
    target = patch_targets()[0]
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
    assert {op["opId"] for op in module["operations"]} == EXPECTED_OPERATION_IDS
    assert len(module["operations"]) == len(EXPECTED_OPERATION_IDS)
    postcondition_values = {item["value"] for item in target["postconditions"]}
    for value in [
        "__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__",
        "__CODEX_THINKING_TEXT_DRAWER_TURN_V1__",
        "No thinking captured yet",
        "__codexTTDRecordLiveThinking",
        "__codexTTDRecordStructuredThinking",
        "__codexTTDRecordSalvagedThinking",
        "__codexTTDRecordThinkingSignature",
        "__codexTTDRecordThinkingEstimate",
        "__codexTTDRecordRedactedThinking",
        "function __codexTTDPanel",
    ]:
        assert value in postcondition_values

    if LIVE_2_1_201.exists():
        assert hashlib.sha256(LIVE_2_1_201.read_bytes()).hexdigest() == EXPECTED_BINARY_SHA


def test_manifest_operations_match_source_and_payload_hashes() -> None:
    module = patch_targets()[0]["modules"][0]
    source = source_module_text()
    if source is not None:
        for op in module["operations"]:
            if op["type"] == "replace_exact":
                exact = op["exact"]
                assert source.count(exact) == 1, op["opId"]
                assert op["oldRangeLength"] == len(exact.encode("utf-8")), op["opId"]
                assert op["oldRangeSha256"] == hashlib.sha256(exact.encode("utf-8")).hexdigest(), op["opId"]
            elif op["type"] in {"insert_before", "insert_after"}:
                assert source.count(op["anchor"]) == op.get("expectedAnchorCount", 1), op["opId"]
            else:
                raise AssertionError(op)
    for op in module["operations"]:
        payload = PACKAGE / op["replacement"]["path"]
        assert payload.exists(), op["opId"]
        assert op["replacement"]["sha256"] == hashlib.sha256(payload.read_bytes()).hexdigest(), op["opId"]


def test_thinking_text_drawer_is_real_target_panel_extension() -> None:
    manifest = manifest_json()
    assert manifest["requiresPackages"] == ["drawer-dock"]
    op_ids = {op["opId"] for op in patch_targets()[0]["modules"][0]["operations"]}
    assert op_ids.isdisjoint({
        "thinking-footer-open-state",
        "thinking-footer-target",
        "thinking-footer-selection-flag",
        "thinking-footer-action-wrap-open",
        "thinking-footer-action-wrap-close",
        "thinking-selected-overlay-globals",
        "thinking-bottom-overlay-renderer",
        "thinking-footer-status-bar",
        "thinking-register-footer-drawer",
    })
    helper_op = next(op for op in patch_targets()[0]["modules"][0]["operations"] if op["opId"] == "thinking-helpers-before-ypr")
    assert helper_op["type"] == "insert_before"
    assert helper_op["anchor"] == "function Ypr(e){"
    assert helper_op["insertOrder"] == 200
    helpers = read_rel("payloads/01-thinking-text-helpers.js")
    assert "function Ypr(e){" not in helpers
    assert "__codexTTDWrapFooterActions" not in helpers
    assert "__CODEX_FOOTER_DRAWERS_V1__" not in helpers
    assert "openId" not in helpers
    panel = read_rel("payloads/17-panel-real-target.js")
    assert "function __codexTTDPanel" in panel
    assert "__CODEX_THINKING_TEXT_DRAWER_SELECTED_V1__===!0&&globalThis.__CODEX_THINKING_TEXT_DRAWER_OPEN_V1__===!0" in panel
    assert "__codexFDRenderDrawerPanel" in panel
    assert "escape" not in panel.lower()

def test_thinking_text_drawer_panel_and_docs_remain_display_only() -> None:
    text = read_rel("README.md") + "\n" + payloads_text()
    panel = read_rel("payloads/17-panel-real-target.js")
    assert "No thinking captured yet" in text
    assert "request assembly" in read_rel("README.md")
    assert "JSONL" in read_rel("README.md")
    assert "main chat" in read_rel("README.md")
    assert "transcript" in read_rel("README.md")
    assert "model-visible" in read_rel("README.md")
    assert "Thinking is a real footer target extension" in read_rel("README.md")
    assert 'id:"thinking"' not in text
    assert "available:()=>!0" not in text
    assert "__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__" in text
    assert "__CODEX_THINKING_TEXT_DRAWER_OPEN_V1__" in text
    assert "__codexFDRenderDrawerPanel" in panel
    assert "escape" not in panel.lower()

def test_thinking_text_drawer_collectors_cover_required_sources() -> None:
    helpers = read_rel("payloads/01-thinking-text-helpers.js")
    assert "__codexTTDRecordStructuredThinking" in helpers
    assert "__codexTTDRecordLiveThinking" in helpers
    assert "__codexTTDRecordSalvagedThinking" in helpers
    assert "__codexTTDRecordThinkingSignature" in helpers
    assert "__codexTTDRecordThinkingEstimate" in helpers
    assert "preserve both" in helpers
    assert "slice(0,80)" not in helpers
    assert "Levenshtein" not in helpers


def test_structured_collection_runs_before_ctrl_o_guard() -> None:
    structured = read_rel("payloads/04-structured-thinking-block-collector.js")
    assert "__codexTTDScanAssistantMessage(n)" in structured
    assert "n.message.content.map(I)" in structured
    assert "if(!p&&!i)return null" not in structured
    assert "case\"thinking\"" not in structured
    helpers = read_rel("payloads/01-thinking-text-helpers.js")
    assert "function __codexTTDScanAssistantMessage" in helpers
    assert "__codexTTDRecordRedactedThinking" in helpers
    assert "__codexTTDRecordStructuredThinking" in helpers
    assert "blockIndex:o" in helpers
    assert "blockIndex:r" not in helpers


def test_helper_fixture_merge_and_actual_text_only_sources() -> None:
    helper = read_rel("payloads/01-thinking-text-helpers.js")
    helper_prefix = helper
    script = textwrap.dedent(
        f"""
        {helper_prefix}
        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        __codexTTDRecordLiveThinking({{text:'abc', streamKey:'s1', turnKey:'turn'}});
        __codexTTDRecordLiveThinking({{text:'def', streamKey:'s1', turnKey:'turn'}});
        __codexTTDRecordStructuredThinking({{thinking:'abcdef finalized', messageId:'m1', blockHash:'h1', turnKey:'turn'}});
        __codexTTDRecordSalvagedThinking({{thinking:'interrupted salvage text', messageId:'cancel-1'}});
        __codexTTDRecordRedactedThinking({{messageId:'m2', blockHash:'r1'}});
        __codexTTDRecordThinkingSignature({{chars:128, streamKey:'s1'}});
        __codexTTDRecordThinkingEstimate({{estimatedTokensDelta:7, estimatedTokens:21, streamKey:'s1'}});
        __codexTTDScanAssistantMessage({{uuid:'u1', requestId:'req', timestamp:123, message:{{id:'mid', content:[{{type:'thinking', thinking:'parent text'}}, {{type:'redacted_thinking'}}]}}}});
        const frame = __codexTTDDrawerFrame();
        if (!frame.entries.some(e => e.source === 'structured' && e.sources.includes('live') && e.text === 'abcdef finalized')) throw new Error('structured/live merge failed');
        if (!frame.entries.some(e => e.source === 'structured' && e.text === 'parent text')) throw new Error('parent structured missing');
        if (!frame.entries.some(e => e.source === 'salvaged' && e.text === 'interrupted salvage text')) throw new Error('salvaged thinking missing');
        if (frame.entries.some(e => ['redacted','signature','estimate'].includes(e.source))) throw new Error('secondary progress markers should not create drawer rows');
        if (frame.entries.some(e => e.status === 'secondary')) throw new Error('secondary status rows should not be shown');
        if (frame.entries.length !== 3) throw new Error('drawer should contain only captured thinking text entries');
        if (!Array.isArray(frame.lines) || !Array.isArray(frame.lineKinds)) throw new Error('drawer frame should expose hidden-context-style lines');
        if (!frame.lines.some(line => line.includes('Structured thinking'))) throw new Error('structured header line missing');
        if (frame.lines.some((line, idx) => frame.lineKinds[idx] === 'header' && (line.includes('provisional') || line.includes('final')))) throw new Error('drawer headers should not expose progress/finality statuses');
        if (!frame.lineKinds.includes('header') || !frame.lineKinds.includes('body')) throw new Error('line kinds missing');
        """
    )
    subprocess.run(["node", "-e", script], check=True)



def test_thinking_text_drawer_panel_uses_shared_boxed_drawer_renderer() -> None:
    panel = read_rel("payloads/17-panel-real-target.js")
    helpers = read_rel("payloads/01-thinking-text-helpers.js")

    assert "blocks:" in helpers
    assert "__codexTTDFrameBlocks" in helpers
    assert "function __codexTTDVisibleBlocks" not in helpers
    assert "__codexFDRenderDrawerPanel" in panel
    assert 'title:"Thinking"' in panel
    assert 'borderColor:"permission"' in panel
    assert 'scrollGlobal:"__CODEX_THINKING_TEXT_DRAWER_SCROLL_V1__"' in panel
    assert 'viewportGlobal:"__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__"' in panel
    assert 'borderStyle:"single"' not in panel
    assert "__codexTTDVisibleBlocks" not in panel
    assert "r?.lines??" not in panel


def test_helper_fixture_exposes_box_blocks_for_rendering() -> None:
    helper = read_rel("payloads/01-thinking-text-helpers.js")
    script = textwrap.dedent(
        f"""
        {helper}
        function assert(cond, msg) {{ if (!cond) throw new Error(msg); }}
        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        __codexTTDRecordStructuredThinking({{thinking:`alpha\nbeta`, messageId:'m1', blockHash:'h1'}});
        __codexTTDRecordSalvagedThinking({{thinking:'gamma', messageId:'m2', blockHash:'h2'}});
        const frame = __codexTTDDrawerFrame();
        assert(Array.isArray(frame.blocks), 'drawer frame should expose render blocks');
        assert(frame.blocks.length === 2, 'two thinking entries should produce two boxes');
        assert(frame.blocks.every(b => Array.isArray(b.bodyLines)), 'blocks should carry body lines');
        assert(frame.blocks.every(b => b.header && b.key), 'blocks should carry stable key and header');
        assert(frame.lineCount >= frame.blocks.reduce((n, b) => n + b.bodyLines.length + 3, 0), 'lineCount should include box border/header overhead');
        assert(frame.blocks[0].bodyLines.length === 1, 'chunked body should normalize wrapped text lines');
        """
    )
    subprocess.run(["node", "-e", script], check=True)

def test_secondary_marker_strings_are_not_drawer_content() -> None:
    text = payloads_text()
    assert "[redacted thinking block present]" not in text
    assert "thinking signature received" not in text
    assert "thinking active; raw text not exposed" not in text
    assert "estimated tokens" not in read_rel("payloads/01-thinking-text-helpers.js")


def test_operations_stay_out_of_request_and_persistence_surfaces() -> None:
    op_ids = {op["opId"] for op in patch_targets()[0]["modules"][0]["operations"]}
    assert op_ids == EXPECTED_OPERATION_IDS
    forbidden_op_fragments = ["request-assembly", "jsonl", "transcript-persist", "prompt-context"]
    for op_id in op_ids:
        assert not any(fragment in op_id for fragment in forbidden_op_fragments), op_id
    payload_text = payloads_text()
    assert "messages.push" not in payload_text
    assert "appendFile" not in payload_text
    assert "writeFile" not in payload_text
    assert "transcript" not in payload_text.lower()


def test_helper_fixture_review_regressions() -> None:
    helper = read_rel("payloads/01-thinking-text-helpers.js")
    helper_prefix = helper
    script = textwrap.dedent(
        f"""
        {helper_prefix}
        function assert(cond, msg) {{ if (!cond) throw new Error(msg); }}

        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        __codexTTDBeginTurn('turn-a');
        __codexTTDRecordLiveThinking({{text:'first', streamKey:0}});
        __codexTTDEndTurn();
        __codexTTDBeginTurn('turn-b');
        __codexTTDRecordLiveThinking({{text:'second', streamKey:0}});
        let frame = __codexTTDDrawerFrame();
        assert(frame.entries.filter(e => e.source === 'live').length === 2, 'live deltas from separate turns must not merge');
        assert(frame.entries.some(e => e.turnKey === 'turn-a'), 'turn-a missing');
        assert(frame.entries.some(e => e.turnKey === 'turn-b'), 'turn-b missing');

        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        __codexTTDBeginTurn('msg-1');
        __codexTTDRecordLiveThinking({{text:'abc', streamKey:0}});
        __codexTTDRecordStructuredThinking({{thinking:'abcdef final', messageId:'msg-1', requestId:'req-1', blockHash:'h-msg'}});
        frame = __codexTTDDrawerFrame();
        assert(frame.entries.length === 1, 'live and structured for same message should merge even when requestId exists');
        assert(frame.entries[0].source === 'structured' && frame.entries[0].sources.includes('live'), 'merged entry should preserve live provenance');
        assert(frame.entries[0].messageId === 'msg-1', 'merged entry should keep assistant message id');

        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        __codexTTDRecordLiveThinking({{text:'partial', streamKey:'s1', turnKey:'turn'}});
        __codexTTDRecordStructuredThinking({{thinking:'different final', messageId:'m1', blockHash:'h1', turnKey:'turn'}});
        frame = __codexTTDDrawerFrame();
        assert(frame.entries.some(e => e.source === 'live' && e.text === 'partial'), 'mismatched live text should remain');
        assert(frame.entries.some(e => e.source === 'structured' && e.text === 'different final'), 'mismatched structured text should remain');

        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        __codexTTDRecordLiveThinking({{text:'', streamKey:'s1'}});
        __codexTTDRecordStructuredThinking({{thinking:'   ', messageId:'m1'}});
        assert(__codexTTDDrawerFrame().entries.length === 0, 'empty thinking strings should not create rows');

        const longText = 'x'.repeat(50000);
        __codexTTDRecordStructuredThinking({{thinking:longText, messageId:'long', blockHash:'long-h', turnKey:'long-turn'}});
        frame = __codexTTDDrawerFrame();
        const longEntry = frame.entries.find(e => e.messageId === 'long');
        assert(longEntry.text.includes('captured text truncated') || longEntry.lines.some(l => l.includes('displayed text truncated')), 'long rendered text should label truncation');
        assert(longEntry.charCount >= 50000 && longEntry.rawCharCount >= 50000, 'long entry should track original char count');
        assert(longEntry.fullText.length === 50000, 'long entry should preserve full captured text in frame metadata');
        assert((longEntry.text.length || 0) < longEntry.rawCharCount, 'long stored display text should be bounded');

        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        __codexTTDBeginTurn('long-live');
        for (let i = 0; i < 10; i++) __codexTTDRecordLiveThinking({{text:'y'.repeat(10000), streamKey:1}});
        frame = __codexTTDDrawerFrame();
        const liveLong = frame.entries.find(e => e.source === 'live');
        assert(liveLong.rawCharCount === 100000 && liveLong.charCount === 100000, 'long live raw char count should remain accurate');
        assert(liveLong.fullText.length === 100000, 'long live fullText should preserve all chunks');
        assert(liveLong.text.length < liveLong.rawCharCount, 'long live display text should be bounded');
        assert(frame.droppedCharCount === liveLong.droppedCharCount, 'frame droppedCharCount should not double-count repeated live upserts');
        __codexTTDRecordStructuredThinking({{thinking:'y'.repeat(100000) + ' final', messageId:'long-live', requestId:'req-long'}});
        frame = __codexTTDDrawerFrame();
        assert(frame.entries.length === 1, 'long live and final structured thinking for same message should merge');
        assert(frame.entries[0].source === 'structured' && frame.entries[0].sources.includes('live'), 'long merge should preserve live provenance');
        assert(frame.entries[0].rawCharCount === 100006, 'merged long structured char count should be accurate');
        assert(frame.entries[0].fullText.length === 100006, 'merged long structured fullText should be preserved');

        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        for (let i = 0; i < 100; i++) __codexTTDRecordStructuredThinking({{thinking:'entry-' + i, messageId:'m' + i, blockHash:'h' + i}});
        frame = __codexTTDDrawerFrame();
        assert(__codexTTDEnsure().entries.length <= 80, 'stored entries should be capped');
        assert(frame.droppedEntryCount >= 20, 'dropped entry count should be tracked');

        globalThis.__CODEX_THINKING_TEXT_DRAWER_OPEN_V1__ = true;
        __codexTTDMarkRead();
        assert(__codexTTDDrawerFrame().unread === false, 'opening drawer should clear unread');
        __codexTTDClampScroll(999, __codexTTDDrawerFrame().lineCount, globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__);
        frame = __codexTTDDrawerFrame();
        assert(frame.scroll <= Math.max(0, frame.lineCount - 18), 'scroll should clamp to available content');
        const maxViewport4 = Math.max(0, frame.lineCount - 4);
        __codexTTDClampScroll(999, frame.lineCount, 4);
        frame = __codexTTDDrawerFrame();
        assert(frame.scroll === maxViewport4, 'frame refresh should preserve supplied drawer viewport bottom');
        globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__ = 4;
        frame = __codexTTDDrawerFrame();
        assert(frame.scroll === maxViewport4, 'frame refresh with stored viewport should not reclamp to default height');
        __codexTTDClampScroll(0, frame.lineCount, 4);
        __codexTTDClampScroll(999, frame.lineCount, globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__);
        frame = __codexTTDDrawerFrame();
        assert(frame.scroll === maxViewport4, 'footer down should honor stored viewport height');

        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__ = 4;
        __codexTTDRecordStructuredThinking({{thinking:Array.from({{length:95}}, (_, i) => 'base line ' + i).join('\\n'), messageId:'scroll-base', blockHash:'scroll-base'}});
        frame = __codexTTDDrawerFrame();
        __codexTTDClampScroll(999, frame.lineCount, 4);
        frame = __codexTTDDrawerFrame();
        assert(frame.scroll === Math.max(0, frame.lineCount - 4), 'setup should reach dynamic bottom');
        __codexTTDRecordStructuredThinking({{thinking:Array.from({{length:100}}, (_, i) => 'updated line ' + i).join('\\n'), messageId:'scroll-base', blockHash:'scroll-base'}});
        frame = __codexTTDDrawerFrame();
        assert(frame.scroll === Math.max(0, frame.lineCount - 4), 'structured update at dynamic bottom should stay at dynamic bottom');
        __codexTTDRecordStructuredThinking({{thinking:Array.from({{length:12}}, (_, i) => 'new line ' + i).join('\\n'), messageId:'scroll-new', blockHash:'scroll-new'}});
        frame = __codexTTDDrawerFrame();
        assert(frame.scroll === Math.max(0, frame.lineCount - 4), 'new entry at dynamic bottom should stay at dynamic bottom');
        globalThis.__CODEX_THINKING_TEXT_DRAWER_OPEN_V1__ = false;
        assert(__codexTTDIsOpen() === false, 'framework helper should report closed Thinking');
        """
    )
    subprocess.run(["node", "-e", script], check=True)


if __name__ == "__main__":
    test_thinking_text_drawer_is_v3_patch_package()
    test_thinking_text_drawer_payload_ui_literals_are_ascii_safe()
    test_thinking_text_drawer_targets_claude_2_1_201()
    test_thinking_text_drawer_is_real_target_panel_extension()
    test_thinking_text_drawer_panel_and_docs_remain_display_only()
    test_thinking_text_drawer_collectors_cover_required_sources()
    test_structured_collection_runs_before_ctrl_o_guard()
    test_helper_fixture_merge_and_actual_text_only_sources()
    test_secondary_marker_strings_are_not_drawer_content()
    test_manifest_operations_match_source_and_payload_hashes()
    test_operations_stay_out_of_request_and_persistence_surfaces()
    test_helper_fixture_review_regressions()
    print("thinking drawer package checks passed")
