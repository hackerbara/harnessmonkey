from __future__ import annotations

from harnessmonkey.menubar_state import parse_command_envelope, parse_menu_state

# ---------------------------------------------------------------------------
# shim-update-resilience stage 1 fields (spec 2026-07-04, section 1)
# ---------------------------------------------------------------------------
#
# `status --json` additively carries six fields describing a shim replaced
# by an official Claude update: shimPreviouslyManaged, targetReplacedByOfficial,
# detectedOfficialSha256, detectedOfficialVersion, shimRepairAvailable,
# rolloutRequired. `MenuState` must expose all six so the GUI notice model
# (window_model.build_notice_model) can decide what to show without ever
# reaching back into raw status JSON.


def _minimal_status_raw(**overrides) -> dict:
    base = {
        "schemaVersion": 1,
        "status": "ok",
        "sourceClaudeVersion": None,
        "sourceClaudePath": None,
        "installMode": "shim",
        "shimInstalled": True,
        "activeProfile": "default",
        "activePrompt": None,
        "desiredPatchIds": [],
        "activePatchIds": [],
        "rebuildRequired": False,
        "latestBuildReportPath": None,
        "activePatchSet": None,
        "currentClaudePath": None,
        "shimTargetPath": None,
        "installRecordPath": None,
        "stateDir": "/tmp/state",
        "logsDir": "/tmp/state/logs",
        "lastError": None,
    }
    base.update(overrides)
    return base


def test_parse_menu_state_reads_official_replacement_fields():
    state = parse_menu_state(
        _minimal_status_raw(
            shimInstalled=False,
            shimPreviouslyManaged=True,
            targetReplacedByOfficial=True,
            detectedOfficialSha256="a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd",
            detectedOfficialVersion="2.1.201",
            shimRepairAvailable=True,
            rolloutRequired=True,
        ),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
    )
    assert state.shim_previously_managed is True
    assert state.target_replaced_by_official is True
    assert (
        state.detected_official_sha256
        == "a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd"
    )
    assert state.detected_official_version == "2.1.201"
    assert state.shim_repair_available is True
    assert state.rollout_required is True


def test_parse_menu_state_defaults_official_replacement_fields_when_absent():
    # Real status --json always includes these six fields (they're additive
    # but unconditional), but MenuState must not blow up on an older/partial
    # payload -- same additive-and-optional discipline as every other v3
    # status field.
    state = parse_menu_state(
        _minimal_status_raw(),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
    )
    assert state.shim_previously_managed is False
    assert state.target_replaced_by_official is False
    assert state.detected_official_sha256 is None
    assert state.detected_official_version is None
    assert state.shim_repair_available is False
    assert state.rollout_required is False


def test_parse_menu_state_applies_status_precedence():
    state = parse_menu_state(
        {
            "schemaVersion": 1,
            "status": "ok",
            "sourceClaudeVersion": "2.1.198",
            "sourceClaudePath": "/tmp/claude",
            "installMode": "shim",
            "shimInstalled": True,
            "activeProfile": "default",
            "activePrompt": "research",
            "desiredPatchIds": ["a"],
            "activePatchIds": [],
            "rebuildRequired": True,
            "latestBuildReportPath": None,
            "activePatchSet": None,
            "currentClaudePath": None,
            "shimTargetPath": None,
            "installRecordPath": None,
            "buildStrategy": "repack",
            "lastBuildStrategy": "repack",
            "changedModules": [{"path": "/$bunfs/root/src/entrypoints/cli.js"}],
            "repackSummary": {"changedModuleCount": 1},
            "stateDir": "/tmp/state",
            "logsDir": "/tmp/state/logs",
            "lastError": None,
        },
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
    )
    assert state.status == "rebuild_required"
    assert state.status_label == "Rebuild Required"
    assert state.last_build_strategy == "repack"
    assert state.changed_modules == ({"path": "/$bunfs/root/src/entrypoints/cli.js"},)


def test_parse_menu_state_keeps_rebuild_boolean_consistent_with_status():
    state = parse_menu_state(
        {
            "schemaVersion": 1,
            "status": "rebuild_required",
            "sourceClaudeVersion": None,
            "sourceClaudePath": None,
            "installMode": "shim",
            "shimInstalled": True,
            "activeProfile": "default",
            "activePrompt": None,
            "desiredPatchIds": [],
            "activePatchIds": [],
            "rebuildRequired": False,
            "latestBuildReportPath": None,
            "activePatchSet": "/tmp/state/patchsets/default",
            "currentClaudePath": "/tmp/state/current",
            "shimTargetPath": "/tmp/state/bin/claude",
            "installRecordPath": "/tmp/state/install-record.json",
            "stateDir": "/tmp/state",
            "logsDir": "/tmp/state/logs",
            "lastError": None,
        },
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
    )
    assert state.status == "rebuild_required"
    assert state.rebuild_required is True


def test_parse_command_envelope_requires_error_message_on_failure():
    envelope = parse_command_envelope(
        {
            "schemaVersion": 1,
            "ok": False,
            "status": "error",
            "summary": "failed",
            "reportPath": None,
            "dryRun": False,
            "plannedActions": [],
            "error": {"message": "failed", "code": "boom"},
        }
    )
    assert envelope.error.message == "failed"


def test_prompt_and_patch_items_are_checked():
    state = parse_menu_state(
        {
            "schemaVersion": 1,
            "status": "ok",
            "sourceClaudeVersion": None,
            "sourceClaudePath": None,
            "installMode": "shim",
            "shimInstalled": False,
            "activeProfile": "default",
            "activePrompt": "research",
            "desiredPatchIds": ["fable-fallback"],
            "activePatchIds": ["fable-fallback"],
            "rebuildRequired": False,
            "latestBuildReportPath": None,
            "activePatchSet": "/tmp/state/patchsets/default",
            "currentClaudePath": "/tmp/state/current",
            "shimTargetPath": "/tmp/state/bin/claude",
            "installRecordPath": "/tmp/state/shims/claude.json",
            "stateDir": "/tmp/state",
            "logsDir": "/tmp/state/logs",
            "lastError": None,
        },
        {
            "schemaVersion": 1,
            "patches": [
                {
                    "id": "fable-fallback",
                    "label": "Fable",
                    "desiredEnabled": True,
                    "activeEnabled": True,
                    "available": True,
                    "compatibilityStatus": "compatible",
                }
            ],
        },
        {
            "schemaVersion": 1,
            "prompts": [
                {
                    "id": "research",
                    "label": "Research",
                    "active": True,
                    "mode": "append",
                    "sourcePath": "/tmp/research.md",
                }
            ],
        },
    )
    assert state.patch_items[0].checked is True
    assert state.prompt_items[0].checked is True


def test_command_envelope_rejects_string_booleans():
    try:
        parse_command_envelope(
            {
                "schemaVersion": 1,
                "ok": "false",
                "status": "error",
                "summary": "failed",
                "reportPath": None,
                "dryRun": False,
                "plannedActions": [],
                "error": {"message": "failed", "code": "boom"},
            }
        )
    except ValueError as exc:
        assert "ok must be boolean" in str(exc)
    else:
        raise AssertionError("expected strict boolean validation")


def test_command_envelope_rejects_string_planned_actions():
    try:
        parse_command_envelope(
            {
                "schemaVersion": 1,
                "ok": True,
                "status": "ok",
                "summary": "ok",
                "reportPath": None,
                "dryRun": True,
                "plannedActions": "rm -rf",
                "error": None,
            }
        )
    except ValueError as exc:
        assert "plannedActions must be a list" in str(exc)
    else:
        raise AssertionError("expected plannedActions validation")


def test_command_envelope_rejects_schema_drift_and_contradictory_status():
    base = {
        "schemaVersion": 2,
        "ok": True,
        "status": "ok",
        "summary": "ok",
        "reportPath": None,
        "dryRun": False,
        "plannedActions": [],
        "error": None,
    }
    try:
        parse_command_envelope(base)
    except ValueError as exc:
        assert "schemaVersion must be 1" in str(exc)
    else:
        raise AssertionError("expected schema validation")

    base["schemaVersion"] = 1
    base["status"] = "error"
    try:
        parse_command_envelope(base)
    except ValueError as exc:
        assert "ok envelope cannot have error status" in str(exc)
    else:
        raise AssertionError("expected status validation")


def test_command_envelope_rejects_non_string_planned_actions():
    try:
        parse_command_envelope(
            {
                "schemaVersion": 1,
                "ok": True,
                "status": "ok",
                "summary": "ok",
                "reportPath": None,
                "dryRun": True,
                "plannedActions": [{"bad": "object"}],
                "error": None,
            }
        )
    except ValueError as exc:
        assert "plannedActions items must be strings" in str(exc)
    else:
        raise AssertionError("expected plannedActions item validation")


def test_parse_menu_state_rejects_schema_drift():
    status = {
        "schemaVersion": 2,
        "status": "ok",
        "sourceClaudeVersion": None,
        "sourceClaudePath": None,
        "installMode": "shim",
        "shimInstalled": False,
        "activeProfile": "default",
        "activePrompt": None,
        "desiredPatchIds": [],
        "activePatchIds": [],
        "rebuildRequired": False,
        "latestBuildReportPath": None,
        "activePatchSet": None,
        "currentClaudePath": None,
        "shimTargetPath": None,
        "installRecordPath": None,
        "stateDir": "/tmp/state",
        "logsDir": "/tmp/state/logs",
        "lastError": None,
    }
    try:
        parse_menu_state(
            status,
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
        )
    except ValueError as exc:
        assert "schemaVersion must be 1" in str(exc)
    else:
        raise AssertionError("expected status schema validation")


def test_command_envelope_rejects_invalid_status_and_authorization_method():
    raw = {
        "schemaVersion": 1,
        "ok": True,
        "status": "surprising",
        "summary": "ok",
        "reportPath": None,
        "authorizationMethod": None,
        "dryRun": False,
        "plannedActions": [],
        "error": None,
    }
    try:
        parse_command_envelope(raw)
    except ValueError as exc:
        assert "unsupported status" in str(exc)
    else:
        raise AssertionError("expected status enum validation")

    raw["status"] = "ok"
    raw["authorizationMethod"] = {"bad": "object"}
    try:
        parse_command_envelope(raw)
    except ValueError as exc:
        assert "authorizationMethod" in str(exc)
    else:
        raise AssertionError("expected authorizationMethod validation")


def test_parse_menu_state_rejects_non_list_core_fields():
    status = {
        "schemaVersion": 1,
        "status": "ok",
        "sourceClaudeVersion": None,
        "sourceClaudePath": None,
        "installMode": "shim",
        "shimInstalled": False,
        "activeProfile": "default",
        "activePrompt": None,
        "desiredPatchIds": "abc",
        "activePatchIds": [],
        "rebuildRequired": False,
        "latestBuildReportPath": None,
        "activePatchSet": None,
        "currentClaudePath": None,
        "shimTargetPath": None,
        "installRecordPath": None,
        "stateDir": "/tmp/state",
        "logsDir": "/tmp/state/logs",
        "lastError": None,
    }
    try:
        parse_menu_state(
            status,
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
        )
    except ValueError as exc:
        assert "desiredPatchIds must be a list" in str(exc)
    else:
        raise AssertionError("expected desiredPatchIds validation")


def test_parse_menu_state_rejects_malformed_patch_and_prompt_lists():
    status = {
        "schemaVersion": 1,
        "status": "ok",
        "sourceClaudeVersion": None,
        "sourceClaudePath": None,
        "installMode": "shim",
        "shimInstalled": False,
        "activeProfile": "default",
        "activePrompt": None,
        "desiredPatchIds": [],
        "activePatchIds": [],
        "rebuildRequired": False,
        "latestBuildReportPath": None,
        "activePatchSet": None,
        "currentClaudePath": None,
        "shimTargetPath": None,
        "installRecordPath": None,
        "stateDir": "/tmp/state",
        "logsDir": "/tmp/state/logs",
        "lastError": None,
    }
    try:
        parse_menu_state(
            status,
            {"schemaVersion": 1, "patches": "bad"},
            {"schemaVersion": 1, "prompts": []},
        )
    except ValueError as exc:
        assert "patches must be a list" in str(exc)
    else:
        raise AssertionError("expected patches validation")


def _base_status(**overrides):
    status = {
        "schemaVersion": 1,
        "status": "ok",
        "sourceClaudeVersion": None,
        "sourceClaudePath": None,
        "installMode": "shim",
        "shimInstalled": False,
        "activeProfile": "default",
        "activePrompt": None,
        "desiredPatchIds": [],
        "activePatchIds": [],
        "rebuildRequired": False,
        "latestBuildReportPath": None,
        "activePatchSet": None,
        "currentClaudePath": None,
        "shimTargetPath": None,
        "installRecordPath": None,
        "stateDir": "/tmp/state",
        "logsDir": "/tmp/state/logs",
        "lastError": None,
    }
    status.update(overrides)
    return status


def test_parse_options_and_risk():
    options = {
        "schemaVersion": 1,
        "options": [
            {
                "id": "dangerous-permissions",
                "label": "Dangerous permissions",
                "kind": "option",
                "enabled": True,
                "valid": True,
                "compatibilityStatus": "compatible",
                "riskLevel": "high",
                "requiresConfirmation": True,
                "errors": [],
            }
        ],
    }
    state = parse_menu_state(
        _base_status(),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
        options,
    )
    item = state.option_items[0]
    assert item.option_id == "dangerous-permissions"
    assert item.risk_level == "high" and item.requires_confirmation is True


def test_high_risk_warnings_from_status():
    status = _base_status(
        highRiskOptions=[
            {
                "id": "dangerous-permissions",
                "label": "Dangerous permissions",
                "warning": "Dangerous permissions enabled",
            }
        ]
    )
    state = parse_menu_state(
        status,
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
        None,
    )
    assert "Dangerous permissions enabled" in state.high_risk_warnings


def test_options_none_tolerated():
    state = parse_menu_state(
        _base_status(),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
        None,
    )
    assert state.option_items == ()


def test_parse_menu_state_rejects_malformed_changed_modules():
    status = {
        "schemaVersion": 1,
        "status": "ok",
        "sourceClaudeVersion": None,
        "sourceClaudePath": None,
        "installMode": "shim",
        "shimInstalled": False,
        "activeProfile": "default",
        "activePrompt": None,
        "desiredPatchIds": [],
        "activePatchIds": [],
        "rebuildRequired": False,
        "latestBuildReportPath": None,
        "activePatchSet": None,
        "currentClaudePath": None,
        "shimTargetPath": None,
        "installRecordPath": None,
        "changedModules": [["path", "/tmp/not-object"]],
        "stateDir": "/tmp/state",
        "logsDir": "/tmp/state/logs",
        "lastError": None,
    }
    try:
        parse_menu_state(
            status,
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
        )
    except ValueError as exc:
        assert "changedModules items must be objects" in str(exc)
    else:
        raise AssertionError("expected changedModules validation")
