# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from tests.harnessmonkey_binary import claude_bin_candidates, claude_version_path

from harnessmonkey.builder_v15 import ValidationRequestV15, load_manifest_v2, validate_package
from harnessmonkey.payloads import load_payload_bytes

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = [
    ROOT / "packages" / "capybara-onsen",
    ROOT / "packages" / "heraldic-dragons",
    ROOT / "packages" / "fable-fallback",
    ROOT / "packages" / "hidden-context-drawer",
    ROOT / "packages" / "hidden-context-inline",
    ROOT / "packages" / "reminders-drawer",
    ROOT / "packages" / "mute-reminders",
    ROOT / "packages" / "thinking-drawer",
    ROOT / "packages" / "drawer-dock",
]


def source_for_identity(identity) -> Path | None:
    candidates = [
        Path.home() / ".harnessmonkey" / "sources" / identity.sha256 / "claude",
        *claude_bin_candidates(),
        claude_version_path(identity.claude_version),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        if hashlib.sha256(candidate.read_bytes()).hexdigest() == identity.sha256:
            return candidate
    return None


def test_reference_packages_are_v3_schema_with_v15_compatible_targets():
    for package_dir in PACKAGE_DIRS:
        manifest_data = json.loads((package_dir / "patch.json").read_text())
        assert manifest_data["schemaVersion"] == 1
        assert manifest_data["kind"] == "patch"
        assert "label" in manifest_data
        assert manifest_data["patch"]["engine"] == "bun_graph_repack"
        manifest = load_manifest_v2(package_dir)
        assert manifest.id == package_dir.name
        assert manifest.schema_version == 2
        for target in manifest.targets:
            assert target.required_engine == "bun_graph_repack"
            assert target.required_binary_format == "bun_standalone_macho64"
            assert [module.path for module in target.modules] == [
                "/$bunfs/root/src/entrypoints/cli.js"
            ]
            for module in target.modules:
                assert module.content_sha256
                assert module.content_length > 0
                for operation in module.operations:
                    if operation.type in ("insert_before", "insert_after"):
                        # Structured-splice insertions carry an anchor instead of
                        # old-range evidence (old-range fields are disallowed for
                        # these operation types, see manifest_v2._validate_operation_shape).
                        assert operation.anchor
                    else:
                        assert operation.old_range_sha256
                        assert operation.old_range_length is not None
                    payload = load_payload_bytes(operation.replacement, package_dir)
                    assert payload


def test_reference_packages_validate_against_current_pinned_source():
    for package_dir in PACKAGE_DIRS:
        manifest = load_manifest_v2(package_dir)
        identity = manifest.targets[0].source_identity
        source = source_for_identity(identity)
        if source is None:
            pytest.skip(f"local Claude Code source missing for sha {identity.sha256}")
        result = validate_package(
            ValidationRequestV15(
                source_path=source,
                package_dir=package_dir,
                source_version=identity.claude_version,
                source_version_output=identity.version_output,
                platform=identity.platform,
                arch=identity.arch,
            )
        )
        assert result["ok"] is True, result
        assert result["packageId"] == package_dir.name
        assert result["operationsResolved"]


def test_fable_resume_metadata_payload_uses_ascii_escapes_for_terminal_rendering():
    payload_path = (
        ROOT / "packages" / "fable-fallback" / "payloads" / "net-metadata-formatter.js"
    )
    payload = payload_path.read_bytes()
    assert b"\xc2\xb7" not in payload
    assert b"\\xB7" in payload
    assert b"\\x1b[33mFable classifier triggered\\x1b[39m" in payload


def test_normal_channel_hidden_context_projects_hidden_attachments_before_filtering():
    package_dir = ROOT / "packages" / "hidden-context-inline"
    helper_payload = (package_dir / "payloads" / "projection-helpers-before-jlr.js").read_text()
    helper_payload_199 = (
        package_dir / "payloads" / "projection-helpers-before-jur.js"
    ).read_text()
    filter_payload = (package_dir / "payloads" / "project-before-hidden-filter.js").read_text()
    filter_payload_199 = (
        package_dir / "payloads" / "project-before-hidden-filter-2.1.199.js"
    ).read_text()

    for helper in (helper_payload, helper_payload_199):
        assert "function __codexNCHCProjectAttachment(e)" in helper
        assert "function __codexNCHCProjectList(e)" in helper
        assert 'type:"system",subtype:"codex_hidden_context",level:"warning"' in helper
        assert 'content:"[model context] "+t' in helper
    assert "function Jlr(e){" in helper_payload
    assert "function Jur(e){" in helper_payload_199
    assert "Yt=__codexNCHCProjectList(Yt)" in filter_payload
    assert '.filter((Rt)=>Rt.type!=="progress").filter((Rt)=>!Jlr(Rt))' in filter_payload
    assert "Jt=__codexNCHCProjectList(Jt)" in filter_payload_199
    assert '.filter((cr)=>cr.type!=="progress").filter((cr)=>!Jur(cr))' in filter_payload_199


def test_normal_channel_hidden_context_projection_payload_handles_known_records():
    package_dir = ROOT / "packages" / "hidden-context-inline"
    helper_payload = (package_dir / "payloads" / "projection-helpers-before-jlr.js").read_text()
    helper_block = helper_payload.removesuffix("function Jlr(e){\n").removesuffix(
        "function Jlr(e){"
    )
    script = f"""
{helper_block}
const rows = [
  {{
    type: "attachment",
    uuid: "hook-row",
    timestamp: "2026-07-02T22:13:14.365Z",
    sessionId: "session",
    parentUuid: "parent",
    attachment: {{
      type: "hook_additional_context",
      hookName: "SessionStart",
      content: ["using-superpowers skill block"]
    }}
  }},
  {{
    type: "attachment",
    uuid: "task-row",
    timestamp: "2026-07-02T22:14:17.825Z",
    sessionId: "session",
    parentUuid: "parent",
    attachment: {{ type: "task_reminder", content: [], itemCount: 0 }}
  }}
];
const projected = __codexNCHCProjectList(rows).filter(
  (row) => row.type === "system" && row.subtype === "codex_hidden_context"
);
if (projected.length !== 2) throw new Error("expected two projected rows");
if (!projected.every((row) => row.level === "warning")) throw new Error("expected warning rows");
if (!projected[0].content.includes("[model context] SessionStart hook additional context:")) {{
  throw new Error("missing SessionStart projection label");
}}
if (!projected[0].content.includes("using-superpowers")) {{
  throw new Error("missing hook content");
}}
if (projected[1].content !== "[model context] Task reminder: task tools have not been used recently (0 tasks)") {{
  throw new Error("task projection mismatch: " + projected[1].content);
}}
"""
    result = subprocess.run(
        ["node", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_hidden_context_drawer_package_uses_footer_overlay_without_global_ijo_cap_patch():
    package_dir = ROOT / "packages" / "hidden-context-drawer"
    footer_drawers_dir = ROOT / "packages" / "drawer-dock"
    manifest_data = json.loads((package_dir / "patch.json").read_text())
    targets = manifest_data.get("patch", manifest_data)["targets"]
    operations = targets[0]["modules"][0]["operations"]
    payloads = {
        operation["opId"]: (package_dir / operation["replacement"]["path"]).read_text()
        for operation in operations
    }
    overlay_payload = (
        footer_drawers_dir / "payloads" / "01-real-target-helpers-and-overlay.js"
    ).read_text()

    assert "__CODEX_HIDDEN_CONTEXT_DRAWER_FRAME_V13__" in payloads[
        "projection-helpers-before-ypr"
    ]
    # Overlay positioning is now owned by the shared drawer-dock overlay
    # component instead of a hidden-context-drawer-specific patch.
    assert 'position:"absolute",bottom:"100%"' in overlay_payload
    # The panel now refreshes itself on an interval rather than relying on a
    # shared 100ms poll patched directly onto the overlay component.
    assert (
        "setInterval(()=>t(Date.now()),250)"
        in payloads["hidden-context-panel-real-target"]
    )
    assert 'position:"absolute",marginTop:-(hCh+1)' not in "".join(payloads.values())
    assert 'position:"absolute",marginTop:-(hCh+1)' not in overlay_payload
    postcondition_values = {
        assertion["value"] for assertion in targets[0]["postconditions"]
    }
    assert "__CODEX_HIDDEN_CONTEXT_DRAWER_FRAME_V13__" in postcondition_values
    assert "function __codexNCHCPanel" in postcondition_values


def test_hidden_context_drawer_scroll_step_is_six_for_keyboard_and_mouse_with_top_jump():
    package_dir = ROOT / "packages" / "drawer-dock"
    keyboard_payload = (
        package_dir / "payloads" / "01-real-target-helpers-and-overlay.js"
    ).read_text()
    overlay_payload = (
        ROOT / "packages" / "hidden-context-drawer" / "payloads" / "17-panel-real-target.js"
    ).read_text()

    # Keyboard and mouse-wheel scrolling now share the faster 6-line drawer step.
    assert "function __codexFDScrollStep(){return 6}" in keyboard_payload
    assert "__codexFDHiddenContextScroll(-__codexFDScrollStep(),r)" in keyboard_payload
    assert "__codexFDHiddenContextScroll(__codexFDScrollStep(),r)" in keyboard_payload
    assert "footer:jumpTop" in keyboard_payload
    assert "__codexFDHiddenContextJumpTop(r)" in keyboard_payload
    assert "__codexFDHiddenContextScroll(-3,r)" not in keyboard_payload
    assert "__codexFDHiddenContextScroll(3,r)" not in keyboard_payload
    # Mouse-wheel scrolling is now owned by the shared drawer renderer; the
    # Hidden Context panel delegates to that renderer.
    assert "__codexFDRenderDrawerPanel" in overlay_payload
    assert "onWheel" in keyboard_payload
    assert "m.deltaY>0?d:-d" in keyboard_payload


def test_hidden_context_drawer_footer_flashes_blue_until_selection_clears():
    package_dir = ROOT / "packages" / "hidden-context-drawer"
    footer_drawers_dir = ROOT / "packages" / "drawer-dock"
    helper_payload = (
        package_dir / "payloads" / "01-projection-helpers-before-ypr-2.1.201.js"
    ).read_text()
    footer_payload = (
        footer_drawers_dir / "payloads" / "09-status-real-drawer-bars.js"
    ).read_text()
    # Reset-on-open and reset-on-scroll both now live in the shared
    # drawer-dock real-target helpers/action-wrapper payload.
    globals_and_keyboard_payload = (
        footer_drawers_dir / "payloads" / "01-real-target-helpers-and-overlay.js"
    ).read_text()

    assert "flashUntil:o?Number.MAX_SAFE_INTEGER:r?.flashUntil??0" in helper_payload
    assert "FDhFlash=!FDhSel&&Date.now()<(FDhCf?.flashUntil??0)" in footer_payload
    assert 'color:"white",backgroundColor:"blue"' in footer_payload
    assert "Date.now()<(FDhCf?.flashUntil??0)" in footer_payload
    # Reset when scrolling the drawer.
    assert "if(n)n.flashUntil=0" in globals_and_keyboard_payload
    # Reset when opening the drawer via footer:openSelected.
    assert "if(r?.frame)r.frame.flashUntil=0" in globals_and_keyboard_payload


def test_hidden_context_drawer_footer_x_closes_and_enter_opens():
    package_dir = ROOT / "packages" / "hidden-context-drawer"
    footer_drawers_dir = ROOT / "packages" / "drawer-dock"
    # Open/close wiring for the hiddenContext target moved into the shared
    # drawer-dock real-target action wrapper.
    open_close_payload = (
        footer_drawers_dir / "payloads" / "01-real-target-helpers-and-overlay.js"
    ).read_text()
    # The shared footer renderer owns the "x closes" hint text.
    overlay_payload = (
        package_dir / "payloads" / "17-panel-real-target.js"
    ).read_text()
    combined_hc_and_framework_text = "\n".join(
        [
            *(p.read_text() for p in sorted((package_dir / "payloads").glob("*.js"))),
            *(p.read_text() for p in sorted((footer_drawers_dir / "payloads").glob("*.js"))),
        ]
    )

    assert not (
        package_dir / "payloads" / "17-main-keydown-ctrl-period-hiddencontext.js"
    ).exists()
    assert 'onKeyDown:(Bt)=>{if(hC&&Bt.ctrl&&Bt.key===".")' not in combined_hc_and_framework_text
    assert 'Bt.ctrl&&Bt.name==="escape"' not in combined_hc_and_framework_text
    assert 't==="hiddenContext"' in open_close_payload
    assert "globalThis.__CODEX_HIDDEN_CONTEXT_DRAWER_OPEN_V13__=!0" in open_close_payload
    assert "r?.setHiddenOpen?.(!0)" in open_close_payload
    assert "globalThis.__CODEX_HIDDEN_CONTEXT_DRAWER_OPEN_V13__=!1" in open_close_payload
    assert "r?.setHiddenOpen?.(!1)" in open_close_payload
    assert "n?.(null)" in open_close_payload
    assert (
        'o["footer:clearSelection"]=()=>{if(t==="hiddenContext"&&r?.hiddenOpen)return!1;'
        in open_close_payload
    )
    assert "__codexFDRenderDrawerPanel" in overlay_payload
    assert "x closes" in open_close_payload
    assert "ctrl+. closes" not in combined_hc_and_framework_text
    assert "ctrl+esc closes" not in combined_hc_and_framework_text
    assert "| esc closes" not in combined_hc_and_framework_text


def test_hidden_context_drawer_payload_avoids_utf8_separator_mojibake_and_uses_warning_header():
    package_dir = ROOT / "packages" / "hidden-context-drawer"
    helper_payload = (
        package_dir / "payloads" / "01-projection-helpers-before-ypr-2.1.201.js"
    ).read_bytes()
    overlay_payload = (
        package_dir / "payloads" / "17-panel-real-target.js"
    ).read_text()

    assert b"\xc2\xb7" not in helper_payload
    assert b"\\xB7" in helper_payload
    footer_payload = (ROOT / "packages" / "drawer-dock" / "payloads" / "01-real-target-helpers-and-overlay.js").read_text()
    assert 'borderColor:"warning"' in overlay_payload
    assert 'title:"Hidden Context"' in overlay_payload
    assert "borderText:{content:` ${n} ${p} `" in footer_payload
    assert 'lineKinds' in helper_payload.decode()
    assert 'blocks' in helper_payload.decode()
    assert 'color:d===""?void 0:"warning"' not in overlay_payload
    assert 'Xd.jsx(v,{bold:!0,children:["Hidden Context  "' not in overlay_payload


def test_hidden_context_drawer_projection_frame_has_timestamps_sources_and_broader_model_context():
    package_dir = ROOT / "packages" / "hidden-context-drawer"
    helper_payload = (
        package_dir / "payloads" / "01-projection-helpers-before-ypr-2.1.201.js"
    ).read_text()
    # The migrated payload is inserted before the "Ypr" anchor and no longer
    # carries a trailing stub of the anchored function, but keep the
    # removesuffix guard in case that ever changes again.
    helper_block = helper_payload.removesuffix("function Ypr(e){\n").removesuffix(
        "function Ypr(e){"
    )
    script = f"""
{helper_block}
globalThis.__CODEX_HIDDEN_CONTEXT_DRAWER_FRAME_V13__ = undefined;
const rows = [
  {{
    type: "attachment",
    uuid: "hook-additional",
    timestamp: "2026-07-02T22:13:14.365Z",
    attachment: {{
      type: "hook_additional_context",
      hookName: "SessionStart",
      content: ["full hidden context line one", "full hidden context line two"]
    }}
  }},
  {{
    type: "attachment",
    uuid: "hook-blocking",
    timestamp: "2026-07-02T22:14:15.000Z",
    attachment: {{
      type: "hook_blocking_error",
      hookEvent: "UserPromptSubmit",
      message: "blocked command details"
    }}
  }},
  {{
    type: "attachment",
    uuid: "hook-stopped",
    timestamp: "2026-07-02T22:15:16.000Z",
    attachment: {{
      type: "hook_stopped_continuation",
      hookEvent: "Stop",
      content: ["continue with hidden instruction"]
    }}
  }},
  {{
    type: "attachment",
    uuid: "plan-mode",
    timestamp: "2026-07-02T22:16:17.000Z",
    attachment: {{
      type: "plan_mode",
      content: "plan mode model-visible reminder"
    }}
  }},
  {{
    type: "attachment",
    uuid: "auto-mode",
    timestamp: "2026-07-02T22:17:18.000Z",
    attachment: {{
      type: "auto_mode",
      content: "auto mode model-visible reminder"
    }}
  }},
  {{
    type: "attachment",
    uuid: "task-reminder",
    timestamp: "2026-07-02T22:18:19.000Z",
    attachment: {{ type: "task_reminder", content: [], itemCount: 0 }}
  }},
  {{
    type: "attachment",
    uuid: "agent-listing",
    timestamp: "2026-07-02T22:19:20.000Z",
    attachment: {{
      type: "agent_listing_delta",
      added: ["researcher"],
      removed: ["old-agent"],
      content: "agent listing changed for model"
    }}
  }}
];
const frame = __codexNCHCDrawerFrameFromList(rows);
if (!frame.visible) throw new Error("frame should be visible");
if (frame.eventCount !== rows.length) throw new Error("expected all model-visible hidden rows, got " + frame.eventCount);
if (frame.entries[0].key !== "agent-listing") throw new Error("expected reverse chronological order");
if (!frame.entries.every((entry) => entry.timeLabel && entry.sourceLabel && entry.text)) {{
  throw new Error("entries must include timeLabel, sourceLabel, and text: " + JSON.stringify(frame.entries));
}}
if (frame.entries[0].timeLabel !== "22:19:20Z") throw new Error("bad time label: " + frame.entries[0].timeLabel);
if (frame.entries[0].sourceLabel !== "attachment:agent_listing_delta") {{
  throw new Error("bad source label: " + frame.entries[0].sourceLabel);
}}
const allText = frame.lines.join("\\n");
if (frame.lineKinds[0] !== "header" || frame.lineKinds[1] !== "body") throw new Error("expected header/body line kinds: " + JSON.stringify(frame.lineKinds.slice(0,4)));
for (const expected of [
  "22:19:20Z",
  "attachment:agent_listing_delta",
  "Agent listing",
  "22:17:18Z",
  "attachment:auto_mode",
  "auto mode model-visible reminder",
  "22:16:17Z",
  "attachment:plan_mode",
  "plan mode model-visible reminder",
  "22:15:16Z",
  "attachment:hook_stopped_continuation",
  "continue with hidden instruction",
  "22:14:15Z",
  "attachment:hook_blocking_error",
  "blocked command details",
  "22:13:14Z",
  "attachment:hook_additional_context \xB7 hook:SessionStart",
  "full hidden context line two"
]) {{
  if (!allText.includes(expected)) throw new Error("missing expected drawer text: " + expected + "\\n" + allText);
}}
if (!(frame.tokenCount > 0)) throw new Error("expected non-zero token count");
"""
    result = subprocess.run(
        ["node", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
