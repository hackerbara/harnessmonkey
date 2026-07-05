from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from harnessmonkey.bun_graph import parse_bun_section
from harnessmonkey.builder_v15 import BuildRequestV15, build_patchset_v15, load_manifest_v2
from harnessmonkey.macho import find_macho_layout
from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = "/$bunfs/root/src/entrypoints/cli.js"
SOURCE = claude_version_path("2.1.201")
MODULE_DUMP = ROOT / ".development" / "artifacts" / "claude-2.1.201-framework-source-module0.js"
FOOTER = ROOT / "packages" / "drawer-dock"
HC = ROOT / "packages" / "hidden-context-drawer"
THINKING = ROOT / "packages" / "thinking-drawer"
REMINDERS = ROOT / "packages" / "reminders-drawer"

EXPECTED_SOURCE_SHA = "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
EXPECTED_SOURCE_SIZE = 231708784
EXPECTED_MODULE_SHA = "46db617a7b13c062fb31595f6244819b11f7cdc6e6fed8e2c3f74a27fb6da1bd"
EXPECTED_MODULE_LENGTH = 18700756

FORBIDDEN_RUNTIME_NEEDLES = [
    '"drawers"',
    'footerSelection==="drawers"',
    'footerSelection === "drawers"',
    'id:"drawers"',
    'id: "drawers"',
    "__CODEX_FOOTER_DRAWERS_V1__",
    "__codexFDDrawers",
    "__codexFDRegister",
    "__codexFDLand",
    "__codexFDMove",
    "hoverId",
    "openId",
]

REGISTRATION_PAYLOADS = [
    HC / "payloads" / "17-register-footer-drawer.js",
    THINKING / "payloads" / "17-register-footer-drawer.js",
    REMINDERS / "payloads" / "rm-register-footer-drawer-2.1.201.js",
]


def _manifest(package_dir: Path):
    return load_manifest_v2(package_dir)


def _all_payload_text() -> str:
    parts: list[str] = []
    for package_dir in [FOOTER, HC, THINKING, REMINDERS]:
        for path in sorted((package_dir / "payloads").glob("*.js")):
            parts.append(f"\n/* {path.relative_to(ROOT)} */\n")
            parts.append(path.read_text(encoding="utf-8"))
    return "".join(parts)


def _source_or_skip() -> Path:
    if not SOURCE.exists():
        pytest.skip(f"missing local Claude source: {SOURCE}")
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SOURCE_SHA:
        pytest.skip("local Claude source SHA differs from approved 2.1.201 identity")
    if len(raw) != EXPECTED_SOURCE_SIZE:
        pytest.skip("local Claude source size differs from approved 2.1.201 identity")
    return SOURCE


def _module_text_from_binary(binary: Path) -> str:
    raw = binary.read_bytes()
    layout = find_macho_layout(raw)
    section = raw[layout.bun_section.offset : layout.bun_section.offset + layout.bun_section.size]
    graph = parse_bun_section(section)
    module = graph.module_by_path(MODULE_PATH)
    return module.content.decode("utf-8")


def _build_full_stack(tmp_path: Path) -> str:
    source = _source_or_skip()
    request = BuildRequestV15(
        source_path=source,
        output_dir=tmp_path / "claude-footer-real-targets",
        package_dirs=[FOOTER, HC, THINKING, REMINDERS],
        source_version="2.1.201",
        source_version_output="2.1.201 (Claude Code)",
        platform="darwin",
        arch="arm64",
    )
    report = build_patchset_v15(request)
    assert report.failureReason is None, report.failureReason
    assert report.automatedStatus == "passed"
    assert report.status == "verified"
    assert report.manualSmoke["required"] is True
    assert report.manualSmoke["status"] == "bypassed"
    assert report.activationEligible is True
    assert report.outputPath is not None
    return _module_text_from_binary(Path(report.outputPath))


def test_source_identity_constants_match_approved_spec() -> None:
    assert SOURCE.exists()
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_SOURCE_SHA
    assert len(raw) == EXPECTED_SOURCE_SIZE
    if MODULE_DUMP.exists():
        dump = MODULE_DUMP.read_bytes()
        assert hashlib.sha256(dump).hexdigest() == EXPECTED_MODULE_SHA
        assert len(dump) == EXPECTED_MODULE_LENGTH


def test_payloads_and_manifests_contain_no_runtime_registry_or_synthetic_drawers() -> None:
    text = _all_payload_text()
    for needle in FORBIDDEN_RUNTIME_NEEDLES:
        assert needle not in text
    for descriptor_field in ["available:", "onOpen:", "onClose:", "onKey:", "renderPanel:"]:
        assert descriptor_field not in text
    for path in REGISTRATION_PAYLOADS:
        assert not path.exists(), f"delete or replace bad registrant payload: {path}"


def test_footer_manifest_owns_real_target_seams_not_registry_lifecycle() -> None:
    manifest = _manifest(FOOTER)
    op_ids = {op.op_id for target in manifest.targets for module in target.modules for op in module.operations}
    assert op_ids == {
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
    postconditions = {pc.value for target in manifest.targets for pc in target.postconditions}
    assert "__CODEX_FOOTER_DRAWERS_V1__" not in postconditions
    assert "__codexFDWrapActions" not in postconditions
    assert '"drawers"' not in postconditions


def test_drawer_packages_no_longer_ship_descriptor_registrants() -> None:
    for package_dir in [HC, THINKING, REMINDERS]:
        manifest = _manifest(package_dir)
        op_ids = {op.op_id for target in manifest.targets for module in target.modules for op in module.operations}
        assert all("register-footer-drawer" not in op_id for op_id in op_ids)
        assert all("register" not in op_id or "drawer" not in op_id for op_id in op_ids)
    assert "__codexTTDRegisterFooterDrawer" not in _all_payload_text()
    assert "__codexNCHCRegisterFooterDrawer" not in _all_payload_text()
    assert "__codexRMRegisterFooterDrawer" not in _all_payload_text()


def test_full_stack_composed_module_uses_real_targets_and_rejects_prior_failure_mode(tmp_path: Path) -> None:
    module = _build_full_stack(tmp_path)
    for needle in [item for item in FORBIDDEN_RUNTIME_NEEDLES if item != "openId"]:
        assert needle not in module
    assert "__CODEX_FOOTER_DRAWERS_V1__" not in module
    assert "__CODEX_FOOTER_DRAWERS_V1__?.openId" not in module
    assert "openId===\"thinking\"" not in module
    assert '"hiddenContext"' in module
    assert '"thinking"' in module
    assert '"reminders"' in module
    target_idx = module.index('__codexHiddenContextFrame?.visible&&"hiddenContext"')
    tasks_idx = module.index('Ui&&"tasks"', target_idx)
    assert target_idx < tasks_idx
    assert 'TT=Lm==="thinking"' in module or 'Lm==="thinking"' in module
    assert 'RM=Lm==="reminders"' in module or 'Lm==="reminders"' in module
    assert "__codexRMWrapActions" in module
    assert 'if(t!=="reminders")return e' in module
    assert "__CODEX_THINKING_TEXT_DRAWER_OPEN_V1__" in module
    assert "__CODEX_THINKING_TEXT_DRAWER_SELECTED_V1__" in module
    assert "__CODEX_THINKING_TEXT_DRAWER_SELECTED_V1__===!0&&globalThis.__CODEX_THINKING_TEXT_DRAWER_OPEN_V1__===!0" in module


def test_hidden_context_target_construction_is_same_render_frame_not_global_callback(tmp_path: Path) -> None:
    module = _build_full_stack(tmp_path)
    assert "available:()=>!!globalThis.__CODEX_HIDDEN_CONTEXT_DRAWER_FRAME_V13__?.visible" not in module
    assert '__codexHiddenContextFrame=typeof __codexNCHCDrawerFrameFromList==="function"?__codexNCHCDrawerFrameFromList(d.current):null' in module
    assert '__codexHiddenContextFrame?.visible&&"hiddenContext"' in module
    assert "__codexHiddenContextFrame?.generation" in module


def test_status_bar_is_explicit_real_segments_not_synthetic_toolbar(tmp_path: Path) -> None:
    module = _build_full_stack(tmp_path)
    assert "FDbar=__codexFDAvailable" not in module
    assert "__codexFDBar(" not in module
    assert 'footerSelection==="hiddenContext"' in module
    assert 'footerSelection==="thinking"' in module
    assert 'footerSelection==="reminders"' in module
    assert '"Hidden Context "' in module
    assert '"Thinking"' in module
    assert '"Reminders"' in module
    assert '" (enter)"' in module
    assert '" \\u2192"' in module
    assert "3/7" not in module


def test_no_descriptor_like_static_drawer_table_exists() -> None:
    text = _all_payload_text()
    forbidden_combinations = [
        ('id:"hiddenContext"', 'onOpen:', 'renderPanel:'),
        ('id:"thinking"', 'onOpen:', 'renderPanel:'),
        ('id:"reminders"', 'onOpen:', 'renderPanel:'),
        ('available:()=>', 'onKey:', 'renderPanel:'),
    ]
    for combo in forbidden_combinations:
        assert not all(piece in text for piece in combo), combo
