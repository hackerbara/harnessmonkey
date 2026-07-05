from __future__ import annotations

import json
from pathlib import Path

from harnessmonkey.paths import StatePaths
from harnessmonkey.shim_entry import compute_launch


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho claude\n")
    path.chmod(0o755)
    return path


def install_patched_current(state: Path) -> Path:
    paths = StatePaths(state_dir=state)
    patched = make_executable(paths.patchset_dir("2.1.199", "default") / "claude")
    paths.current_path.parent.mkdir(parents=True, exist_ok=True)
    paths.current_path.symlink_to(patched)
    return patched


def base_state(tmp_path: Path, *, prompt: str | None = None, options: list[str] | None = None):
    state = tmp_path / ".harnessmonkey"
    official = make_executable(tmp_path / "official" / "claude")
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "installMode": "shim",
            "officialClaudePath": str(official),
            "profiles": {
                "default": {"prompt": prompt, "patches": [], "options": options or []}
            },
        },
    )
    return state, official


def prompt_package(state: Path, package_id: str = "research") -> Path:
    package_dir = state / "prompts" / package_id
    prompt = package_dir / "prompt.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("extra prompt")
    write_json(
        package_dir / f"{package_id}.json",
        {
            "schemaVersion": 1,
            "kind": "prompt",
            "id": package_id,
            "label": "Research",
            "description": "Prompt package",
            "prompt": {"mode": "append", "source": {"path": "prompt.md"}},
        },
    )
    return prompt


def option_package(
    state: Path,
    package_id: str = "local-session-defaults",
    *,
    argv: list[str] | None = None,
    env: dict | None = None,
):
    package_dir = state / "options" / package_id
    write_json(
        package_dir / f"{package_id}.json",
        {
            "schemaVersion": 1,
            "kind": "option",
            "id": package_id,
            "label": "Local Session Defaults",
            "description": "Option package",
            "option": {
                "argv": argv or [],
                "env": env or {},
                "conflictsWithArgv": [],
                "conflictsWithOptions": [],
                "conflictsWithEnv": [],
            },
        },
    )


def test_compute_launch_appends_prompt(tmp_path):
    state, official = base_state(tmp_path, prompt="research")
    prompt = prompt_package(state, "research")

    result = compute_launch(state, ["--resume"], {"PATH": ""})

    assert result.target.path == official.resolve()
    assert result.target.kind == "official_fallback"
    assert result.argv == ["--append-system-prompt-file", str(prompt), "--resume"]
    assert result.errors == []


def test_compute_launch_merges_option_argv_and_env(tmp_path):
    state, _official = base_state(tmp_path, options=["local-session-defaults"])
    option_package(
        state,
        argv=["--model", "sonnet"],
        env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
    )

    result = compute_launch(state, ["--resume"], {"PATH": ""})

    assert result.argv == ["--model", "sonnet", "--resume"]
    assert result.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert result.errors == []


def test_compute_launch_skips_profile_for_management_invocation(tmp_path):
    state, _official = base_state(tmp_path, prompt="research", options=["local-session-defaults"])
    prompt_package(state, "research")
    option_package(state, argv=["--model", "sonnet"])

    result = compute_launch(state, ["--version"], {"PATH": ""})

    assert result.management is True
    assert result.target.kind == "official_management"
    assert result.argv == ["--version"]
    assert result.skipped == [
        {"kind": "launch_profile", "id": "default", "reason": "management_invocation"}
    ]


def test_compute_launch_management_prefers_configured_official_over_patched_current(
    tmp_path,
):
    state, official = base_state(tmp_path, prompt="research", options=["local-session-defaults"])
    patched = install_patched_current(state)
    prompt_package(state, "research")
    option_package(state, argv=["--model", "sonnet"])

    management = compute_launch(state, ["--help"], {"PATH": ""})
    normal = compute_launch(state, ["--resume"], {"PATH": ""})

    assert management.management is True
    assert management.target.kind == "official_management"
    assert management.target.path == official.resolve()
    assert management.argv == ["--help"]

    assert normal.management is False
    assert normal.target.kind == "patched"
    assert normal.target.path == patched.resolve()


def test_compute_launch_uses_official_fallback_when_current_missing(tmp_path):
    state, official = base_state(tmp_path)

    result = compute_launch(state, [], {"PATH": ""})

    assert result.target.path == official.resolve()
    assert result.target.kind == "official_fallback"
    assert result.errors == []


def test_compute_launch_rejects_recursive_current_target(tmp_path):
    state = tmp_path / ".harnessmonkey"
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "installMode": "shim",
            "officialClaudePath": str(state / "current"),
            "profiles": {"default": {"prompt": None, "patches": [], "options": []}},
        },
    )

    result = compute_launch(state, [], {"PATH": ""})

    assert result.target.kind == "missing"
    assert result.errors == ["no launch target found"]
