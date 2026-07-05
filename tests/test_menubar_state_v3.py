from __future__ import annotations

from pathlib import Path

from harnessmonkey.menubar_state import parse_menu_state


def base_status(**overrides):
    status = {
        "schemaVersion": 1,
        "status": "ok",
        "activeProfile": "default",
        "activePrompt": "research-prompt",
        "desiredPatchIds": ["fable-fallback"],
        "builtPatchIds": ["fable-fallback"],
        "activePatchIds": ["fable-fallback"],
        "patchedBuildActive": True,
        "targetClaudeKind": "patched",
        "activeOptionIds": ["dangerous-permissions"],
        "highRiskOptions": [
            {
                "id": "dangerous-permissions",
                "label": "Dangerous permissions",
                "warning": "Dangerous permissions enabled",
            }
        ],
        "sourceClaudeVersion": "2.1.199",
        "sourceClaudePath": "/tmp/claude-source",
        "detectedClaudeCommandPath": "/tmp/bin/claude",
        "installMode": "shim",
        "shimInstalled": True,
        "compatibilityStatus": "compatible",
        "manifestCompatibilityStatus": "compatible",
        "sourceIdentityStatus": "compatible",
        "lastBuildCompatibilityStatus": "compatible",
        "liveValidationStatus": "unknown",
        "compatibilityWarnings": ["option dangerous-permissions requires confirmation"],
        "rebuildRequired": False,
        "latestBuildReportPath": "/tmp/state/build-report.json",
        "activePatchSet": "/tmp/state/patchsets/default",
        "currentClaudePath": "/tmp/state/current",
        "shimTargetPath": "/tmp/state/bin/claude",
        "installRecordPath": "/tmp/state/install-record.json",
        "lastBuildStrategy": "bun_graph_repack",
        "changedModules": [],
        "repackSummary": None,
        "stateDir": "/tmp/state",
        "logsDir": "/tmp/state/logs",
        "lastError": None,
    }
    status.update(overrides)
    return status


def test_parse_menu_state_captures_v3_status_and_option_payloads():
    state = parse_menu_state(
        base_status(
            launchPreviewAction={"command": "launch-preview"},
            refreshAction={"command": "refresh"},
        ),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
        {
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
                    "statusWarning": "Dangerous permissions enabled",
                },
                {
                    "id": "broken-option",
                    "label": "broken-option",
                    "kind": "option",
                    "enabled": False,
                    "valid": False,
                    "compatibilityStatus": "unknown",
                    "riskLevel": "unknown",
                    "errors": ["id_must_match_folder: different != broken-option"],
                },
            ],
        },
    )

    assert state.active_option_ids == ("dangerous-permissions",)
    assert state.built_patch_ids == ("fable-fallback",)
    assert state.patched_build_active is True
    assert state.target_claude_kind == "patched"
    assert state.compatibility_status == "compatible"
    assert state.manifest_compatibility_status == "compatible"
    assert state.source_identity_status == "compatible"
    assert state.last_build_compatibility_status == "compatible"
    assert state.live_validation_status == "unknown"
    assert state.compatibility_warnings == (
        "option dangerous-permissions requires confirmation",
    )
    assert state.high_risk_options[0].option_id == "dangerous-permissions"
    assert state.high_risk_options[0].id == "dangerous-permissions"
    assert state.high_risk_options[0].label == "Dangerous permissions"
    assert state.high_risk_options[0].warning == "Dangerous permissions enabled"

    assert len(state.option_items) == 2
    first = state.option_items[0]
    assert first.option_id == "dangerous-permissions"
    assert first.label == "Dangerous permissions"
    assert first.enabled is True
    assert first.valid is True
    assert first.compatibility_status == "compatible"
    assert first.risk_level == "high"
    assert first.requires_confirmation is True
    assert first.errors == ()
    assert first.status_warning == "Dangerous permissions enabled"
    second = state.option_items[1]
    assert second.option_id == "broken-option"
    assert second.enabled is False
    assert second.valid is False
    assert second.errors == ("id_must_match_folder: different != broken-option",)
    assert second.status_warning is None

    assert not hasattr(state, "launch_preview_action")
    assert not hasattr(state, "refresh_action")


def test_parse_menu_state_accepts_v3_patch_records_from_list_patches_payload():
    state = parse_menu_state(
        base_status(
            desiredPatchIds=["fable-fallback", "bad-patch"],
            activePatchIds=["fable-fallback"],
        ),
        {
            "schemaVersion": 1,
            "patches": [
                {
                    "id": "fable-fallback",
                    "label": "Fable Fallback",
                    "kind": "patch",
                    "enabled": True,
                    "valid": True,
                    "compatibilityStatus": "constrained",
                    "riskLevel": "low",
                    "errors": [],
                },
                {
                    "id": "legacy-active",
                    "label": "Legacy Active",
                    "kind": "patch",
                    "enabled": False,
                    "activeEnabled": True,
                    "valid": True,
                    "compatibilityStatus": "compatible",
                    "riskLevel": "low",
                    "errors": [],
                },
                {
                    "id": "bad-patch",
                    "label": "bad-patch",
                    "kind": "patch",
                    "enabled": True,
                    "valid": False,
                    "compatibilityStatus": "unknown",
                    "riskLevel": "unknown",
                    "errors": ["id_must_match_folder: different != bad-patch"],
                },
            ],
        },
        {"schemaVersion": 1, "prompts": []},
        {"schemaVersion": 1, "options": []},
    )

    first, legacy_active, invalid = state.patch_items
    assert first.patch_id == "fable-fallback"
    assert first.checked is True
    assert first.active_enabled is True
    assert first.available is True
    assert first.compatibility_status == "constrained"
    assert first.errors == ()

    assert legacy_active.patch_id == "legacy-active"
    assert legacy_active.checked is False
    assert legacy_active.active_enabled is True
    assert legacy_active.available is True
    assert legacy_active.compatibility_status == "compatible"
    assert legacy_active.errors == ()

    assert invalid.patch_id == "bad-patch"
    assert invalid.checked is True
    assert invalid.active_enabled is False
    assert invalid.available is False
    assert invalid.compatibility_status == "unknown"
    assert invalid.errors == ("id_must_match_folder: different != bad-patch",)


def test_parse_menu_state_accepts_v3_prompt_records_from_list_prompts_payload():
    state = parse_menu_state(
        base_status(activePrompt="status-prompt"),
        {"schemaVersion": 1, "patches": []},
        {
            "schemaVersion": 1,
            "prompts": [
                {
                    "id": "research-prompt",
                    "label": "Research Prompt",
                    "kind": "prompt",
                    "enabled": True,
                    "valid": True,
                    "compatibilityStatus": "unconstrained",
                    "riskLevel": "low",
                    "errors": [],
                },
                {
                    "id": "status-prompt",
                    "label": "Status Prompt",
                    "kind": "prompt",
                    "enabled": False,
                    "valid": True,
                    "compatibilityStatus": "unconstrained",
                    "riskLevel": "low",
                    "errors": [],
                },
            ],
        },
        {"schemaVersion": 1, "options": []},
    )

    enabled_prompt, status_prompt = state.prompt_items
    assert enabled_prompt.prompt_id == "research-prompt"
    assert enabled_prompt.checked is True
    assert enabled_prompt.mode == "append"
    assert enabled_prompt.source_path is None

    assert status_prompt.prompt_id == "status-prompt"
    assert status_prompt.checked is True
    assert status_prompt.mode == "append"
    assert status_prompt.source_path is None


def test_parse_menu_state_tolerates_missing_options_payload_for_v2_callers():
    state = parse_menu_state(
        base_status(activeOptionIds=[], highRiskOptions=[], builtPatchIds=[]),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
    )

    assert state.active_option_ids == ()
    assert state.high_risk_options == ()
    assert state.option_items == ()
    assert state.built_patch_ids == ()


def test_parse_menu_state_rejects_malformed_v3_status_fields():
    try:
        parse_menu_state(
            base_status(activeOptionIds="dangerous-permissions"),
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
            {"schemaVersion": 1, "options": []},
        )
    except ValueError as exc:
        assert "activeOptionIds must be a list" in str(exc)
    else:
        raise AssertionError("expected activeOptionIds validation")

    try:
        parse_menu_state(
            base_status(patchedBuildActive="true"),
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
            {"schemaVersion": 1, "options": []},
        )
    except ValueError as exc:
        assert "patchedBuildActive must be boolean" in str(exc)
    else:
        raise AssertionError("expected patchedBuildActive validation")

    try:
        parse_menu_state(
            base_status(highRiskOptions=["dangerous-permissions"]),
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
            {"schemaVersion": 1, "options": []},
        )
    except ValueError as exc:
        assert "highRiskOptions items must be objects" in str(exc)
    else:
        raise AssertionError("expected highRiskOptions validation")


def test_parse_menu_state_rejects_malformed_options_payload():
    try:
        parse_menu_state(
            base_status(),
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
            {"schemaVersion": 2, "options": []},
        )
    except ValueError as exc:
        assert "schemaVersion must be 1" in str(exc)
    else:
        raise AssertionError("expected options schema validation")

    try:
        parse_menu_state(
            base_status(),
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
            {"schemaVersion": 1, "options": "bad"},
        )
    except ValueError as exc:
        assert "options must be a list" in str(exc)
    else:
        raise AssertionError("expected options list validation")

    try:
        parse_menu_state(
            base_status(),
            {"schemaVersion": 1, "patches": []},
            {"schemaVersion": 1, "prompts": []},
            {
                "schemaVersion": 1,
                "options": [
                    {
                        "id": "dangerous-permissions",
                        "label": "Dangerous permissions",
                        "enabled": "true",
                        "valid": True,
                        "compatibilityStatus": "compatible",
                        "riskLevel": "high",
                        "errors": [],
                    }
                ],
            },
        )
    except ValueError as exc:
        assert "enabled must be boolean" in str(exc)
    else:
        raise AssertionError("expected option enabled validation")


def test_parse_menu_state_parses_last_managed_target_path_opportunistically():
    # `lastManagedTargetPath` is a CLI-side field landing in a parallel
    # worktree -- not present in today's real `status --json` output. It
    # must parse when present (forward-compat) and default to None when
    # absent (today's actual shape), never raising either way.
    with_field = parse_menu_state(
        base_status(lastManagedTargetPath="/tmp/state/bin/claude"),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
        {"schemaVersion": 1, "options": []},
    )
    assert with_field.last_managed_target_path == Path("/tmp/state/bin/claude")

    without_field = parse_menu_state(
        base_status(),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
        {"schemaVersion": 1, "options": []},
    )
    assert without_field.last_managed_target_path is None


def test_parse_menu_state_parses_shim_locked_opportunistically():
    # Shim lock feature: `shimLocked` is additive on the status payload.
    # Must parse when present and default to False when absent, never
    # raising either way (same pattern as `lastManagedTargetPath` above).
    with_field = parse_menu_state(
        base_status(shimLocked=True),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
        {"schemaVersion": 1, "options": []},
    )
    assert with_field.shim_locked is True

    without_field = parse_menu_state(
        base_status(),
        {"schemaVersion": 1, "patches": []},
        {"schemaVersion": 1, "prompts": []},
        {"schemaVersion": 1, "options": []},
    )
    assert without_field.shim_locked is False
