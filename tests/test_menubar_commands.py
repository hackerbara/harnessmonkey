from __future__ import annotations

import json
import sys
import time

import pytest

from harnessmonkey.menubar_commands import CommandRunner, MutatingCommandBusy


def test_runner_uses_argv_list_and_shell_false(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))

        class Result:
            returncode = 0
            stdout = json.dumps(
                {
                    "schemaVersion": 1,
                    "ok": True,
                    "status": "ok",
                    "summary": "ok",
                    "reportPath": None,
                    "dryRun": False,
                    "plannedActions": [],
                    "error": None,
                }
            )
            stderr = ""

        return Result()

    runner = CommandRunner(
        cli_argv=[sys.executable, "-m", "harnessmonkey"], logs_dir=tmp_path, run=fake_run
    )
    runner.run_json(["status", "--json"], mutating=False)
    argv, kwargs = calls[0]
    assert isinstance(argv, list)
    assert kwargs["shell"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


def test_mutating_commands_are_serialized(tmp_path):
    runner = CommandRunner(cli_argv=["harnessmonkey"], logs_dir=tmp_path, run=lambda *a, **k: None)
    runner.mark_busy_for_test()
    try:
        try:
            runner.run_json(["enable", "x", "--json"], mutating=True)
        except MutatingCommandBusy:
            pass
        else:
            raise AssertionError("expected busy")
    finally:
        runner.clear_busy_for_test()


def test_worker_queue_boundary(tmp_path):
    runner = CommandRunner(cli_argv=[sys.executable, "-c"], logs_dir=tmp_path)
    runner.post_result_for_test("refresh", {"ok": True})
    assert runner.drain_results() == [("refresh", {"ok": True})]


def test_open_path_does_not_prefix_harnessmonkey(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    runner = CommandRunner(cli_argv=["harnessmonkey"], logs_dir=tmp_path, run=fake_run)
    runner.open_path(tmp_path / "logs")
    argv, kwargs = calls[0]
    assert argv == ["open", str(tmp_path / "logs")]
    assert kwargs["shell"] is False


def test_nonzero_json_error_envelope_is_preserved(tmp_path):
    def fake_run(argv, **kwargs):
        class Result:
            returncode = 1
            stdout = json.dumps(
                {
                    "schemaVersion": 1,
                    "ok": False,
                    "status": "error",
                    "summary": "authorization denied",
                    "reportPath": None,
                    "targetPath": "/usr/local/bin/claude",
                    "authorizationRequired": True,
                    "authorizationMethod": "macos_gui",
                    "dryRun": False,
                    "plannedActions": [],
                    "error": {
                        "message": "authorization denied",
                        "code": "authorization_denied",
                    },
                }
            )
            stderr = ""

        return Result()

    runner = CommandRunner(cli_argv=["harnessmonkey"], logs_dir=tmp_path, run=fake_run)
    payload = runner.run_json(
        ["install-shim", "--target", "/usr/local/bin/claude", "--json"], mutating=True
    )
    assert payload["error"]["code"] == "authorization_denied"
    assert payload["authorizationRequired"] is True
    assert payload["targetPath"] == "/usr/local/bin/claude"


def test_default_runner_bounds_subprocess_output_before_error_envelope(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("harnessmonkey.menubar_commands.MAX_CAPTURE_CHARS", 32)
    runner = CommandRunner(cli_argv=[sys.executable, "-c"], logs_dir=tmp_path)

    payload = runner.run_json(
        ["import sys; sys.stderr.write('x' * 10_000); sys.exit(1)"], mutating=False
    )

    assert payload["error"]["code"] == "command_failed"
    assert payload["error"]["message"] == "x" * 32
    logged = json.loads(runner.log_path.read_text().splitlines()[-1])
    assert logged["stderr"] == "x" * 32


FAKE_STREAMING_CLI = [
    sys.executable,
    "-c",
    (
        "import json,sys,time;"
        "print(json.dumps({'event':'stage','id':'a','status':'running'}),file=sys.stderr,flush=True);"
        "print('garbage line',file=sys.stderr,flush=True);"
        "print(json.dumps({'schemaVersion':1,'ok':True,'status':'ok','summary':'done'}))"
    ),
]


def test_run_streaming_events_and_result(tmp_path):
    runner = CommandRunner(cli_argv=FAKE_STREAMING_CLI[:2], logs_dir=tmp_path)
    events: list[dict] = []
    handle = runner.run_streaming("build", FAKE_STREAMING_CLI[2:], on_event=events.append)
    handle.process.wait(timeout=10)
    deadline = time.time() + 5
    results = []
    while not results and time.time() < deadline:
        results = runner.drain_results()
        time.sleep(0.05)
    assert events[0] == {"event": "stage", "id": "a", "status": "running"}
    assert {"event": "log", "stage": None, "line": "garbage line"} in events
    assert results[0][1]["ok"] is True


def test_cancel_kills_process_group(tmp_path):
    sleeper = ["-c", "import time; time.sleep(60)"]
    runner = CommandRunner(cli_argv=[sys.executable], logs_dir=tmp_path)
    handle = runner.run_streaming("build", sleeper, on_event=lambda e: None)
    handle.cancel(grace_seconds=1.0)
    assert handle.process.wait(timeout=10) != 0


def test_run_streaming_respects_mutating_lock(tmp_path):
    runner = CommandRunner(cli_argv=[sys.executable], logs_dir=tmp_path)
    handle = runner.run_streaming(
        "build", ["-c", "import time; time.sleep(5)"], on_event=lambda e: None
    )
    with pytest.raises(MutatingCommandBusy):
        runner.run_streaming("build", ["-c", "pass"], on_event=lambda e: None)
    handle.cancel(grace_seconds=0.5)
    handle.process.wait(timeout=10)


def test_run_streaming_respects_busy_for_test_flag(tmp_path):
    runner = CommandRunner(cli_argv=[sys.executable], logs_dir=tmp_path)
    runner.mark_busy_for_test()
    try:
        with pytest.raises(MutatingCommandBusy):
            runner.run_streaming("build", ["-c", "pass"], on_event=lambda e: None)
    finally:
        runner.clear_busy_for_test()


def test_run_streaming_on_event_exception_does_not_abort_stream(tmp_path):
    runner = CommandRunner(cli_argv=FAKE_STREAMING_CLI[:2], logs_dir=tmp_path)
    events: list[dict] = []
    call_count = {"n": 0}

    def flaky_on_event(evt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom from a bad GUI callback")
        events.append(evt)

    handle = runner.run_streaming("build", FAKE_STREAMING_CLI[2:], on_event=flaky_on_event)
    handle.process.wait(timeout=10)
    deadline = time.time() + 5
    results = []
    while not results and time.time() < deadline:
        results = runner.drain_results()
        time.sleep(0.05)
    assert {"event": "log", "stage": None, "line": "garbage line"} in events
    assert results[0][1]["ok"] is True


ORPHAN_GRANDCHILD_CLI = [
    sys.executable,
    "-c",
    (
        "import json,subprocess,sys;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)']);"
        "print(json.dumps({'schemaVersion':1,'ok':True,'status':'ok','summary':'done'}))"
    ),
]


def test_run_streaming_bounded_join_survives_orphaned_grandchild(monkeypatch, tmp_path):
    # A grandchild that inherits the stdout/stderr pipe fds keeps them open
    # (no EOF) even after our immediate child exits. Python's buffered
    # TextIOWrapper.read(8192) blocks trying to fill the full chunk rather
    # than returning the short write early, so the reader threads genuinely
    # cannot finish here -- the fix under test is that finalize() stops
    # waiting on them (bounded join), still queues a best-effort payload
    # noting the truncation, and -- most importantly -- releases the
    # mutating lock instead of holding it forever.
    monkeypatch.setattr("harnessmonkey.menubar_commands.READER_JOIN_TIMEOUT_SECONDS", 0.3)
    runner = CommandRunner(cli_argv=ORPHAN_GRANDCHILD_CLI[:1], logs_dir=tmp_path)
    handle = runner.run_streaming("build", ORPHAN_GRANDCHILD_CLI[1:], on_event=lambda e: None)
    handle.process.wait(timeout=10)

    deadline = time.time() + 5
    results = []
    while not results and time.time() < deadline:
        results = runner.drain_results()
        time.sleep(0.05)
    assert results, "a best-effort result should be queued even though a grandchild kept pipes open"
    assert results[0][0] == "build"

    logged = json.loads(runner.log_path.read_text().splitlines()[-1])
    assert "reader thread still running" in logged["stderr"]

    # Lock must have been released despite the leaked pipe fds still being open.
    deadline = time.time() + 5
    second_handle = None
    last_error: Exception | None = None
    while second_handle is None and time.time() < deadline:
        try:
            second_handle = runner.run_streaming("build", ["-c", "pass"], on_event=lambda e: None)
        except MutatingCommandBusy as exc:
            last_error = exc
            time.sleep(0.05)
    assert second_handle is not None, f"lock never released: {last_error}"
    second_handle.process.wait(timeout=10)


def test_runner_logs_stdout_summary_for_json_error_payload(tmp_path):
    def fake_run(argv, **kwargs):
        class Result:
            returncode = 2
            stdout = json.dumps(
                {
                    "schemaVersion": 1,
                    "ok": False,
                    "status": "error",
                    "summary": "build requires enabled patches or at least one --package",
                    "reportPath": None,
                    "targetPath": None,
                    "authorizationRequired": False,
                    "authorizationMethod": None,
                    "dryRun": False,
                    "plannedActions": [],
                    "error": {
                        "message": "build requires enabled patches",
                        "code": "missing_package",
                    },
                }
            )
            stderr = ""

        return Result()

    runner = CommandRunner(cli_argv=["harnessmonkey"], logs_dir=tmp_path, run=fake_run)

    payload = runner.run_json(["build", "--json"], mutating=True)

    assert payload["error"]["code"] == "missing_package"
    logged = json.loads(runner.log_path.read_text().splitlines()[-1])
    assert "missing_package" in logged["stdout"]
    assert "build requires enabled patches" in logged["stdout"]
