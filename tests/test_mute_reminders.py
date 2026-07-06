from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from harnessmonkey.bun_graph import parse_bun_section
from harnessmonkey.builder_v15 import ValidationRequestV15, load_manifest_v2, validate_package
from harnessmonkey.macho import find_macho_layout
from harnessmonkey.payloads import load_payload_bytes
from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "packages" / "mute-reminders"
LIVE_2_1_201 = claude_version_path("2.1.201")
MODULE_PATH = "/$bunfs/root/src/entrypoints/cli.js"
EXPECTED_SOURCE_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"

DENIED_LABELS = [
    "todo_reminders",
    "tool_search_usage_reminder",
    "total_tokens_reminder",
    "token_usage",
    "budget_usd",
    "output_token_usage",
]

DENIED_TYPES = [
    "todo_reminder",
    "task_reminder",
    "tool_search_usage_reminder",
    "token_usage",
    "total_tokens_reminder",
    "budget_usd",
    "output_token_usage",
    "hook_success",
]

KEPT_TYPES = [
    "hook_additional_context",
    "hook_blocking_error",
    "hook_stopped_continuation",
    "command_permissions",
    "agent_mention",
    "critical_system_reminder",
    "edited_text_file",
    "opened_file_in_ide",
    "plan_mode",
    "plan_mode_exit",
    "plan_mode_reentry",
    "auto_mode",
    "auto_mode_exit",
    "team_context",
    "memory_update",
    "mcp_instructions_delta",
    "deferred_tools_delta",
    "diagnostics",
    "lsp_diagnostics",
    "queued_command",
    "file_reference",
    "pdf_reference",
    "directory_reference",
]


def _exact_2_1_201_source() -> bytes:
    if not LIVE_2_1_201.exists():
        pytest.skip(f"Claude Code 2.1.201 source missing: {LIVE_2_1_201}")
    source = LIVE_2_1_201.read_bytes()
    actual = hashlib.sha256(source).hexdigest()
    if actual != EXPECTED_SOURCE_SHA:
        pytest.skip(f"live Claude source is not the pinned 2.1.201 target: {actual}")
    return source


def _target_module_text() -> str:
    source = _exact_2_1_201_source()
    layout = find_macho_layout(source)
    section = source[layout.bun_section.offset : layout.bun_section.offset + layout.bun_section.size]
    graph = parse_bun_section(section)
    module = graph.module_by_path(MODULE_PATH)
    assert hashlib.sha256(module.content).hexdigest() == EXPECTED_MODULE_SHA
    return module.content.decode("utf-8")


def _payloads() -> tuple[str, str, str, str]:
    manifest = load_manifest_v2(PACKAGE_DIR)
    target = manifest.targets[0]
    module = target.modules[0]
    payload_texts_by_id = {}
    for operation in module.operations:
        payload_texts_by_id[operation.op_id] = load_payload_bytes(operation.replacement, PACKAGE_DIR).decode("utf-8")
    return (
        payload_texts_by_id["_g-drop-denied-labels-2-1-201"],
        payload_texts_by_id["xye-filter-before-ki-2-1-201"],
        payload_texts_by_id["hook-success-message-filter-2-1-201"],
        "\n".join(payload_texts_by_id.values()),
    )


def test_upstream_attachment_suppression_package_validates_against_real_2_1_199_source():
    _exact_2_1_201_source()
    result = validate_package(
        ValidationRequestV15(
            source_path=LIVE_2_1_201,
            package_dir=PACKAGE_DIR,
            source_version="2.1.201",
            source_version_output="2.1.201 (Claude Code)",
            platform="darwin",
            arch="arm64",
        )
    )
    assert result["ok"] is True, result
    assert result["packageId"] == "mute-reminders"
    assert [item["opId"] for item in result["operationsResolved"]] == [
        "_g-drop-denied-labels-2-1-201",
        "xye-filter-before-ki-2-1-201",
        "hook-success-message-filter-2-1-201",
    ]
    assert result["operationsResolved"][0]["delta"] > 0
    assert result["operationsResolved"][1]["delta"] > 0


def test_upstream_attachment_suppression_payloads_encode_the_policy_and_keep_boundaries():
    ug_payload, xye_payload, hook_payload, all_payload = _payloads()
    assert "function __codexUASDropLabel(e)" in ug_payload
    assert "function __codexUASDropAttachment(e)" in ug_payload
    assert "async function _g(e,t)" in ug_payload
    assert "async function*XYe(e,t,n,r,o,s,i,a)" in xye_payload
    assert "!__codexUASDropAttachment(L.message.attachment)" in hook_payload
    for label in DENIED_LABELS:
        assert label in ug_payload
    for attachment_type in DENIED_TYPES:
        assert attachment_type in ug_payload
    for kept in KEPT_TYPES:
        assert kept not in ug_payload
        assert kept not in xye_payload
    assert "__codexNCHC" not in all_payload
    assert "__CODEX_HIDDEN_CONTEXT_DRAWER" not in all_payload
    assert "function zsr" not in all_payload
    assert "function Jur" not in all_payload


def test_upstream_attachment_suppression_gates_before_compute_telemetry_and_li_wrapping():
    ug_payload, xye_payload, hook_payload, _ = _payloads()
    label_guard = ug_payload.index("if(__codexUASDropLabel(e))return[]")
    start_timer = ug_payload.index("let n=Date.now()")
    await_generator = ug_payload.index("let r=await t()")
    compute_telemetry = ug_payload.index('G("tengu_attachment_compute_duration"')
    assert label_guard < start_timer < await_generator < compute_telemetry

    hze_filter = xye_payload.index("l=l.filter((c)=>!__codexUASDropAttachment(c))")
    hze_empty = xye_payload.index("if(l.length===0)return")
    hze_telemetry = xye_payload.index('G("tengu_attachments"')
    hze_li = xye_payload.index("yield ki(c,o)")
    assert hze_filter < hze_empty < hze_telemetry < hze_li
    assert hook_payload.index("L.message") < hook_payload.index("!__codexUASDropAttachment") < hook_payload.index("yield{message:L.message")


def test_upstream_attachment_suppression_manifest_targets_upstream_only():
    manifest_data = json.loads((PACKAGE_DIR / "patch.json").read_text())
    assert manifest_data["schemaVersion"] == 1
    assert manifest_data["kind"] == "patch"
    assert manifest_data["patch"]["engine"] == "bun_graph_repack"
    manifest = load_manifest_v2(PACKAGE_DIR)
    assert manifest.id == "mute-reminders"
    assert manifest.package_version == "1.0.0"
    assert len(manifest.targets) == 1
    target = manifest.targets[0]
    assert target.required_engine == "bun_graph_repack"
    assert target.required_binary_format == "bun_standalone_macho64"
    assert target.source_identity.claude_version == "2.1.201"
    assert [module.path for module in target.modules] == [MODULE_PATH]
    operations = target.modules[0].operations
    assert [operation.type for operation in operations] == ["replace_between", "replace_between", "replace_exact"]
    assert [operation.start_marker for operation in operations[:2]] == [
        "async function _g(e,t){",
        "async function*XYe(e,t,n,r,o,s,i,a){",
    ]
    assert operations[2].exact == "if(L.message)yield{message:L.message,...W};if(N++,L.systemMessage){"
    forbidden_values = [
        "function zsr(e){",
        "function Ypr(e){",
        "__codexNCHCProjectList",
        "__CODEX_HIDDEN_CONTEXT_DRAWER_FRAME",
    ]
    serialized = json.dumps(manifest_data, sort_keys=True)
    for value in forbidden_values:
        assert value not in serialized


def test_no_direct_denied_family_li_construction_bypasses_hze_in_target_module():
    module = _target_module_text()
    assert module.count("yield ki(c,o)") == 1
    for denied in DENIED_TYPES:
        direct_needles = [
            f'li({{type:"{denied}"',
            f'li({{attachment:{{type:"{denied}"',
            f"li({{type:'{denied}'",
            f"li({{attachment:{{type:'{denied}'",
        ]
        for needle in direct_needles:
            assert needle not in module


def test_upstream_attachment_suppression_fixture_blocks_denied_generators_telemetry_and_rows():
    ug_payload, xye_payload, _, _ = _payloads()
    script = "\n".join(
        [
            "let telemetry=[];",
            "function G(name,payload){telemetry.push({name,payload})}",
            "function De(value){return JSON.stringify(value)}",
            "class jM extends Error {}",
            "function C(){}",
            "function sr(value){return value}",
            "function qo(value){return value}",
            "function He(){}",
            "function C6(){return undefined}",
            "let i5l;",
            "let ki;",
            ug_payload,
            xye_payload,
            r'''
(async()=>{
  for (const label of ["todo_reminders","tool_search_usage_reminder","total_tokens_reminder","token_usage","budget_usd","output_token_usage"]) {
    if (!__codexUASDropLabel(label)) throw new Error("label should be denied: "+label);
  }
  for (const type of ["todo_reminder","task_reminder","tool_search_usage_reminder","token_usage","total_tokens_reminder","budget_usd","output_token_usage"]) {
    if (!__codexUASDropAttachment({type})) throw new Error("type should be denied: "+type);
  }
  if (!__codexUASDropAttachment({type:"hook_success",content:""})) throw new Error("blank hook_success should be denied");
  if (!__codexUASDropAttachment({type:"hook_success",content:" \n\t"})) throw new Error("whitespace hook_success should be denied");
  if (__codexUASDropAttachment({type:"hook_success",content:"OK"})) throw new Error("contentful hook_success should be kept");
  for (const type of ["hook_additional_context","hook_blocking_error","critical_system_reminder","plan_mode","memory_update","diagnostics","queued_command"]) {
    if (__codexUASDropAttachment({type})) throw new Error("type should be kept: "+type);
  }

  let deniedCalled=false;
  let denied=await _g("todo_reminders", async()=>{deniedCalled=true; return [{type:"todo_reminder"}]});
  if (deniedCalled) throw new Error("denied generator should not run");
  if (denied.length !== 0) throw new Error("denied generator should return empty array");
  if (telemetry.length !== 0) throw new Error("denied generator should not emit telemetry");

  Math.random=()=>0;
  let keptCalled=false;
  let kept=await _g("hook_additional_context", async()=>{keptCalled=true; return [{type:"hook_additional_context",content:["keep"]}]});
  if (!keptCalled) throw new Error("kept generator should run");
  if (kept.length !== 1 || kept[0].type !== "hook_additional_context") throw new Error("kept generator result mismatch");
  if (!telemetry.some((item)=>item.name==="tengu_attachment_compute_duration" && item.payload.label==="hook_additional_context")) {
    throw new Error("kept generator telemetry should remain");
  }

  telemetry=[];
  let wrapped=[];
  i5l=async()=>[
    {type:"todo_reminder",content:[]},
    {type:"hook_success",content:""},
    {type:"hook_success",content:"OK"},
    {type:"hook_additional_context",content:["keep"]},
    {type:"token_usage",used:1,total:10,remaining:9}
  ];
  ki=(attachment)=>{wrapped.push(attachment.type); return {type:"attachment",attachment}};
  let yielded=[];
  for await (const row of XYe(null,null,null,null,null,null,null,null)) yielded.push(row);
  if (wrapped.join(",") !== "hook_success,hook_additional_context") throw new Error("denied objects were wrapped by ki: "+wrapped.join(","));
  if (yielded.length !== 2 || yielded[0].attachment.type !== "hook_success" || yielded[0].attachment.content !== "OK" || yielded[1].attachment.type !== "hook_additional_context") throw new Error("yield mismatch");
  let event=telemetry.find((item)=>item.name==="tengu_attachments");
  if (!event) throw new Error("kept XYe attachment telemetry should remain");
  let types=event.payload.attachment_types;
  for (const deniedType of ["todo_reminder","token_usage"]) {
    if (types.includes(deniedType)) throw new Error("denied XYe type reached telemetry: "+deniedType);
  }
  if (types.filter((type)=>type==="hook_success").length !== 1) throw new Error("only contentful hook_success should reach telemetry");
})().catch((err)=>{console.error(err.stack||err.message); process.exit(1)});
''',
        ]
    )
    result = subprocess.run(
        ["node", "-e", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
