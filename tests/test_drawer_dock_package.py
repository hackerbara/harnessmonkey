# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from tests.harnessmonkey_binary import claude_version_path

from harnessmonkey.builder_v15 import BuildRequestV15, build_patchset_v15, load_manifest_v2
from harnessmonkey.payloads import load_payload_bytes

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = "/$bunfs/root/src/entrypoints/cli.js"
SOURCE_2_1_201 = claude_version_path("2.1.201")
MODULE_DUMP_2_1_201 = ROOT / ".development" / "artifacts" / "claude-2.1.201-framework-source-module0.js"
FOOTER_DRAWERS = ROOT / "packages" / "drawer-dock"
HC = ROOT / "packages" / "hidden-context-drawer"
THINKING = ROOT / "packages" / "thinking-drawer"
REMINDERS = ROOT / "packages" / "reminders-drawer"
CAPY = ROOT / "packages" / "capybara-onsen"
DRAGONS = ROOT / "packages" / "heraldic-dragons"

EXPECTED_BINARY_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_BINARY_SIZE = 231708784
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"
EXPECTED_MODULE_LENGTH = 18700756

FRAMEWORK_OP_IDS = {
    "fd-real-target-helpers-and-overlay",
    "fd-footer-hiddencontext-state",
    "fd-real-drawer-targets",
    "fd-real-drawer-selection-flags",
    "fd-real-target-action-wrap-open",
    "fd-real-target-action-wrap-close",
    "fd-footer-space-binding",
    "fd-status-real-drawer-selection-hooks",
    "fd-status-real-drawer-bars",
    "fd-status-shortcuts-condition",
    "fd-status-null-condition",
    "fd-status-render-real-drawer-bars",
}

MOVED_THINKING_OP_IDS = {
    "thinking-footer-open-state",
    "thinking-footer-target",
    "thinking-footer-selection-flag",
    "thinking-footer-action-wrap-open",
    "thinking-footer-action-wrap-close",
    "thinking-selected-overlay-globals",
    "thinking-bottom-overlay-renderer",
    "thinking-footer-status-bar",
}


def _manifest_json(package_dir: Path) -> dict:
    return json.loads((package_dir / "patch.json").read_text(encoding="utf-8"))


def _source_or_skip() -> Path:
    if not SOURCE_2_1_201.exists():
        pytest.skip(f"missing local Claude source: {SOURCE_2_1_201}")
    actual = hashlib.sha256(SOURCE_2_1_201.read_bytes()).hexdigest()
    if actual != EXPECTED_BINARY_SHA:
        pytest.skip(f"local Claude source SHA changed: {actual}")
    return SOURCE_2_1_201


def _module_dump_or_skip() -> str:
    if not MODULE_DUMP_2_1_201.exists():
        pytest.skip(f"missing module dump: {MODULE_DUMP_2_1_201}")
    data = MODULE_DUMP_2_1_201.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED_MODULE_SHA:
        pytest.skip("module dump SHA does not match 2.1.201 target")
    return data.decode("utf-8")


def test_footer_drawers_manifest_targets_latest_local_2_1_201() -> None:
    manifest = _manifest_json(FOOTER_DRAWERS)
    assert manifest["schemaVersion"] == 1
    assert manifest["kind"] == "patch"
    assert manifest["patch"]["engine"] == "bun_graph_repack"
    assert manifest["id"] == "drawer-dock"
    assert manifest.get("requiresPackages", []) == []
    assert manifest.get("conflictsWithPackages", []) == []
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
    assert {op["opId"] for op in module["operations"]} == FRAMEWORK_OP_IDS


def test_footer_drawers_payloads_are_ascii_safe_and_hashes_match() -> None:
    manifest = load_manifest_v2(FOOTER_DRAWERS)
    for target in manifest.targets:
        for module in target.modules:
            for operation in module.operations:
                payload = load_payload_bytes(operation.replacement, FOOTER_DRAWERS)
                assert payload
                if operation.replacement.path:
                    path = FOOTER_DRAWERS / operation.replacement.path
                    assert operation.replacement.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
                    text = path.read_text(encoding="utf-8")
                    offenders = [(i, line) for i, line in enumerate(text.splitlines(), 1) if any(ord(ch) > 127 for ch in line)]
                    assert offenders == [], f"non-ascii payload text in {path}: {offenders[:3]}"


def test_footer_drawers_payloads_have_no_registry_or_descriptor_contract() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted((FOOTER_DRAWERS / "payloads").glob("*.js")))
    for needle in [
        "__CODEX_FOOTER_DRAWERS_V1__",
        "__codexFDDrawers",
        "__codexFDRegister",
        "hoverId",
        "openId",
        "__codexFDLand",
        "__codexFDMove",
        '"drawers"',
        'footerSelection==="drawers"',
        "available:",
        "onOpen:",
        "onClose:",
        "onKey:",
        "renderPanel:",
    ]:
        assert needle not in text
    assert "function __codexFDWrapRealTargetActions" in text
    assert 't==="reminders"&&typeof __codexRMWrapActions==="function"' in text
    assert '__codexHiddenContextFrame?.visible&&"hiddenContext"' in text
    assert "FDdrawerBars=[FDhBar,FDtBar,FDrBar].filter(Boolean)" in text

def _run_footer_drawers_payload_js(body: str) -> dict:
    bootstrap = FOOTER_DRAWERS / "payloads" / "01-bootstrap-and-overlay.js"
    script = f"""
const fs = require("fs");
const Xd = {{
  Fragment: "Fragment",
  jsx: (type, props, key) => ({{type: typeof type === "function" ? type.name : type, props, key}}),
  jsxs: (type, props, key) => ({{type: typeof type === "function" ? type.name : type, props, key}}),
}};
function B(props) {{ return props; }}
function v(props) {{ return props; }}
const MXe = {{ c: (n) => new Array(n) }};
function clc() {{ return null; }}
eval(fs.readFileSync({str(bootstrap)!r}, "utf8"));
{body}
"""
    result = subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def test_footer_drawers_status_bar_uses_explicit_real_target_segments() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted((FOOTER_DRAWERS / "payloads").glob("*.js")))
    assert 'footerSelection==="hiddenContext"' in text
    assert 'footerSelection==="thinking"' in text
    assert 'footerSelection==="reminders"' in text
    assert '"Hidden Context "' in text
    assert '"Thinking"' in text
    assert '"Reminders"' in text
    assert '" (enter)"' in text
    assert '" \\u2192"' in text
    assert "FDbar" not in text
    assert "__codexFDBar" not in text

def test_footer_drawers_target_list_has_real_drawer_targets_before_stock_targets() -> None:
    text = (FOOTER_DRAWERS / "payloads" / "03-real-drawer-targets.js").read_text(encoding="utf-8")
    assert text.index('__codexHiddenContextFrame?.visible&&"hiddenContext"') < text.index('typeof __codexTTDEnsure==="function"&&"thinking"') < text.index('typeof __codexRMState==="function"&&"reminders"') < text.index('Ui&&"tasks"')
    assert '"drawers"' not in text

def test_footer_drawers_action_wrapper_routes_by_real_selected_target() -> None:
    text = (FOOTER_DRAWERS / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    bindings = (FOOTER_DRAWERS / "payloads" / "07-footer-space-binding.js").read_text(encoding="utf-8")
    assert 'function __codexFDWrapRealTargetActions(e,t,n,r)' in text
    assert 'function __codexFDScrollStep(){return 6}' in text
    assert 't==="hiddenContext"' in text
    assert 't==="thinking"' in text
    assert 't==="reminders"&&typeof __codexRMWrapActions==="function"' in text
    assert 'footer:clearSelection' in text
    assert 'footer:close' in text
    assert 'footer:jumpTop' in text
    assert 'g:"footer:jumpTop"' in bindings
    assert '"shift+g":"footer:jumpTop"' in bindings
    assert '__codexFDHiddenContextScroll(-3,r)' not in text
    assert '__codexFDHiddenContextScroll(3,r)' not in text
    assert 'children:"  up/down or mouse wheel scroll | x closes"' in text
    assert 'openId' not in text
    assert 'hoverId' not in text


def test_footer_drawers_owns_shared_boxed_drawer_display_primitives() -> None:
    text = (FOOTER_DRAWERS / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    for name in [
        "__codexFDViewport",
        "__codexFDClampScroll",
        "__codexFDBlockLineCount",
        "__codexFDVisibleBlocks",
        "__codexFDRenderBlockList",
        "__codexFDVisibleLines",
        "__codexFDRenderLineList",
        "__codexFDRenderDrawerPanel",
    ]:
        assert f"function {name}" in text
    assert 'borderStyle:"single"' in text
    assert 'borderStyle:"round"' in text
    assert 'top:g' in text
    assert 'onWheel' in text
    assert 'bodyLines' in text
    assert 'flatContent' in text


def test_footer_drawers_overlay_optionally_mounts_markdown_preview_panel() -> None:
    text = (FOOTER_DRAWERS / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    assert 'typeof __codexMDLPPanel==="function"?Xd.jsx(__codexMDLPPanel,{})' in text
    assert "children:[n,r,o,s,t]" in text


def test_footer_drawers_operations_resolve_once_in_2_1_201_module_dump() -> None:
    source = _module_dump_or_skip()
    manifest = _manifest_json(FOOTER_DRAWERS)
    operations = manifest["patch"]["targets"][0]["modules"][0]["operations"]
    for operation in operations:
        if operation["type"] == "replace_exact":
            exact = operation["exact"]
            assert source.count(exact) == 1, operation["opId"]
            assert len(exact.encode("utf-8")) == operation["oldRangeLength"]
            assert hashlib.sha256(exact.encode("utf-8")).hexdigest() == operation["oldRangeSha256"]
        elif operation["type"] in {"insert_before", "insert_after"}:
            anchor = operation["anchor"]
            assert source.count(anchor) == operation.get("expectedAnchorCount", 1), operation["opId"]
        elif operation["type"] == "replace_substring_within":
            start = operation["startMarker"]
            end = operation["endMarker"]
            assert source.count(start) == operation.get("expectedStartMarkerCount", 1), operation["opId"]
            start_index = source.index(start)
            end_index = source.index(end, start_index + len(start)) + len(end)
            context = source[start_index:end_index]
            assert context.count(operation["subExact"]) == operation.get("expectedSubExactCount", 1), operation["opId"]
        else:
            raise AssertionError(operation)


def test_thin_drawers_require_footer_drawers_after_migration() -> None:
    for package_dir in [HC, THINKING, REMINDERS]:
        manifest = load_manifest_v2(package_dir)
        assert "drawer-dock" in manifest.requires_packages, package_dir


def test_thinking_direct_footer_ops_are_removed_after_migration() -> None:
    manifest = load_manifest_v2(THINKING)
    op_ids = {op.op_id for target in manifest.targets for module in target.modules for op in module.operations}
    assert op_ids.isdisjoint(MOVED_THINKING_OP_IDS)
    assert "thinking-register-footer-drawer" not in op_ids
    assert "thinking-panel-real-target" in op_ids
    assert {
        "thinking-helpers-before-ypr",
        "thinking-message-start-turn-collector",
        "thinking-message-stop-turn-collector",
        "thinking-live-delta-collector",
        "thinking-signature-collector",
        "thinking-parent-structured-collector",
        "thinking-system-token-estimate",
        "thinking-cancel-salvage-collector",
    }.issubset(op_ids)

@pytest.mark.local_real_smoke
def test_build_framework_alone_reaches_verified_with_manual_smoke_bypassed(tmp_path) -> None:
    source = _source_or_skip()
    report = build_patchset_v15(
        BuildRequestV15(
            source_path=source,
            output_dir=tmp_path / "framework-alone",
            package_dirs=[FOOTER_DRAWERS],
            source_version="2.1.201",
            source_version_output="2.1.201 (Claude Code)",
            platform="darwin",
            arch="arm64",
        )
    )
    assert report.automatedStatus == "passed"
    assert report.status == "verified"
    assert report.manualSmoke["required"] is True
    assert report.manualSmoke["status"] == "bypassed"
    assert report.activationEligible is True


def _write_matching_uas_conflict_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "mute-reminders-fixture"
    payload_dir = fixture / "payloads"
    payload_dir.mkdir(parents=True)
    payload = b"/* unused: package conflict is checked before operation planning */\n"
    (payload_dir / "noop.js").write_bytes(payload)
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "mute-reminders-fixture",
        "label": "UAS Conflict Fixture",
        "description": "2.1.201 identity fixture used only to verify Reminders package relationship conflicts.",
        "packageVersion": "2.1.201-fixture",
        "conflictsWithPackages": ["reminders-drawer"],
        "patch": {"engine": "bun_graph_repack", "targets": [{
            "sourceIdentity": {
                "claudeVersion": "2.1.201",
                "versionOutput": "2.1.201 (Claude Code)",
                "sha256": EXPECTED_BINARY_SHA,
                "sizeBytes": EXPECTED_BINARY_SIZE,
                "platform": "darwin",
                "arch": "arm64",
            },
            "requiredEngine": "bun_graph_repack",
            "requiredBinaryFormat": "bun_standalone_macho64",
            "modules": [{
                "path": MODULE_PATH,
                "contentSha256": EXPECTED_MODULE_SHA,
                "contentLength": EXPECTED_MODULE_LENGTH,
                "operations": [{
                    "opId": "uas-conflict-fixture-noop",
                    "label": "Unused fixture operation",
                    "type": "replace_exact",
                    "exact": "__uas_conflict_fixture_never_reaches_planning__",
                    "replacement": {"path": "payloads/noop.js", "sha256": hashlib.sha256(payload).hexdigest()},
                    "knownBehaviorChange": "Never planned; relationship conflict should fail first.",
                }],
            }],
            "preconditions": [],
            "postconditions": [],
            "manualSmoke": {"required": False, "reason": None},
        }]},
    }
    (fixture / "patch.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return fixture


def test_reminders_conflicts_with_matching_uas_fixture_when_framework_is_present(tmp_path) -> None:
    source = _source_or_skip()
    uas_fixture = _write_matching_uas_conflict_fixture(tmp_path)
    report = build_patchset_v15(
        BuildRequestV15(
            source_path=source,
            output_dir=tmp_path / "reminders-uas",
            package_dirs=[FOOTER_DRAWERS, REMINDERS, uas_fixture],
            source_version="2.1.201",
            source_version_output="2.1.201 (Claude Code)",
            platform="darwin",
            arch="arm64",
        )
    )
    assert report.status == "failed"
    assert report.failureReason is not None
    assert "patch_conflict:package_conflict:mute-reminders-fixture:reminders-drawer" in report.failureReason


def _build_packages(tmp_path: Path, name: str, packages: list[Path]):
    source = _source_or_skip()
    return build_patchset_v15(
        BuildRequestV15(
            source_path=source,
            output_dir=tmp_path / name,
            package_dirs=packages,
            source_version="2.1.201",
            source_version_output="2.1.201 (Claude Code)",
            platform="darwin",
            arch="arm64",
        )
    )


@pytest.mark.parametrize(
    ("name", "packages"),
    [
        ("framework-thinking", [FOOTER_DRAWERS, THINKING]),
        ("framework-hidden", [FOOTER_DRAWERS, HC]),
        ("framework-reminders", [FOOTER_DRAWERS, REMINDERS]),
        ("framework-hidden-thinking", [FOOTER_DRAWERS, HC, THINKING]),
        ("framework-hidden-reminders", [FOOTER_DRAWERS, HC, REMINDERS]),
        ("framework-thinking-reminders", [FOOTER_DRAWERS, THINKING, REMINDERS]),
        ("framework-all", [FOOTER_DRAWERS, HC, THINKING, REMINDERS]),
        # Regression coverage for the capybara-onsen + hidden-context-drawer Enter-to-open
        # bug: capybara-onsen's responsive frame re-provides the app's real fde/t4 React
        # contexts around the composer/footer subtree that hosts drawer-dock' Enter
        # wiring. This combo is the maintainer's minimal reproduction (bars rendered, but
        # Enter no longer opened any drawer) before the center provider's context values
        # were memoized -- see test_capybara_onsen_center_provider_memoizes_context_values.
        ("framework-hidden-capy", [FOOTER_DRAWERS, HC, CAPY]),
        ("framework-all-capy", [FOOTER_DRAWERS, HC, THINKING, REMINDERS, CAPY]),
        # Same coverage for heraldic-dragons, which shares the identical
        # __hdCenterProviderV4 pattern (fixed alongside capybara-onsen's
        # __coCenterProviderV4) -- see
        # test_heraldic_dragons_center_provider_memoizes_context_values.
        ("framework-hidden-dragons", [FOOTER_DRAWERS, HC, DRAGONS]),
    ],
)
@pytest.mark.local_real_smoke
def test_footer_drawers_successful_composition_matrix(tmp_path, name, packages) -> None:
    report = _build_packages(tmp_path, name, packages)
    assert report.automatedStatus == "passed", report.failureReason
    assert report.status == "verified"
    assert report.manualSmoke["required"] is True
    assert report.manualSmoke["status"] == "bypassed"
    assert report.activationEligible is True
    assert report.enabledPatches == [p.name for p in packages]
    if name in ("framework-all", "framework-all-capy"):
        panels = [
            (op["packageId"], op["opId"], op["insertOrder"], op.get("insertionVerified"))
            for op in report.operationsApplied
            if op["opId"] in {
                "hidden-context-panel-real-target",
                "thinking-panel-real-target",
                "rm-panel-real-target",
            }
        ]
        assert panels == [
            ("hidden-context-drawer", "hidden-context-panel-real-target", 100, True),
            ("thinking-drawer", "thinking-panel-real-target", 200, True),
            ("reminders-drawer", "rm-panel-real-target", 300, True),
        ]
    if name in ("framework-hidden-capy", "framework-all-capy"):
        capy_ops = {op["opId"] for op in report.operationsApplied if op["packageId"] == "capybara-onsen"}
        assert "capy-onsen-main-window-me-2-1-201" in capy_ops
        assert "capy-onsen-bottom-stack-de-2-1-201" in capy_ops
    if name == "framework-hidden-dragons":
        dragon_ops = {op["opId"] for op in report.operationsApplied if op["packageId"] == "heraldic-dragons"}
        assert "heraldic-dragons-main-window-me-2-1-201" in dragon_ops
        assert "heraldic-dragons-bottom-stack-de-2-1-201" in dragon_ops


@pytest.mark.parametrize(("name", "package_dir"), [("hc", HC), ("thinking", THINKING), ("reminders", REMINDERS)])
def test_thin_drawer_without_framework_fails_required_package_missing(tmp_path, name, package_dir) -> None:
    report = _build_packages(tmp_path, f"missing-framework-{name}", [package_dir])
    assert report.status == "failed"
    assert report.failureReason is not None
    assert "patch_conflict:required_package_missing" in report.failureReason
    assert f":{package_dir.name}:drawer-dock" in report.failureReason

def test_old_direct_footer_owner_with_framework_fails_closed(tmp_path) -> None:
    source = _source_or_skip()
    stale = tmp_path / "thinking-drawer"
    stale.mkdir()
    exact = 'ss=wo.useMemo(()=>[Ui&&"tasks",po&&"workflows",Fn&&"tmux",_e&&"bagel",Tr&&"bridge",Ne&&"frame"].filter(Boolean),[Ui,po,Fn,_e,Tr,Ne])'
    replacement = exact.replace('[Ui&&"tasks"', '["thinking",Ui&&"tasks"')
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "thinking-drawer",
        "label": "Stale Direct Thinking",
        "description": "Fixture direct footer owner",
        "packageVersion": "0.0.0",
        "patch": {"engine": "bun_graph_repack", "targets": [{
            "sourceIdentity": {"claudeVersion":"2.1.201","versionOutput":"2.1.201 (Claude Code)","sha256":EXPECTED_BINARY_SHA,"sizeBytes":EXPECTED_BINARY_SIZE,"platform":"darwin","arch":"arm64"},
            "requiredEngine": "bun_graph_repack",
            "requiredBinaryFormat": "bun_standalone_macho64",
            "modules": [{"path":MODULE_PATH,"contentSha256":EXPECTED_MODULE_SHA,"contentLength":EXPECTED_MODULE_LENGTH,"operations":[{"opId":"stale-footer-target","label":"Stale footer target","type":"replace_exact","exact":exact,"requireWithinRange":[],"oldRangeSha256":hashlib.sha256(exact.encode()).hexdigest(),"oldRangeLength":len(exact.encode()),"replacement":{"inline":replacement}}]}],
        }]},
    }
    (stale / "patch.json").write_text(json.dumps(manifest))
    report = build_patchset_v15(BuildRequestV15(source_path=source, output_dir=tmp_path / "stale", package_dirs=[FOOTER_DRAWERS, stale], source_version="2.1.201", source_version_output="2.1.201 (Claude Code)", platform="darwin", arch="arm64"))
    assert report.status == "failed"
    assert report.failureReason is not None
    assert "patch_conflict" in report.failureReason
