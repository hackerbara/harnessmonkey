from __future__ import annotations

import json

from harnessmonkey.cli import main


def read_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_v2_contract_acceptance_uses_one_disposable_home(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude-patches" / "fable-fallback").mkdir(parents=True)
    (tmp_path / ".harnessmonkey" / "prompts").mkdir(parents=True)
    (tmp_path / ".harnessmonkey" / "prompts" / "research.json").write_text(
        '{"id":"research","name":"Research","sourcePath":"/tmp/research.md","mode":"append"}\n'
    )

    assert main(["status", "--json"]) == 0
    assert read_json(capsys)["schemaVersion"] == 1

    assert main(["enable", "fable-fallback", "--json"]) == 0
    assert read_json(capsys)["ok"] is True

    assert main(["disable", "fable-fallback", "--json"]) == 0
    assert read_json(capsys)["ok"] is True

    prompt_source = tmp_path / ".harnessmonkey" / "prompts" / "research.md"
    prompt_source.write_text("Prompt text")
    assert (
        main(["set-prompt", str(prompt_source), "--id", "research", "--from-file", "--json"])
        == 0
    )
    assert read_json(capsys)["ok"] is True

    assert main(["clear-prompt", "--json"]) == 0
    assert read_json(capsys)["ok"] is True

    shim_target = tmp_path / ".harnessmonkey" / "bin" / "claude"
    for command in (
        ["build", "--json", "--dry-run"],
        ["install-shim", "--target", str(shim_target), "--json", "--dry-run"],
        ["uninstall-shim", "--target", str(shim_target), "--json", "--dry-run"],
    ):
        assert main(command) == 0
        payload = read_json(capsys)
        assert payload["dryRun"] is True
        assert isinstance(payload["plannedActions"], list)

    for command in (
        ["install-shim", "--target", str(shim_target), "--json"],
        ["uninstall-shim", "--target", str(shim_target), "--json"],
    ):
        assert main(command) == 0
        payload = read_json(capsys)
        assert payload["dryRun"] is False
        assert payload["targetPath"] == str(shim_target)
