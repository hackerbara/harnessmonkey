from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from harnessmonkey.builder_v15 import BuildRequestV15, build_patchset_v15, load_manifest_v2
from harnessmonkey.payloads import load_payload_bytes
from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "packages" / "reminders-drawer"
FOOTER_DRAWERS_DIR = ROOT / "packages" / "drawer-dock"
LIVE_2_1_201 = claude_version_path("2.1.201")
MODULE_DUMP = ROOT / ".development" / "artifacts" / "claude-2.1.201-framework-source-module0.js"
MODULE_PATH = "/$bunfs/root/src/entrypoints/cli.js"
EXPECTED_SOURCE_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_SOURCE_SIZE = 231708784
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"
EXPECTED_MODULE_LENGTH = 18700756
DENY_FAMILIES = ["todo_reminder", "task_reminder", "tool_search_usage_reminder", "token_usage", "total_tokens_reminder", "budget_usd", "output_token_usage", "hook_success"]


def _load_manifest():
    return load_manifest_v2(PACKAGE_DIR)


def _live_source_or_skip() -> bytes:
    if not LIVE_2_1_201.exists():
        pytest.skip(f"local Claude Code 2.1.201 source missing: {LIVE_2_1_201}")
    source = LIVE_2_1_201.read_bytes()
    actual = hashlib.sha256(source).hexdigest()
    if actual != EXPECTED_SOURCE_SHA:
        pytest.skip(f"live Claude source is not the pinned 2.1.201 target: {actual}")
    return source


def _build(tmp_path: Path, package_dirs: list[Path]):
    return build_patchset_v15(BuildRequestV15(source_path=LIVE_2_1_201, output_dir=tmp_path / "out", package_dirs=package_dirs, source_version="2.1.201", source_version_output="2.1.201 (Claude Code)", platform="darwin", arch="arm64"))


def _rm_payload_texts() -> tuple[str, str, str, str]:
    wrapper = (PACKAGE_DIR / "payloads" / "rm-attachment-wrapper-deny-2.1.201.js").read_text(encoding="utf-8")
    xye = (PACKAGE_DIR / "payloads" / "rm-xye-runtime-filter-2.1.201.js").read_text(encoding="utf-8")
    hook_gate = (PACKAGE_DIR / "payloads" / "rm-hook-success-message-filter-2.1.201.js").read_text(encoding="utf-8")
    panel = (PACKAGE_DIR / "payloads" / "rm-panel-real-target-2.1.201.js").read_text(encoding="utf-8")
    return wrapper, xye, hook_gate, panel


def test_reminders_manager_manifest_loads_package_model_with_valid_payload_hashes():
    manifest = _load_manifest()
    assert manifest.id == "reminders-drawer"
    assert manifest.schema_version == 2
    for target in manifest.targets:
        assert target.required_engine == "bun_graph_repack"
        assert target.required_binary_format == "bun_standalone_macho64"
        assert [module.path for module in target.modules] == [MODULE_PATH]
        for module in target.modules:
            assert module.content_sha256 == EXPECTED_MODULE_SHA
            assert module.content_length == EXPECTED_MODULE_LENGTH
            for operation in module.operations:
                payload = load_payload_bytes(operation.replacement, PACKAGE_DIR)
                assert payload
                assert payload.isascii()


def test_reminders_manager_targets_claude_2_1_201_and_declares_relationships():
    manifest = load_manifest_v2(PACKAGE_DIR)
    target = manifest.targets[0]
    assert target.source_identity.claude_version == "2.1.201"
    assert target.source_identity.version_output == "2.1.201 (Claude Code)"
    assert target.source_identity.sha256 == EXPECTED_SOURCE_SHA
    assert target.source_identity.size_bytes == EXPECTED_SOURCE_SIZE
    assert manifest.requires_packages == ("drawer-dock",)
    assert manifest.conflicts_with_packages == ("mute-reminders",)
    if LIVE_2_1_201.exists():
        assert hashlib.sha256(LIVE_2_1_201.read_bytes()).hexdigest() == EXPECTED_SOURCE_SHA


def test_reminders_manager_operation_anchors_are_unique_in_stock_module_dump():
    if not MODULE_DUMP.exists():
        pytest.skip(f"stock module dump missing: {MODULE_DUMP}")
    dump_bytes = MODULE_DUMP.read_bytes()
    assert hashlib.sha256(dump_bytes).hexdigest() == EXPECTED_MODULE_SHA
    source = dump_bytes.decode("utf-8")
    manifest = _load_manifest()
    for module in manifest.targets[0].modules:
        for operation in module.operations:
            if operation.type == "replace_between":
                assert operation.start_marker is not None, operation.op_id
                assert operation.end_marker is not None, operation.op_id
                assert source.count(operation.start_marker) == operation.expected_start_marker_count, operation.op_id
                assert source.count(operation.end_marker) == operation.expected_end_marker_count, operation.op_id
                start = source.index(operation.start_marker)
                end = source.index(operation.end_marker, start + len(operation.start_marker))
                old = source[start:end]
                assert operation.old_range_length == len(old.encode("utf-8")), operation.op_id
                assert operation.old_range_sha256 == hashlib.sha256(old.encode("utf-8")).hexdigest(), operation.op_id
            elif operation.type in {"insert_before", "insert_after"}:
                assert operation.anchor is not None, operation.op_id
                assert source.count(operation.anchor) == operation.expected_anchor_count, operation.op_id
            elif operation.type == "replace_exact":
                assert operation.exact is not None, operation.op_id
                assert source.count(operation.exact) == 1, operation.op_id
                assert operation.old_range_length == len(operation.exact.encode("utf-8")), operation.op_id
                assert operation.old_range_sha256 == hashlib.sha256(operation.exact.encode("utf-8")).hexdigest(), operation.op_id
            else:
                raise AssertionError(operation)


def test_reminders_manager_uses_spike_wrapper_and_real_target_panel():
    manifest = load_manifest_v2(PACKAGE_DIR)
    op_ids = {op.op_id for target in manifest.targets for module in target.modules for op in module.operations}
    assert {"rm-attachment-wrapper-deny", "rm-xye-runtime-filter", "rm-hook-success-message-filter", "rm-panel-real-target"}.issubset(op_ids)
    assert "rm-register-footer-drawer" not in op_ids
    assert op_ids.isdisjoint({"rm-footer-target-append-2-1-199", "rm-wo-wrap-open-2-1-199", "rm-wo-wrap-close-2-1-199", "rm-footer-space-binding-2-1-199", "rm-bar-segment-2-1-199", "rm-overlay-default-2-1-199", "rm-overlay-bde-2-1-199"})
    wrapper, _, hook_gate, panel = _rm_payload_texts()
    assert 'function __codexRMWrapActions(e,t){if(t!=="reminders")return e' in wrapper
    assert "__CODEX_FOOTER_DRAWERS_V1__" not in wrapper
    assert "function __codexRMRegisterFooterDrawer" not in wrapper + panel
    assert ".register" not in wrapper + panel
    assert "function __codexRMPanel" in panel
    assert "__CODEX_REMINDERS_SELECTED_V1__===!0&&n.open" in panel
    assert "Math.min(8" in wrapper
    assert "!__codexRMDenyAttachment(L.message.attachment)" in hook_gate
    assert "u<9" in panel
    assert "escape" not in panel.lower()

def test_reminders_manager_declares_manual_smoke_for_the_drawer_ui():
    manifest = _load_manifest()
    for target in manifest.targets:
        assert target.manual_smoke.required is True
        assert target.manual_smoke.reason


def test_reminders_manager_deny_payloads_define_expected_state_and_gate_functions():
    wrapper, xye, hook_gate, panel = _rm_payload_texts()
    assert "function __codexRMState(){" in wrapper
    assert "function __codexRMDenyLabel(e)" in wrapper
    assert "function __codexRMDenyAttachment(e)" in wrapper
    assert "globalThis.__CODEX_REMINDERS_MANAGER_V1__" in wrapper
    assert "async function _g(e,t){" in wrapper
    assert "async function*XYe(e,t,n,r,o,s,i,a){" in xye
    assert "!__codexRMDenyAttachment(L.message.attachment)" in hook_gate
    assert "function __codexRMPanel" in panel
    assert "function __codexRMWrapActions" in wrapper
    for family in DENY_FAMILIES:
        assert family in wrapper
    assert '"hook success"' in wrapper


def test_reminders_manager_deny_payloads_gate_before_telemetry_and_attachment_wrapping():
    wrapper, xye, hook_gate, _ = _rm_payload_texts()
    assert wrapper.index("if(__codexRMDenyLabel(e))return[]") < wrapper.index("let n=Date.now()") < wrapper.index("let r=await t()") < wrapper.index('G("tengu_attachment_compute_duration"')
    assert xye.index("l=l.filter((c)=>!__codexRMDenyAttachment(c))") < xye.index("if(l.length===0)return") < xye.index('G("tengu_attachments"') < xye.index("yield ki(c,o)")
    assert hook_gate.index("L.message") < hook_gate.index("!__codexRMDenyAttachment") < hook_gate.index("yield{message:L.message")


def test_reminders_manager_deny_state_defaults_to_all_blocked_and_fails_closed():
    wrapper, _, _, _ = _rm_payload_texts()
    script = "\n".join([wrapper, r'''
if (globalThis.__CODEX_REMINDERS_MANAGER_V1__ !== undefined) throw new Error("test setup: global should start undefined");
let state = __codexRMState();
for (const family of ["todo_reminder","task_reminder","tool_search_usage_reminder","token_usage","total_tokens_reminder","budget_usd","output_token_usage","hook_success"]) {
  if (state.deny[family] !== true) throw new Error("expected default-deny for " + family);
}
if (!__codexRMDenyLabel("todo_reminders")) throw new Error("todo_reminders label should be denied by default");
for (const type of ["todo_reminder","task_reminder","tool_search_usage_reminder","token_usage","total_tokens_reminder","budget_usd","output_token_usage"]) if (!__codexRMDenyAttachment({type})) throw new Error("type should be denied by default: " + type);
if (!__codexRMDenyAttachment({type:"hook_success",content:""})) throw new Error("blank hook_success should be denied by default");
if (__codexRMDenyAttachment({type:"hook_success",content:"OK"})) throw new Error("contentful hook_success should be kept");
for (const type of ["hook_additional_context","critical_system_reminder","plan_mode","memory_update","diagnostics","queued_command"]) if (__codexRMDenyAttachment({type})) throw new Error("unrelated type should never be denied: " + type);
'''])
    result = subprocess.run(["node", "-e", script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr


def test_reminders_manager_blank_hook_success_filter_respects_toggle():
    wrapper, xye, _, _ = _rm_payload_texts()
    script = "\n".join(["let telemetry=[];", "function G(name,payload){telemetry.push({name,payload})}", "function De(value){return JSON.stringify(value)}", "class jM extends Error {}", "function C(){}", "function sr(value){return value}", "function qo(value){return value}", "function He(){}", "function C6(){return undefined}", "let i5l;", "let ki;", wrapper, xye, r'''
(async()=>{
  if (!__codexRMDenyAttachment({type:"hook_success",content:""})) throw new Error("blank hook_success should be denied");
  if (!__codexRMDenyAttachment({type:"hook_success",content:" \n\t"})) throw new Error("whitespace hook_success should be denied");
  if (__codexRMDenyAttachment({type:"hook_success",content:"OK"})) throw new Error("contentful hook_success should be kept");
  i5l = async () => [
    {type:"hook_success",content:""},
    {type:"hook_success",content:"OK"},
    {type:"hook_additional_context",content:["keep"]}
  ];
  ki = (attachment) => ({type:"attachment", attachment});
  let yielded = [];
  for await (const row of XYe(null,null,null,null,null,null,null,null)) yielded.push(row.attachment);
  if (yielded.map((item)=>item.type+":"+item.content).join(",") !== "hook_success:OK,hook_additional_context:keep") throw new Error("blank hook_success filter mismatch: " + JSON.stringify(yielded));
  globalThis.__CODEX_REMINDERS_MANAGER_V1__.deny.hook_success = false;
  if (__codexRMDenyAttachment({type:"hook_success",content:""})) throw new Error("blank hook_success should be kept after toggle");
})().catch((err)=>{console.error(err.stack||err.message); process.exit(1)});
'''])
    result = subprocess.run(["node", "-e", script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr


def test_reminders_manager_shared_todo_reminders_label_gates_only_when_both_rows_denied():
    wrapper, xye, _, _ = _rm_payload_texts()
    script = "\n".join(["let telemetry=[];", "function G(name,payload){telemetry.push({name,payload})}", "function De(value){return JSON.stringify(value)}", "class jM extends Error {}", "function C(){}", "function sr(value){return value}", "function qo(value){return value}", "function He(){}", "function C6(){return undefined}", "let i5l;", "let ki;", wrapper, xye, r'''
(async()=>{
  let genRan = false;
  let dropped = await _g("todo_reminders", async()=>{genRan=true; return [{type:"todo_reminder"},{type:"task_reminder"}]});
  if (genRan) throw new Error("generator should not run while both todo/task are denied");
  if (dropped.length !== 0) throw new Error("gated label should return an empty array");
  globalThis.__CODEX_REMINDERS_MANAGER_V1__.deny.task_reminder = false;
  if (__codexRMDenyLabel("todo_reminders")) throw new Error("shared label must run once one of todo/task is allowed");
  if (!__codexRMDenyAttachment({type:"todo_reminder"})) throw new Error("todo_reminder should still be denied");
  if (__codexRMDenyAttachment({type:"task_reminder"})) throw new Error("task_reminder should now be allowed");
  genRan = false;
  let both = await _g("todo_reminders", async()=>{genRan=true; return [{type:"todo_reminder"},{type:"task_reminder"}]});
  if (!genRan) throw new Error("generator should run once only one of pair is denied");
  if (both.length !== 2) throw new Error("_g itself must not split rows; XYe filters objects");
  i5l = async () => both;
  ki = (attachment) => ({type:"attachment", attachment});
  let yielded = [];
  for await (const row of XYe(null,null,null,null,null,null,null,null)) yielded.push(row.attachment.type);
  if (yielded.join(",") !== "task_reminder") throw new Error("XYe should keep only task_reminder, got: " + yielded.join(","));
  globalThis.__CODEX_REMINDERS_MANAGER_V1__.deny.task_reminder = true;
  if (!__codexRMDenyLabel("todo_reminders")) throw new Error("shared label should be gated again once both rows are denied");
  globalThis.__CODEX_REMINDERS_MANAGER_V1__.deny.token_usage = false;
  if (__codexRMDenyLabel("token_usage")) throw new Error("token_usage label should not be gated once its own flag is false");
  if (__codexRMDenyAttachment({type:"token_usage"})) throw new Error("token_usage type should not be denied once its own flag is false");
})().catch((err)=>{console.error(err.stack||err.message); process.exit(1)});
'''])
    result = subprocess.run(["node", "-e", script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.local_real_smoke
def test_reminders_manager_builds_with_footer_framework(tmp_path):
    _live_source_or_skip()
    report = _build(tmp_path, [FOOTER_DRAWERS_DIR, PACKAGE_DIR])
    assert report.failureReason is None, report.failureReason
    assert report.automatedStatus == "passed"
    assert report.enabledPatches == ["drawer-dock", "reminders-drawer"]
    assert report.status == "verified"
    assert report.manualSmoke["required"] is True
    assert report.manualSmoke["status"] == "bypassed"
    assert report.activationEligible is True


@pytest.mark.local_real_smoke
def test_reminders_manager_conflicts_with_matching_uas_fixture_when_framework_present(tmp_path):
    _live_source_or_skip()
    fixture = tmp_path / "mute-reminders"
    (fixture / "payloads").mkdir(parents=True)
    payload = b"/* unused */\n"
    (fixture / "payloads" / "noop.js").write_bytes(payload)
    manifest = {"schemaVersion": 1, "kind": "patch", "id": "mute-reminders", "label": "UAS Fixture", "description": "relationship fixture", "packageVersion": "2.1.201-fixture", "conflictsWithPackages": ["reminders-drawer"], "patch": {"engine": "bun_graph_repack", "targets": [{"sourceIdentity": {"claudeVersion":"2.1.201","versionOutput":"2.1.201 (Claude Code)","sha256":EXPECTED_SOURCE_SHA,"sizeBytes":EXPECTED_SOURCE_SIZE,"platform":"darwin","arch":"arm64"}, "requiredEngine":"bun_graph_repack", "requiredBinaryFormat":"bun_standalone_macho64", "modules":[{"path":MODULE_PATH,"contentSha256":EXPECTED_MODULE_SHA,"contentLength":EXPECTED_MODULE_LENGTH,"operations":[{"opId":"noop","label":"noop","type":"replace_exact","exact":"__never__","replacement":{"path":"payloads/noop.js","sha256":hashlib.sha256(payload).hexdigest()}}]}], "manualSmoke":{"required":False,"reason":None}}]}}
    (fixture / "patch.json").write_text(json.dumps(manifest))
    report = _build(tmp_path, [FOOTER_DRAWERS_DIR, PACKAGE_DIR, fixture])
    assert report.status == "failed"
    assert report.failureReason is not None
    assert "patch_conflict:package_conflict:reminders-drawer:mute-reminders" in report.failureReason
