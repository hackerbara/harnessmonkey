from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from harnessmonkey.cli import main
from harnessmonkey.package_model import PackageKind, load_package_manifest, manifest_digest


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def make_executable(path: Path, text: str = "#!/bin/sh\necho fixture\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


def read_cli_json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def prompt_manifest(package_id: str) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "prompt",
        "id": package_id,
        "label": "Research",
        "description": "Research prompt",
        "risk": {"level": "low"},
        "prompt": {"mode": "append", "source": {"path": "prompt.md"}},
    }


def option_manifest(package_id: str) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "option",
        "id": package_id,
        "label": "Local Session Defaults",
        "description": "Local option",
        "risk": {"level": "low"},
        "option": {
            "argv": ["--model", "sonnet"],
            "env": {},
            "conflictsWithArgv": [],
            "conflictsWithOptions": [],
            "conflictsWithEnv": [],
        },
    }


def patch_manifest(package_id: str) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "patch",
        "id": package_id,
        "label": "Fable Fallback",
        "description": "Patch package",
        "risk": {"level": "low"},
        "patch": {"engine": "bun_graph_repack", "targets": []},
    }


def seed_prompt_package(state: Path) -> Path:
    prompt_dir = state / "prompts" / "research"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "prompt.md"
    prompt_path.write_text("research prompt")
    write_json(prompt_dir / "research.json", prompt_manifest("research"))
    return prompt_path


def seed_option_package(state: Path) -> None:
    write_json(
        state / "options" / "local-session-defaults" / "local-session-defaults.json",
        option_manifest("local-session-defaults"),
    )


def seed_patch_package(state: Path, package_id: str) -> str:
    package_dir = state / "patches" / package_id
    write_json(package_dir / f"{package_id}.json", patch_manifest(package_id))
    return manifest_digest(load_package_manifest(package_dir, PackageKind.PATCH))


def test_prompt_option_acceptance_flow(monkeypatch, tmp_path, capsys):
    home = tmp_path / "home"
    state = home / ".harnessmonkey"
    monkeypatch.setenv("HOME", str(home))
    official = make_executable(tmp_path / "official" / "claude")
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "officialClaudePath": str(official),
            "profiles": {"default": {"prompt": None, "patches": [], "options": []}},
        },
    )
    prompt_path = seed_prompt_package(state)
    seed_option_package(state)

    assert main(["list-prompts", "--json"]) == 0
    assert read_cli_json(capsys)["prompts"][0]["id"] == "research"
    assert main(["list-options", "--json"]) == 0
    assert read_cli_json(capsys)["options"][0]["id"] == "local-session-defaults"

    assert main(["set-prompt", "research", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert main(["enable-option", "local-session-defaults", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True

    assert main(["launch-preview", "--json", "--", "--resume"]) == 0
    preview = read_cli_json(capsys)
    assert preview["argv"] == [
        "--append-system-prompt-file",
        str(prompt_path),
        "--model",
        "sonnet",
        "--resume",
    ]

    assert main(["status", "--json"]) == 0
    status = read_cli_json(capsys)
    assert status["activePrompt"] == "research"
    assert status["activeOptionIds"] == ["local-session-defaults"]

    assert main(["clear-prompt", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert main(["disable-option", "local-session-defaults", "--json"]) == 0
    assert read_cli_json(capsys)["ok"] is True
    assert main(["launch-preview", "--json", "--", "--resume"]) == 0
    preview = read_cli_json(capsys)
    assert preview["argv"] == ["--resume"]


def test_report_status_acceptance_with_patched_current_and_official_fallback(
    monkeypatch, tmp_path, capsys
):
    home = tmp_path / "home"
    state = home / ".harnessmonkey"
    monkeypatch.setenv("HOME", str(home))
    official = make_executable(
        tmp_path / "official" / "claude",
        "#!/bin/sh\necho '2.1.199 (Claude Code)'\n",
    )
    patch_id = "fable-fallback"
    digest = seed_patch_package(state, patch_id)
    patchset = state / "versions" / "2.1.199" / "patchsets" / "default"
    patched = make_executable(patchset / "claude", "#!/bin/sh\necho patched\n")
    source_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    write_json(
        state / "config.json",
        {
            "schemaVersion": 1,
            "activeProfile": "default",
            "activePatchSet": str(patchset),
            "officialClaudePath": str(official),
            "profiles": {"default": {"prompt": None, "patches": [patch_id], "options": []}},
        },
    )
    write_json(
        patchset / "build-report.json",
        {
            "schemaVersion": 3,
            "status": "verified",
            "enabledPatches": [patch_id],
            "packageManifestDigests": {patch_id: digest},
            "sourceClaudePath": str(official),
            "sourceVersion": "2.1.199",
            "sourceSha256": source_sha,
            "sourceIdentity": {
                "claudeVersion": "2.1.199",
                "versionOutput": "2.1.199 (Claude Code)",
                "sha256": source_sha,
                "sizeBytes": official.stat().st_size,
                "platform": "darwin",
                "arch": "arm64",
            },
            "buildInputSnapshot": {
                "patches": [patch_id],
                "promptAtBuildTime": None,
                "optionsAtBuildTime": [],
            },
            "compatibility": {"status": "compatible", "warnings": []},
        },
    )
    os.symlink(patched, state / "current")

    assert main(["status", "--json"]) == 0
    status = read_cli_json(capsys)
    assert status["patchedBuildActive"] is True
    assert status["targetClaudeKind"] == "patched"
    assert status["builtPatchIds"] == [patch_id]
    assert status["activePatchIds"] == [patch_id]
    assert status["rebuildRequired"] is False

    (state / "current").unlink()
    assert main(["status", "--json"]) == 0
    status = read_cli_json(capsys)
    assert status["targetClaudeKind"] == "official_fallback"
    assert status["patchedBuildActive"] is False
    assert status["activePatchIds"] == []
    assert status["rebuildRequired"] is True
