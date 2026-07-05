from __future__ import annotations

import json
from pathlib import Path

from harnessmonkey.cli import main


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def option_manifest(package_id: str, **overrides):
    payload = {
        "schemaVersion": 1,
        "kind": "option",
        "id": package_id,
        "label": package_id.replace("-", " ").title(),
        "description": "Option package",
        "risk": {"level": "low"},
        "option": {
            "argv": [],
            "env": {},
            "conflictsWithArgv": [],
            "conflictsWithOptions": [],
            "conflictsWithEnv": [],
        },
    }
    payload.update(overrides)
    return payload


def prompt_manifest(package_id: str, *, label: str | None = None):
    return {
        "schemaVersion": 1,
        "kind": "prompt",
        "id": package_id,
        "label": label or package_id.replace("-", " ").title(),
        "description": "Prompt package",
        "risk": {"level": "low"},
        "prompt": {"mode": "append", "source": {"path": "prompt.md"}},
    }


def make_executable(path: Path, text: str = "#!/bin/sh\necho claude\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


def configure_home(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    state = home / ".harnessmonkey"
    monkeypatch.setenv("HOME", str(home))
    official = make_executable(tmp_path / "official" / "claude")
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "installMode": "shim",
            "officialClaudePath": str(official),
            "profiles": {
                "default": {
                    "prompt": "research-prompt",
                    "patches": [],
                    "options": ["local-session-defaults"],
                }
            },
        },
    )
    return state, official


def write_prompt_package(state: Path) -> Path:
    package_dir = state / "prompts" / "research-prompt"
    package_dir.mkdir(parents=True)
    prompt = package_dir / "prompt.md"
    prompt.write_text("extra system prompt")
    write_json(package_dir / "research-prompt.json", prompt_manifest("research-prompt"))
    return prompt


def write_option_package(state: Path, payload: dict | None = None) -> None:
    package_dir = state / "options" / "local-session-defaults"
    manifest = payload or option_manifest(
        "local-session-defaults",
        label="Local Session Defaults",
        option={
            "argv": ["--model", "sonnet"],
            "env": {},
            "conflictsWithArgv": [],
            "conflictsWithOptions": [],
            "conflictsWithEnv": [],
        },
    )
    write_json(package_dir / "local-session-defaults.json", manifest)


def read_cli_json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_launch_preview_outputs_merged_argv_and_target(monkeypatch, tmp_path, capsys):
    state, official = configure_home(monkeypatch, tmp_path)
    prompt = write_prompt_package(state)
    write_option_package(state)

    code = main(["launch-preview", "--json", "--", "--resume"])

    assert code == 0
    assert read_cli_json(capsys) == {
        "schemaVersion": 1,
        "targetClaudePath": str(official.resolve()),
        "targetClaudeKind": "official_fallback",
        "argv": ["--append-system-prompt-file", str(prompt), "--model", "sonnet", "--resume"],
        "envPreview": {},
        "skipped": [],
        "warnings": [],
        "errors": [],
    }


def test_launch_preview_redacts_secret_env(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_prompt_package(state)
    write_option_package(
        state,
        option_manifest(
            "local-session-defaults",
            label="Local Session Defaults",
            option={
                "argv": [],
                "env": {"ANTHROPIC_API_KEY": {"value": "secret", "secret": True}},
                "conflictsWithArgv": [],
                "conflictsWithOptions": [],
                "conflictsWithEnv": [],
            },
        ),
    )

    code = main(["launch-preview", "--json"])

    assert code == 0
    payload = read_cli_json(capsys)
    assert payload["envPreview"] == {"ANTHROPIC_API_KEY": "<redacted>"}


def patch_manifest(package_id: str, *, label: str | None = None, **overrides):
    payload = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": package_id,
        "label": label or package_id.replace("-", " ").title(),
        "description": "Patch package",
        "risk": {"level": "low"},
        "patch": {"engine": "bun_graph_repack", "targets": []},
    }
    payload.update(overrides)
    return payload


def write_patch_package(state: Path, package_id: str = "fable-fallback", **overrides) -> None:
    write_json(
        state / "patches" / package_id / f"{package_id}.json",
        patch_manifest(package_id, **overrides),
    )


def write_invalid_package(
    state: Path, kind: str, folder: str, manifest_id: str = "different"
) -> None:
    bucket = {"option": "options", "prompt": "prompts", "patch": "patches"}[kind]
    payload = {
        "schemaVersion": 1,
        "kind": kind,
        "id": manifest_id,
        "label": "Invalid",
        "description": "Invalid package",
    }
    if kind == "option":
        payload["option"] = {
            "argv": [],
            "env": {},
            "conflictsWithArgv": [],
            "conflictsWithOptions": [],
            "conflictsWithEnv": [],
        }
    elif kind == "prompt":
        payload["prompt"] = {"mode": "append", "source": {"path": "prompt.md"}}
        (state / bucket / folder / "prompt.md").parent.mkdir(parents=True, exist_ok=True)
        (state / bucket / folder / "prompt.md").write_text("bad prompt")
    else:
        payload["patch"] = {"engine": "bun_graph_repack", "targets": []}
    write_json(state / bucket / folder / f"{folder}.json", payload)


def configure_package_lists(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    state = home / ".harnessmonkey"
    monkeypatch.setenv("HOME", str(home))
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "profiles": {
                "default": {
                    "prompt": "research-prompt",
                    "patches": ["fable-fallback"],
                    "options": ["local-session-defaults"],
                }
            },
        },
    )
    write_prompt_package(state)
    write_option_package(state)
    write_patch_package(state)
    write_invalid_package(state, "option", "bad-option")
    write_invalid_package(state, "prompt", "bad-prompt")
    write_invalid_package(state, "patch", "bad-patch")
    return state


_KIND_LIST_CASES = [
    (
        "list-options",
        "options",
        "bad-option",
        {
            "id": "local-session-defaults",
            "label": "Local Session Defaults",
            "kind": "option",
            "enabled": True,
            "valid": True,
            "compatibilityStatus": "unconstrained",
            "riskLevel": "low",
            "errors": [],
        },
    ),
    (
        "list-prompts",
        "prompts",
        "bad-prompt",
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
    ),
    (
        "list-patches",
        "patches",
        "bad-patch",
        {
            "id": "fable-fallback",
            "label": "Fable Fallback",
            "kind": "patch",
            "enabled": True,
            "valid": True,
            "compatibilityStatus": "unconstrained",
            "riskLevel": "low",
            "errors": [],
        },
    ),
]


def test_kind_list_commands_include_valid_and_invalid_packages(monkeypatch, tmp_path, capsys):
    configure_package_lists(monkeypatch, tmp_path)

    for command, collection, bad_id, valid_record in _KIND_LIST_CASES:
        assert main([command, "--json"]) == 0
        payload = read_cli_json(capsys)
        records = payload[collection]
        assert valid_record in records
        assert {
            "id": bad_id,
            "label": bad_id,
            "kind": valid_record["kind"],
            "enabled": False,
            "valid": False,
            "compatibilityStatus": "unknown",
            "riskLevel": "unknown",
            "errors": [f"id_must_match_folder: different != {bad_id}"],
        } in records


def test_plain_list_prompts_prints_v3_package_ids(monkeypatch, tmp_path, capsys):
    configure_package_lists(monkeypatch, tmp_path)

    assert main(["list-prompts"]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "research-prompt" in captured.out.splitlines()


def test_plain_list_patches_prints_v3_package_ids(monkeypatch, tmp_path, capsys):
    configure_package_lists(monkeypatch, tmp_path)

    assert main(["list-patches"]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "fable-fallback" in captured.out.splitlines()


def test_list_options_marks_active_invalid_package_enabled(monkeypatch, tmp_path, capsys):
    home = tmp_path / "home"
    state = home / ".harnessmonkey"
    monkeypatch.setenv("HOME", str(home))
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "profiles": {"default": {"prompt": None, "patches": [], "options": ["bad-option"]}},
        },
    )
    write_invalid_package(state, "option", "bad-option")

    assert main(["list-options", "--json"]) == 0

    records = read_cli_json(capsys)["options"]
    assert {
        "id": "bad-option",
        "label": "bad-option",
        "kind": "option",
        "enabled": True,
        "valid": False,
        "compatibilityStatus": "unknown",
        "riskLevel": "unknown",
        "errors": ["id_must_match_folder: different != bad-option"],
    } in records


def test_list_options_exposes_confirmation_metadata_for_high_risk_menu(
    monkeypatch, tmp_path, capsys
):
    home = tmp_path / "home"
    state = home / ".harnessmonkey"
    monkeypatch.setenv("HOME", str(home))
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "profiles": {
                "default": {
                    "prompt": None,
                    "patches": [],
                    "options": ["dangerous-permissions"],
                }
            },
        },
    )
    package_dir = state / "options" / "dangerous-permissions"
    write_json(
        package_dir / "dangerous-permissions.json",
        option_manifest(
            "dangerous-permissions",
            label="Dangerous permissions",
            risk={
                "level": "high",
                "requiresConfirmation": True,
                "statusWarning": "Dangerous permissions enabled",
            },
            option={
                "argv": ["--dangerously-skip-permissions"],
                "env": {},
                "conflictsWithArgv": [],
                "conflictsWithOptions": [],
                "conflictsWithEnv": [],
            },
        ),
    )

    assert main(["list-options", "--json"]) == 0

    [record] = read_cli_json(capsys)["options"]
    assert record["id"] == "dangerous-permissions"
    assert record["riskLevel"] == "high"
    assert record["requiresConfirmation"] is True
    assert record["statusWarning"] == "Dangerous permissions enabled"


def test_patch_and_prompt_mutation_commands_update_default_profile(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_patch_package(state, "fable-fallback")
    write_prompt_package(state)

    assert main(["enable-patch", "fable-fallback", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert json.loads((state / "config.json").read_text())["profiles"]["default"]["patches"] == [
        "fable-fallback"
    ]

    assert main(["disable-patch", "fable-fallback", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert json.loads((state / "config.json").read_text())["profiles"]["default"]["patches"] == []

    assert main(["set-prompt", "research-prompt", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True

    assert main(["clear-prompt", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert json.loads((state / "config.json").read_text())["profiles"]["default"]["prompt"] is None


def test_enable_patch_auto_enables_single_required_package(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_patch_package(state, "drawer-dock")
    write_patch_package(
        state, "thinking-drawer", requiresPackages=["drawer-dock"]
    )

    assert main(["enable-patch", "thinking-drawer", "--json"]) == 0
    payload = read_cli_json(capsys)
    assert payload["ok"] is True
    assert "drawer-dock" in payload["summary"]
    assert "required" in payload["summary"]
    config = json.loads((state / "config.json").read_text())
    assert config["profiles"]["default"]["patches"] == ["drawer-dock", "thinking-drawer"]


def test_enable_patch_auto_enables_transitive_requires_closure(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_patch_package(state, "drawer-dock")
    write_patch_package(state, "mid-layer", requiresPackages=["drawer-dock"])
    write_patch_package(state, "top-layer", requiresPackages=["mid-layer"])

    assert main(["enable-patch", "top-layer", "--json"]) == 0
    payload = read_cli_json(capsys)
    assert payload["ok"] is True
    config = json.loads((state / "config.json").read_text())
    patches = config["profiles"]["default"]["patches"]
    # both transitive dependencies land in the profile, before the patch that
    # pulled them in.
    assert set(patches) == {"drawer-dock", "mid-layer", "top-layer"}
    assert patches.index("drawer-dock") < patches.index("mid-layer") < patches.index(
        "top-layer"
    )


def test_enable_patch_does_not_duplicate_already_enabled_required_package(
    monkeypatch, tmp_path, capsys
):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_patch_package(state, "drawer-dock")
    write_patch_package(
        state, "thinking-drawer", requiresPackages=["drawer-dock"]
    )

    assert main(["enable-patch", "drawer-dock", "--json"]) == 0
    read_cli_json(capsys)
    assert main(["enable-patch", "thinking-drawer", "--json"]) == 0
    payload = read_cli_json(capsys)
    assert payload["ok"] is True
    # drawer-dock was already enabled, so nothing new was cascaded in --
    # the summary should not claim anything was auto-enabled alongside it.
    assert " (+ " not in payload["summary"]
    config = json.loads((state / "config.json").read_text())
    assert config["profiles"]["default"]["patches"] == ["drawer-dock", "thinking-drawer"]


def test_enable_patch_missing_required_package_refuses_with_clear_error(
    monkeypatch, tmp_path, capsys
):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_patch_package(
        state, "thinking-drawer", requiresPackages=["drawer-dock"]
    )

    assert main(["enable-patch", "thinking-drawer", "--json"]) == 1
    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_required_package"
    assert "drawer-dock" in payload["error"]["message"]
    config = json.loads((state / "config.json").read_text())
    # half-enabling must never happen: neither package lands in the profile.
    assert config["profiles"]["default"]["patches"] == []


def test_disable_patch_blocked_by_enabled_dependents(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_patch_package(state, "drawer-dock")
    write_patch_package(
        state, "thinking-drawer", requiresPackages=["drawer-dock"]
    )
    assert main(["enable-patch", "thinking-drawer", "--json"]) == 0
    read_cli_json(capsys)

    assert main(["disable-patch", "drawer-dock", "--json"]) == 1
    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "required_by_enabled_patches"
    assert "thinking-drawer" in payload["error"]["message"]
    config = json.loads((state / "config.json").read_text())
    assert config["profiles"]["default"]["patches"] == ["drawer-dock", "thinking-drawer"]


def test_disable_patch_blocked_by_multiple_enabled_dependents(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_patch_package(state, "drawer-dock")
    write_patch_package(
        state, "thinking-drawer", requiresPackages=["drawer-dock"]
    )
    write_patch_package(
        state, "hidden-context-drawer", requiresPackages=["drawer-dock"]
    )
    assert main(["enable-patch", "thinking-drawer", "--json"]) == 0
    read_cli_json(capsys)
    assert main(["enable-patch", "hidden-context-drawer", "--json"]) == 0
    read_cli_json(capsys)

    assert main(["disable-patch", "drawer-dock", "--json"]) == 1
    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "required_by_enabled_patches"
    assert "thinking-drawer" in payload["error"]["message"]
    assert "hidden-context-drawer" in payload["error"]["message"]


def test_disable_patch_allowed_once_dependent_is_disabled_first(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    write_patch_package(state, "drawer-dock")
    write_patch_package(
        state, "thinking-drawer", requiresPackages=["drawer-dock"]
    )
    assert main(["enable-patch", "thinking-drawer", "--json"]) == 0
    read_cli_json(capsys)

    assert main(["disable-patch", "thinking-drawer", "--json"]) == 0
    read_cli_json(capsys)
    assert main(["disable-patch", "drawer-dock", "--json"]) == 0
    payload = read_cli_json(capsys)
    assert payload["ok"] is True
    config = json.loads((state / "config.json").read_text())
    assert config["profiles"]["default"]["patches"] == []


def test_set_prompt_from_file_creates_package_manifest(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    source = tmp_path / "prompt-source.md"
    source.write_text("external prompt text")

    assert (
        main(["set-prompt", str(source), "--id", "research-prompt", "--from-file", "--json"]) == 0
    )
    assert read_cli_json(capsys)["ok"] is True

    package_dir = state / "prompts" / "research-prompt"
    copied_prompt = package_dir / "prompt.md"
    manifest = json.loads((package_dir / "research-prompt.json").read_text())
    assert copied_prompt.read_text() == "external prompt text"
    assert manifest["kind"] == "prompt"
    assert manifest["id"] == "research-prompt"
    assert manifest["prompt"]["source"]["path"] == "prompt.md"
    assert (
        json.loads((state / "config.json").read_text())["profiles"]["default"]["prompt"]
        == "research-prompt"
    )


def test_set_prompt_from_file_rejects_non_slug_id_before_writing(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)
    source = tmp_path / "prompt-source.md"
    source.write_text("external prompt text")

    assert main(["set-prompt", str(source), "--id", "../escape", "--from-file", "--json"]) == 1

    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_package_id"
    assert not (state / "escape").exists()
    assert not (state / "escape.json").exists()
    assert (
        json.loads((state / "config.json").read_text())["profiles"]["default"]["prompt"]
        == "research-prompt"
    )


def test_set_prompt_missing_v3_package_returns_single_error(monkeypatch, tmp_path, capsys):
    state, _official = configure_home(monkeypatch, tmp_path)

    assert main(["set-prompt", "missing-prompt", "--json"]) == 1

    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_package"
    config = json.loads((state / "config.json").read_text())
    assert config["profiles"]["default"]["prompt"] == "research-prompt"


def test_option_mutation_confirmation_ordering_and_conflicts(monkeypatch, tmp_path, capsys):
    home = tmp_path / "home"
    state = home / ".harnessmonkey"
    monkeypatch.setenv("HOME", str(home))
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "profiles": {"default": {"prompt": None, "patches": [], "options": ["first"]}},
        },
    )
    write_json(state / "options" / "first" / "first.json", option_manifest("first"))
    write_json(state / "options" / "second" / "second.json", option_manifest("second"))
    write_json(
        state / "options" / "high-risk" / "high-risk.json",
        option_manifest(
            "high-risk",
            risk={"level": "high", "requiresConfirmation": True},
        ),
    )
    write_json(
        state / "options" / "conflicting" / "conflicting.json",
        option_manifest(
            "conflicting",
            option={
                "argv": [],
                "env": {},
                "conflictsWithArgv": [],
                "conflictsWithOptions": ["first"],
                "conflictsWithEnv": [],
            },
        ),
    )

    assert main(["disable-option", "first", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert main(["enable-option", "second", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert main(["enable-option", "first", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert json.loads((state / "config.json").read_text())["profiles"]["default"]["options"] == [
        "second",
        "first",
    ]

    assert main(["enable-option", "high-risk", "--json"]) == 1
    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "confirmation_required"

    assert main(["enable-option", "high-risk", "--confirm", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True

    assert main(["enable-option", "conflicting", "--confirm", "--json"]) == 1
    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "option_conflict"
