"""The pool-break note must compose naturally with the hidden-context packages.

Design contract (2026-07-05 pivot): the note is appended as a genuine
hidden-context attachment row — `ki({type:"critical_system_reminder",content:ft})`
— so that:
  - stock UI hides it (Ypr filters attachment types in the scf hidden set),
  - BOTH surfacing packages (hidden-context-inline, and
    hidden-context-drawer) pick it up through their existing
    critical_system_reminder projection branch with ZERO capybara-specific code,
  - the model still receives it (ARc forwards critical_system_reminder as an
    isMeta <system-reminder> user message),
  - it survives /resume (not in the deserialize drop-set).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.harnessmonkey_binary import claude_version_path

ROOT = Path(__file__).resolve().parents[1]
LIVE_SOURCE = claude_version_path("2.1.201")

NOTE_ATTACHMENT_TYPE = "critical_system_reminder"
NOTE_APPEND_LITERAL = 'ki({type:"critical_system_reminder",content:ft})'
OLD_ISMETA_APPEND_TAIL = 'Dn({content:[{type:"text",text:ft}],isMeta:!0})'

SURFACING_PACKAGE_IDS = [
    "hidden-context-inline",
    "hidden-context-drawer",
]


def _package_payload_text(package_id: str) -> str:
    package_dir = ROOT / "packages" / package_id
    manifest = json.loads((package_dir / "patch.json").read_text())
    operations = manifest["patch"]["targets"][0]["modules"][0]["operations"]
    return "\n".join(
        (package_dir / op["replacement"]["path"]).read_text(encoding="utf-8")
        for op in operations
    )


def _module_text() -> str:
    import sys

    sys.path.insert(0, str(ROOT / "examples"))
    from art_package_emitter import module_content  # reuse the generator's extractor

    return module_content(LIVE_SOURCE.read_bytes()).decode("utf-8")


def test_note_payload_appends_hidden_context_attachment_not_ismeta_user_row():
    payload = _package_payload_text("capybara-onsen")
    assert NOTE_APPEND_LITERAL in payload, (
        "op 10 must append the note via ki() as a critical_system_reminder "
        "attachment row (hidden-context composition design)"
    )
    assert OLD_ISMETA_APPEND_TAIL not in payload, (
        "the retired isMeta user-message append must be gone (it was invisible "
        "in the UI and is superseded by the hidden-context attachment shape)"
    )


def test_both_surfacing_packages_project_the_note_type_without_capy_code():
    for package_id in SURFACING_PACKAGE_IDS:
        payload = _package_payload_text(package_id)
        assert NOTE_ATTACHMENT_TYPE in payload, (
            f"{package_id}: no {NOTE_ATTACHMENT_TYPE} projection branch — the "
            "pool note would not surface with this package installed"
        )
        assert "capy" not in payload.lower(), (
            f"{package_id}: contains capybara-specific code — composition must "
            "be natural, not special-cased"
        )


def test_stock_module_hides_forwards_and_resumes_the_note_type():
    if not LIVE_SOURCE.exists():
        pytest.skip(f"local Claude Code 2.1.201 source missing: {LIVE_SOURCE}")
    module = _module_text()

    # 1. Hidden in stock UI: Ypr filters attachment types in the scf/icf set.
    scf = re.search(r'\bscf=\[("[^\]]*?")\]', module)
    assert scf, "hidden-attachment type list (scf) not found in module"
    assert f'"{NOTE_ATTACHMENT_TYPE}"' in scf.group(1), (
        "critical_system_reminder is no longer in the stock hidden set — the "
        "note would leak into the stock transcript"
    )

    # 2. Forwarded to the model: ARc converts it to an isMeta system-reminder.
    assert (
        'critical_system_reminder:(e)=>Ap([Dn({content:e.content,isMeta:!0})])'
        in module
    ), "model-context forwarding handler for critical_system_reminder missing"

    # 3. Survives /resume: not in the deserialize-time attachment drop-set.
    drop = re.search(r'new Set\(\["compaction_reminder"[^\)]*?\]\)', module)
    assert drop, "resume-time attachment drop-set not found in module"
    assert NOTE_ATTACHMENT_TYPE not in drop.group(0), (
        "critical_system_reminder is dropped on resume — the note would not "
        "re-surface after /resume"
    )
