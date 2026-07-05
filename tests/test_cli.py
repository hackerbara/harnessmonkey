from __future__ import annotations

import hashlib
import json

import pytest
from harnessmonkey.cli import main


def unsupported_legacy_manifest() -> dict:
    return {
        "schemaVersion": 1,
        "id": "example-patch",
        "name": "Example Patch",
        "description": "Example declarative patch",
        "packageVersion": "0.1.0",
        "targets": [
            {
                "sourceIdentity": {
                    "claudeVersion": "2.1.198",
                    "versionOutput": "2.1.198 (Claude Code)",
                    "sha256": "a" * 64,
                    "sizeBytes": 100,
                    "platform": "darwin",
                    "arch": "arm64",
                },
                "operations": [],
            }
        ],
    }


def test_cli_version(capsys):
    assert main(["--version"]) == 0
    assert "0.1.0" in capsys.readouterr().out


def test_status_prints_state_dir(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert ".harnessmonkey" in out


def test_enable_and_disable_patch_mutate_default_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["enable", "fable-fallback"]) == 0
    assert main(["disable", "fable-fallback"]) == 0


def test_high_impact_commands_require_explicit_targets_or_inputs(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    for command in ["build", "install-shim", "uninstall-shim", "rollback", "use-official"]:
        assert main([command]) in {1, 2}
    err = capsys.readouterr().err
    assert "not implemented" not in err


def test_enable_rejects_missing_active_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = tmp_path / ".harnessmonkey" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"activeProfile":"missing","profiles":{}}\n')
    with pytest.raises(ValueError, match="only_default_profile_supported"):
        main(["enable", "fable-fallback"])


def test_cli_build_with_explicit_source_and_package(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude-source"
    source.write_bytes(b"HEAD case\"a\":{OLD_A_BODY} case\"b\":{OLD_B_BODY} TAIL")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    package = tmp_path / "patches" / "example-patch"
    package.mkdir(parents=True)
    data = unsupported_legacy_manifest()
    data["targets"][0]["sourceIdentity"]["sha256"] = source_sha
    data["targets"][0]["sourceIdentity"]["sizeBytes"] = source.stat().st_size
    (package / "patch.json").write_text(json.dumps(data))
    out_dir = tmp_path / "out"
    assert (
        main(
            [
                "build",
                "--source",
                str(source),
                "--package",
                str(package),
                "--output-dir",
                str(out_dir),
                "--source-version",
                "2.1.198",
                "--source-version-output",
                "2.1.198 (Claude Code)",
                "--platform",
                "darwin",
                "--arch",
                "arm64",
                "--skip-signing",
                "--skip-smoke",
            ]
        )
        == 1
    )
    assert not (out_dir / "claude").exists()
    out = capsys.readouterr().out
    assert "failed" in out
    assert "unsupported_manifest_format: expected schemaVersion 1 with kind" in out


def test_cli_use_official_updates_current_symlink(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    official = tmp_path / "official"
    official.write_text("official")
    assert main(["use-official", "--official", str(official)]) == 0
    assert (tmp_path / ".harnessmonkey" / "current").resolve() == official.resolve()


def test_cli_install_shim_dry_run_has_no_side_effects(tmp_path):
    target = tmp_path / "claude"
    target.write_text("official")
    assert (
        main(
            [
                "install-shim",
                "--target",
                str(target),
                "--state-dir",
                str(tmp_path / "state"),
                "--dry-run",
            ]
        )
        == 0
    )
    assert target.read_text() == "official"
    assert not (tmp_path / "state").exists()


def test_doctor_warns_when_config_source_differs_from_install_record(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path))
    state = tmp_path / ".harnessmonkey"
    state.mkdir(parents=True)
    newer = tmp_path / "versions" / "2.1.201" / "claude"
    older = tmp_path / "versions" / "2.1.199" / "claude"
    for binary in (newer, older):
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"claude")
        binary.chmod(0o755)
    (state / "install-record.json").write_text(
        json.dumps(
            {
                "owner": "HarnessMonkey managed shim",
                "targetPath": str(tmp_path / "bin" / "claude"),
                "sourcePath": str(newer),
            }
        )
    )
    (state / "config.json").write_text(
        json.dumps({"schemaVersion": 1, "activeProfile": "default", "profiles": {"default": {}}, "officialClaudePath": str(older)})
    )
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "officialClaudePath" in out
    assert "install record" in out
    assert str(newer) in out


def test_doctor_quiet_when_config_source_matches_install_record(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path))
    state = tmp_path / ".harnessmonkey"
    state.mkdir(parents=True)
    binary = tmp_path / "versions" / "2.1.201" / "claude"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"claude")
    binary.chmod(0o755)
    (state / "install-record.json").write_text(
        json.dumps(
            {
                "owner": "HarnessMonkey managed shim",
                "targetPath": str(tmp_path / "bin" / "claude"),
                "sourcePath": str(binary),
            }
        )
    )
    (state / "config.json").write_text(
        json.dumps({"schemaVersion": 1, "activeProfile": "default", "profiles": {"default": {}}, "officialClaudePath": str(binary)})
    )
    assert main(["doctor"]) == 0
    assert "differs" not in capsys.readouterr().out
