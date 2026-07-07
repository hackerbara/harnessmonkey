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
PACKAGE = ROOT / "packages" / "codex-work-drawer"
DRAWER_DOCK = ROOT / "packages" / "drawer-dock"
LIVE_2_1_201 = claude_version_path("2.1.201")
MODULE_PATH = "/$bunfs/root/src/entrypoints/cli.js"
EXPECTED_BINARY_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_BINARY_SIZE = 231708784
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"
EXPECTED_MODULE_LENGTH = 18700756
EXPECTED_OP_IDS = {
    "codex-work-helpers-before-ypr",
    "codex-work-panel-real-target",
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


def test_codex_work_drawer_manifest_targets_local_2_1_201() -> None:
    manifest = manifest_json()
    assert manifest["schemaVersion"] == 1
    assert manifest["kind"] == "patch"
    assert manifest["id"] == "codex-work-drawer"
    assert manifest["label"] == "Codex Work Drawer"
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
    panel = next(op for op in module["operations"] if op["opId"] == "codex-work-panel-real-target")
    assert panel["insertOrder"] == 350
    postconditions = {item["value"] for item in target["postconditions"]}
    assert "function __codexCWDFrame" in postconditions
    assert "function __codexCWDPanel" in postconditions
    if LIVE_2_1_201.exists():
        assert hashlib.sha256(LIVE_2_1_201.read_bytes()).hexdigest() == EXPECTED_BINARY_SHA


def test_codex_work_payloads_are_ascii_safe_and_hashes_match() -> None:
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


def test_codex_work_package_surface_is_public_not_spike_only() -> None:
    manifest = manifest_json()
    readme = read_rel("README.md")
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert manifest["packageVersion"] == "2.1.201-real-target.1"
    assert "spike" not in manifest["packageVersion"].lower()
    assert "spike" not in readme.lower()
    assert "assistant messages" in readme
    assert "clicking toggles expansion" in readme
    assert "codex-work-drawer" in root_readme


def test_codex_work_operations_resolve_once_in_2_1_201_source() -> None:
    source = source_module_text()
    assert source is not None
    module = manifest_json()["patch"]["targets"][0]["modules"][0]
    for op in module["operations"]:
        if op["type"] in {"insert_before", "insert_after"}:
            assert source.count(op["anchor"]) == op.get("expectedAnchorCount", 1), op["opId"]
        else:
            raise AssertionError(op)


def test_codex_work_helper_extracts_assistant_messages_and_expands_omissions(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    home = tmp_path / "home"
    helper = read_rel("payloads/01-codex-work-helpers.js")
    script = f"""
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
process.env.HOME = {str(home)!r};
function Lt() {{ return {str(project)!r}; }}
const realProject = fs.realpathSync({str(project)!r});
const base = path.basename(realProject).replace(/[^a-zA-Z0-9._-]+/g,"-").replace(/^-+|-+$/g,"") || "workspace";
const hash = crypto.createHash("sha256").update(realProject).digest("hex").slice(0,16);
const stateDir = path.join(process.env.HOME, ".claude", "plugins", "data", "codex-openai-codex", "state", `${{base}}-${{hash}}`);
fs.mkdirSync(path.join(stateDir, "jobs"), {{recursive: true}});
const threadId = "thread-abc";
const job = {{id:"job-1",status:"completed",phase:"done",threadId,summary:"demo summary",updatedAt:"2026-07-07T20:00:00.000Z"}};
fs.writeFileSync(path.join(stateDir, "state.json"), JSON.stringify({{jobs:[job]}}));
fs.writeFileSync(path.join(stateDir, "jobs", "job-1.json"), JSON.stringify(job));
const sessionDir = path.join(process.env.HOME, ".codex", "sessions", "2026", "07", "07");
fs.mkdirSync(sessionDir, {{recursive: true}});
const longText = Array.from({{length: 15}}, (_, i) => `line-${{i+1}}`).join("\\n");
fs.writeFileSync(path.join(sessionDir, `rollout-demo-${{threadId}}.jsonl`), [
  JSON.stringify({{timestamp:"2026-07-07T20:00:01.000Z", type:"response_item", payload:{{type:"message", role:"assistant", content:[{{type:"output_text", text:longText}}]}}}}),
  JSON.stringify({{timestamp:"2026-07-07T20:00:02.000Z", type:"response_item", payload:{{type:"function_call", name:"exec_command", arguments:"{{}}"}}}}),
].join("\\n"));
{helper}
let frame = __codexCWDFrame();
if (frame.cardCount !== 1) throw new Error(`card count ${{frame.cardCount}}`);
let card = frame.cards[0];
if (card.kind !== "assistant") throw new Error(card.kind);
if (card.bodyLines.length !== 13) throw new Error(`collapsed lines ${{card.bodyLines.length}}`);
if (!card.bodyLines.at(-1).includes("click to expand")) throw new Error(card.bodyLines.at(-1));
__codexCWDToggleExpanded(card.expandKey);
frame = __codexCWDFrame();
card = frame.cards[0];
if (!card.expanded) throw new Error("not expanded");
if (card.bodyLines.length !== 15) throw new Error(`expanded lines ${{card.bodyLines.length}}`);
console.log(JSON.stringify({{ok:true, title:card.title, lines:card.bodyLines.length}}));
"""
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True)
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_drawer_dock_exposes_codex_work_before_reminders() -> None:
    target_payload = (DRAWER_DOCK / "payloads" / "03-real-drawer-targets.js").read_text(encoding="utf-8")
    status_payload = (DRAWER_DOCK / "payloads" / "09-status-real-drawer-bars.js").read_text(encoding="utf-8")
    overlay_payload = (DRAWER_DOCK / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    assert target_payload.index('FDcWs?.visible&&"codexWork"') < target_payload.index('typeof __codexRMState==="function"&&"reminders"')
    assert "FDdrawerBars=[FDhBar,FDtBar,FDcBar,FDrBar].filter(Boolean)" in status_payload
    assert "children:[n,r,s,o,i,t]" in overlay_payload
