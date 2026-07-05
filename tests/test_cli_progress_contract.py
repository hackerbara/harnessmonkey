from __future__ import annotations

import json

import pytest

from harnessmonkey import cli
from harnessmonkey.reports_v2 import BuildReportV2


def _minimal_verified_report(tmp_path):
    """Mirrors the fake-report style in tests/test_cli_v15.py: a BuildReportV2 that
    satisfies handle_build's json-payload path without needing a real build."""
    return BuildReportV2(
        status="verified",
        automatedStatus="passed",
        sourceClaudePath=str(tmp_path / "claude-source"),
        sourceVersion="fixture",
        sourceVersionOutput="fixture (Claude Code)",
        activationEligible=True,
        activationStatus="skipped",
        enabledPatches=["demo-patch"],
    )


def _build_argv(tmp_path, *, extra=()):
    source = tmp_path / "claude-source"
    if not source.exists():
        source.write_bytes(b"source")
    package = tmp_path / "demo-patch"
    package.mkdir(exist_ok=True)
    return [
        "build",
        "--source",
        str(source),
        "--package",
        str(package),
        "--output-dir",
        str(tmp_path / "out"),
        "--source-version",
        "fixture",
        "--source-version-output",
        "fixture (Claude Code)",
        *extra,
    ]


def _fake_build(monkeypatch, tmp_path):
    """Monkeypatch build_patchset_v15 to a fake that emits two events and succeeds."""

    def fake(request):
        if request.on_event:
            request.on_event({"event": "stage", "id": "resolve", "status": "running"})
            request.on_event({"event": "stage", "id": "resolve", "status": "done"})
        request.output_dir.mkdir(parents=True, exist_ok=True)
        return _minimal_verified_report(tmp_path)

    # ADAPT: cli.py imports build_patchset_v15 by name (`from harnessmonkey.builder_v15
    # import build_patchset_v15`) and calls it unqualified, so patch the attribute on the
    # cli module itself (mirrors tests/test_cli_v15.py's
    # monkeypatch.setattr("harnessmonkey.cli.build_patchset_v15", fake_build)).
    monkeypatch.setattr(cli, "build_patchset_v15", fake)


def test_stdout_byte_identical_with_and_without_progress(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _fake_build(monkeypatch, tmp_path)

    assert cli.main(_build_argv(tmp_path, extra=["--json"])) == 0
    plain = capsys.readouterr().out

    assert cli.main(_build_argv(tmp_path, extra=["--json", "--progress"])) == 0
    with_progress = capsys.readouterr()

    assert with_progress.out == plain
    lines = [line for line in with_progress.err.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    assert {"event": "stage", "id": "resolve", "status": "done"} in events


def test_progress_lines_are_valid_json_objects(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _fake_build(monkeypatch, tmp_path)

    assert cli.main(_build_argv(tmp_path, extra=["--json", "--progress"])) == 0
    for line in capsys.readouterr().err.splitlines():
        if line.strip():
            assert isinstance(json.loads(line), dict)


def test_progress_not_enabled_without_flag(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _fake_build(monkeypatch, tmp_path)

    assert cli.main(_build_argv(tmp_path, extra=["--json"])) == 0
    assert capsys.readouterr().err == ""


def test_build_dry_run_with_progress_emits_no_stage_events(monkeypatch, tmp_path, capsys):
    # Dry-run build never calls build_patchset_v15 at all, so --progress must not
    # invent events beyond what the (unexecuted) transaction would emit.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    called = False

    def fail_if_called(request):
        nonlocal called
        called = True
        raise AssertionError("build_patchset_v15 should not run in --dry-run")

    monkeypatch.setattr(cli, "build_patchset_v15", fail_if_called)

    assert (
        cli.main(_build_argv(tmp_path, extra=["--json", "--dry-run", "--progress"])) == 0
    )
    assert called is False
    assert capsys.readouterr().err == ""


def test_install_shim_progress_events_and_stdout_byte_identity(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    plain_target = tmp_path / "plain" / "claude"
    assert (
        cli.main(["install-shim", "--target", str(plain_target), "--json"]) == 0
    )
    plain = capsys.readouterr().out

    progress_target = tmp_path / "progress" / "claude"
    assert (
        cli.main(["install-shim", "--target", str(progress_target), "--json", "--progress"])
        == 0
    )
    with_progress = capsys.readouterr()

    # stdout differs only by the disposable target path baked into the envelope;
    # normalize it before comparing so the assertion checks structure, not the path.
    normalized_out = with_progress.out.replace(str(progress_target), str(plain_target))
    assert normalized_out == plain

    lines = [line for line in with_progress.err.splitlines() if line.strip()]
    assert lines, "expected at least one progress event on stderr"
    events = [json.loads(line) for line in lines]
    for event in events:
        assert isinstance(event, dict)
    stage_ids = {event["id"] for event in events if event.get("event") == "stage"}
    assert "preflight" in stage_ids
    assert "swap" in stage_ids


def test_install_shim_without_progress_flag_emits_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = tmp_path / "claude"
    assert cli.main(["install-shim", "--target", str(target), "--json"]) == 0
    assert capsys.readouterr().err == ""


def test_uninstall_shim_progress_events_and_stdout_byte_identity(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    target = tmp_path / "claude"
    assert cli.main(["install-shim", "--target", str(target), "--json"]) == 0
    capsys.readouterr()

    assert cli.main(["uninstall-shim", "--target", str(target), "--json"]) == 0
    plain = capsys.readouterr().out

    assert cli.main(["install-shim", "--target", str(target), "--json"]) == 0
    capsys.readouterr()

    assert (
        cli.main(["uninstall-shim", "--target", str(target), "--json", "--progress"]) == 0
    )
    with_progress = capsys.readouterr()

    assert with_progress.out == plain
    lines = [line for line in with_progress.err.splitlines() if line.strip()]
    assert lines, "expected at least one progress event on stderr"
    events = [json.loads(line) for line in lines]
    stage_ids = {event["id"] for event in events if event.get("event") == "stage"}
    assert "preflight" in stage_ids


def test_rollback_has_no_progress_flag(tmp_path):
    # --progress is scoped to build/install-shim/uninstall-shim only; rollback shares
    # handle_restore but was not in scope for this task.
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["rollback", "--progress"])
