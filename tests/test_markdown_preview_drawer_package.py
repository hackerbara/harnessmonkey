from __future__ import annotations

import hashlib
import json
import subprocess
import textwrap
from pathlib import Path

from harnessmonkey.builder_v15 import load_manifest_v2
from harnessmonkey.payloads import load_payload_bytes
from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "markdown-preview-drawer"
FOOTER = ROOT / "packages" / "drawer-dock"
LIVE_2_1_201 = claude_version_path("2.1.201")
MODULE_PATH = "/$bunfs/root/src/entrypoints/cli.js"
EXPECTED_BINARY_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_BINARY_SIZE = 231708784
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"
EXPECTED_MODULE_LENGTH = 18700756
EXPECTED_OP_IDS = {
    "mdlp-helpers-before-hyperlink-handler",
    "mdlp-hijack-local-md-hyperlink-open",
    "mdlp-panel-real-overlay",
}


def source_module_text() -> str | None:
    candidates = [
        ROOT / ".development" / "artifacts" / "claude-2.1.201-thinking-text-drawer-source-module0.js",
        ROOT / ".development" / "artifacts" / "claude-2.1.201-framework-source-module0.js",
    ]
    for path in candidates:
        if path.exists():
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == EXPECTED_MODULE_SHA:
                return data.decode("utf-8")
    if not LIVE_2_1_201.exists():
        return None
    from harnessmonkey.bun_graph import parse_bun_section
    from harnessmonkey.macho import find_macho_layout

    raw = LIVE_2_1_201.read_bytes()
    layout = find_macho_layout(raw)
    section = raw[layout.bun_section.offset : layout.bun_section.offset + layout.bun_section.size]
    graph = parse_bun_section(section)
    module = graph.module_by_path(MODULE_PATH)
    return module.content.decode("utf-8")


def read_rel(path: str) -> str:
    return (PACKAGE / path).read_text(encoding="utf-8")


def manifest_json() -> dict:
    return json.loads((PACKAGE / "patch.json").read_text(encoding="utf-8"))


def test_markdown_preview_drawer_manifest_targets_local_2_1_201() -> None:
    manifest = manifest_json()
    assert manifest["schemaVersion"] == 1
    assert manifest["kind"] == "patch"
    assert manifest["id"] == "markdown-preview-drawer"
    assert manifest["label"] == "Markdown Preview Drawer"
    assert manifest["requiresPackages"] == ["drawer-dock"]
    assert manifest["patch"]["engine"] == "bun_graph_repack"
    target = manifest["patch"]["targets"][0]
    assert target["sourceIdentity"] == {
        "claudeVersion": "2.1.201",
        "versionOutput": "2.1.201 (Claude Code)",
        "sha256": EXPECTED_BINARY_SHA,
        "sizeBytes": EXPECTED_BINARY_SIZE,
        "platform": "darwin",
        "arch": "arm64",
    }
    module = target["modules"][0]
    assert module["path"] == MODULE_PATH
    assert module["contentSha256"] == EXPECTED_MODULE_SHA
    assert module["contentLength"] == EXPECTED_MODULE_LENGTH
    assert {op["opId"] for op in module["operations"]} == EXPECTED_OP_IDS
    postconditions = {item["value"] for item in target["postconditions"]}
    assert "function __codexMDLPHandleHyperlink" in postconditions
    assert "function __codexMDLPPanel" in postconditions
    assert "__CODEX_MD_LINK_PREVIEW_DRAWER_FRAME_V1__" in postconditions
    if LIVE_2_1_201.exists():
        assert hashlib.sha256(LIVE_2_1_201.read_bytes()).hexdigest() == EXPECTED_BINARY_SHA


def test_markdown_preview_drawer_payloads_are_ascii_safe_and_hashes_match() -> None:
    manifest = load_manifest_v2(PACKAGE)
    assert manifest.requires_packages == ("drawer-dock",)
    for target in manifest.targets:
        for module in target.modules:
            for operation in module.operations:
                payload = load_payload_bytes(operation.replacement, PACKAGE)
                assert payload
                assert payload.isascii(), operation.op_id
                if operation.replacement.path:
                    path = PACKAGE / operation.replacement.path
                    assert operation.replacement.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_markdown_preview_package_surface_is_not_spike_only() -> None:
    manifest = manifest_json()
    readme = read_rel("README.md")
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert manifest["packageVersion"] == "2.1.201-real-target.1"
    assert "spike" not in manifest["packageVersion"].lower()
    assert "spike" not in readme.lower()
    assert "flat-content" in readme
    assert "flatContent" in readme
    assert "nested" in readme.lower()
    assert "markdown-preview-drawer" in root_readme


def test_markdown_preview_operations_resolve_once_in_2_1_201_source() -> None:
    source = source_module_text()
    assert source is not None
    module = manifest_json()["patch"]["targets"][0]["modules"][0]
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


def run_helper_script(body: str) -> dict:
    helper = read_rel("payloads/01-md-link-preview-helpers.js")
    script = f"""
const fs = require("fs");
const path = require("path");
const os = require("os");
const base = fs.mkdtempSync(path.join(os.tmpdir(), "mdlp-test-"));
function Lt() {{ return base; }}
{helper}
{body}
"""
    result = subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def test_markdown_preview_helper_opens_only_local_markdown_and_caps_preview() -> None:
    result = run_helper_script(
        textwrap.dedent(
            """
            const docs = path.join(base, "docs");
            fs.mkdirSync(docs);
            const rel = path.join(docs, "target.md");
            fs.writeFileSync(rel, "# Target\\nhello from markdown\\n", "utf8");
            const big = path.join(base, "big.md");
            fs.writeFileSync(big, Buffer.alloc(262144 + 17, 0x61));
            const txt = path.join(base, "not-md.txt");
            fs.writeFileSync(txt, "no", "utf8");
            const relativeHandled = __codexMDLPHandleHyperlink("docs/target.md#section");
            const relativeFrame = globalThis.__CODEX_MD_LINK_PREVIEW_DRAWER_FRAME_V1__;
            globalThis.__CODEX_MD_LINK_PREVIEW_DRAWER_OPEN_V1__ = false;
            const webHandled = __codexMDLPHandleHyperlink("https://example.com/readme.md");
            const textHandled = __codexMDLPHandleHyperlink(txt);
            const bigHandled = __codexMDLPHandleHyperlink(big);
            const bigFrame = globalThis.__CODEX_MD_LINK_PREVIEW_DRAWER_FRAME_V1__;
            console.log(JSON.stringify({
              relativeHandled,
              relativeOpen: relativeFrame && relativeFrame.open === true,
              relativePath: relativeFrame && relativeFrame.path,
              relativeLine: relativeFrame && relativeFrame.lines[1],
              relativeHasBlocks: !!(relativeFrame && relativeFrame.blocks),
              webHandled,
              textHandled,
              bigHandled,
              cap: bigFrame && bigFrame.previewBytes,
              truncated: bigFrame && bigFrame.truncated,
              bigTextLength: bigFrame && bigFrame.lines.join("\\n").length
            }));
            """
        )
    )
    assert result["relativeHandled"] is True
    assert result["relativeOpen"] is True
    assert result["relativePath"].endswith("/docs/target.md")
    assert result["relativeLine"] == "hello from markdown"
    assert result["relativeHasBlocks"] is False
    assert result["webHandled"] is False
    assert result["textHandled"] is False
    assert result["bigHandled"] is True
    assert result["cap"] == 262144
    assert result["truncated"] is True
    assert result["bigTextLength"] == 262144


def test_markdown_preview_helper_handles_file_url_errors_inside_panel() -> None:
    result = run_helper_script(
        textwrap.dedent(
            """
            const missing = path.join(base, "missing.md");
            const url = require("url").pathToFileURL(missing).href + "?ignored=1#part";
            const handled = __codexMDLPHandleHyperlink(url);
            const frame = globalThis.__CODEX_MD_LINK_PREVIEW_DRAWER_FRAME_V1__;
            console.log(JSON.stringify({
              handled,
              open: globalThis.__CODEX_MD_LINK_PREVIEW_DRAWER_OPEN_V1__,
              error: frame && frame.error,
              path: frame && frame.path,
              title: frame && frame.title,
              body: frame && frame.lines.join("\\n"),
              hasBlocks: !!(frame && frame.blocks)
            }));
            """
        )
    )
    assert result["handled"] is True
    assert result["open"] is True
    assert result["error"] is True
    assert result["path"].endswith("/missing.md")
    assert "missing.md" in result["title"]
    assert result["hasBlocks"] is False
    assert "Unable to preview" in result["body"]


def test_markdown_preview_hijacks_juf_before_system_opener() -> None:
    hijack = read_rel("payloads/02-md-link-preview-hijack.js")
    assert hijack == "function Juf(e){if(typeof __codexMDLPHandleHyperlink===\"function\"&&__codexMDLPHandleHyperlink(e))return;rPn(e)}"


def test_markdown_preview_panel_uses_footer_drawer_primitives_and_local_keys() -> None:
    panel = read_rel("payloads/03-md-link-preview-panel.js")
    assert "function __codexMDLPPanel" in panel
    assert "__codexFDRenderDrawerPanel" in panel
    assert "flatContent:!0" in panel
    assert "__CODEX_MD_LINK_PREVIEW_DRAWER_OPEN_V1__" in panel
    assert "__CODEX_MD_LINK_PREVIEW_DRAWER_SCROLL_V1__" in panel
    assert "__CODEX_MD_LINK_PREVIEW_DRAWER_VIEWPORT_V1__" in panel
    assert "Go({" in panel
    assert "footer:close" in panel
    assert "footer:up" in panel
    assert "footer:down" in panel
    assert "footer:jumpTop" in panel
    assert "borderStyle:\"single\"" not in panel
    assert "escape" not in panel.lower()


def test_footer_drawers_overlay_optionally_mounts_markdown_preview_panel() -> None:
    payload = (FOOTER / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    assert 'typeof __codexMDLPPanel==="function"?Xd.jsx(__codexMDLPPanel,{})' in payload
    assert "children:[n,r,o,s,t]" in payload


def test_markdown_preview_frame_uses_flat_lines_not_entry_blocks() -> None:
    helper = read_rel("payloads/01-md-link-preview-helpers.js")
    assert "lines:r" in helper
    assert "blocks:[" not in helper
    assert "bodyLines" not in helper


def test_footer_drawers_shared_renderer_has_flat_line_mode() -> None:
    payload = (FOOTER / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    assert "function __codexFDVisibleLines" in payload
    assert "function __codexFDRenderLineList" in payload
    assert "flatContent" in payload
    assert "__codexFDRenderLineList({frame:t,scroll:l,viewport:i,borderColor:r})" in payload
