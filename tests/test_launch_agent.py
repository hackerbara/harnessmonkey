import plistlib
from pathlib import Path

import pytest

from harnessmonkey.launch_agent import (
    APP_MARKER_NAME,
    LAUNCH_AGENT_LABEL,
    agent_plist_path,
    app_gui_executable,
    app_venv_dir,
    install_agent,
    provision_app_venv,
    render_plist,
    uninstall_agent,
)


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return type("R", (), {"ok": True, "returncode": 0, "stdout": "", "stderr": ""})()


class FailOnCallRunner:
    """Runner whose call at index `fail_on` returns a failure result; every
    other call succeeds. Used to exercise provisioning failure branches."""

    def __init__(self, fail_on: int):
        self.calls = []
        self._fail_on = fail_on

    def __call__(self, argv):
        index = len(self.calls)
        self.calls.append(argv)
        if index == self._fail_on:
            return type(
                "R", (), {"ok": False, "returncode": 1, "stdout": "", "stderr": "boom"}
            )()
        return type("R", (), {"ok": True, "returncode": 0, "stdout": "", "stderr": ""})()


def test_render_plist_shape(tmp_path):
    data = plistlib.loads(render_plist(Path("/venv/bin/harnessmonkey-gui"), home=tmp_path))
    assert data["Label"] == LAUNCH_AGENT_LABEL
    assert data["ProgramArguments"] == ["/venv/bin/harnessmonkey-gui"]
    assert data["RunAtLoad"] is True
    assert data["ProcessType"] == "Interactive"


def test_render_plist_logs_stdout_and_stderr_to_state_dir(tmp_path):
    """BUG 2 regression: a bare-environment launchd launch that dies before the
    menubar app can open its own log leaves zero diagnostics. Redirect launchd's
    own stdout/stderr capture to a file under the real (expanded) home passed
    in -- never a literal '~', which launchd will not expand."""
    data = plistlib.loads(render_plist(Path("/venv/bin/harnessmonkey-gui"), home=tmp_path))
    expected_log = str(tmp_path / ".harnessmonkey" / "logs" / "menubar.launchd.log")
    assert data["StandardOutPath"] == expected_log
    assert data["StandardErrorPath"] == expected_log
    assert "~" not in data["StandardOutPath"]


def test_install_agent_writes_plist_and_bootstraps(tmp_path):
    runner = FakeRunner()
    install_agent(Path("/venv/bin/harnessmonkey-gui"), home=tmp_path, runner=runner)
    plist = agent_plist_path(tmp_path)
    assert plist.exists()
    assert any(c[:2] == ["launchctl", "bootstrap"] for c in runner.calls)


def test_install_agent_creates_logs_dir_before_bootstrap(tmp_path):
    """BUG 2: the logs dir must exist before launchd bootstraps the agent, or
    launchd's StandardOutPath/StandardErrorPath redirection has nowhere to
    write and silently fails."""
    runner = FakeRunner()
    install_agent(Path("/venv/bin/harnessmonkey-gui"), home=tmp_path, runner=runner)
    logs_dir = tmp_path / ".harnessmonkey" / "logs"
    assert logs_dir.is_dir()


def test_uninstall_agent_removes_plist(tmp_path):
    runner = FakeRunner()
    install_agent(Path("/x"), home=tmp_path, runner=runner)
    uninstall_agent(home=tmp_path, runner=runner)
    assert not agent_plist_path(tmp_path).exists()
    assert any(c[:2] == ["launchctl", "bootout"] for c in runner.calls)


def test_install_agent_is_idempotent(tmp_path):
    runner = FakeRunner()
    install_agent(Path("/x"), home=tmp_path, runner=runner)
    install_agent(Path("/x"), home=tmp_path, runner=runner)
    assert agent_plist_path(tmp_path).exists()


def test_app_venv_dir_is_under_state_dir(tmp_path):
    assert app_venv_dir(tmp_path) == tmp_path / "app"


def test_app_gui_executable_points_at_app_venv_bin(tmp_path):
    assert app_gui_executable(tmp_path) == tmp_path / "app" / "bin" / "harnessmonkey-gui"


def test_provision_app_venv_runs_uv_venv_then_uv_pip_install_in_order(tmp_path):
    """Deliberate runtime OUTSIDE any TCC-protected repo path: `uv venv` builds
    the venv at <state_dir>/app, then `uv pip install` installs this repo into
    it non-editable (so it survives repo moves/deletes)."""
    runner = FakeRunner()
    repo_root = tmp_path / "repo"
    state_dir = tmp_path / "home" / ".harnessmonkey"
    state_dir.mkdir(parents=True)

    result = provision_app_venv(repo_root, state_dir, runner=runner)

    app_dir = state_dir / "app"
    assert result == app_dir
    assert runner.calls[0][:2] == ["uv", "venv"]
    assert str(app_dir) in runner.calls[0]
    install_call = runner.calls[1]
    assert install_call[:3] == ["uv", "pip", "install"]
    assert "--python" in install_call
    assert str(app_dir / "bin" / "python") in install_call
    assert str(repo_root) in install_call
    # Non-editable + reinstall: a repo update must propagate on re-run.
    assert "-e" not in install_call
    assert "--editable" not in install_call
    assert "--reinstall" in install_call


def test_provision_app_venv_passes_clear_flag_so_reprovisioning_an_existing_venv_succeeds(tmp_path):
    """Real-machine regression: `uv venv <dir>` refuses to recreate a venv
    that already exists at that path unless told to --clear it, erroring
    'A virtual environment already exists ... Use --clear to replace it'.
    `install` must be re-runnable (e.g. after a repo update) without that
    failure, per the 'creates/updates a venv... re-running upgrades in
    place' requirement."""
    runner = FakeRunner()
    state_dir = tmp_path / "home" / ".harnessmonkey"
    state_dir.mkdir(parents=True)

    provision_app_venv(tmp_path / "repo", state_dir, runner=runner)

    assert "--clear" in runner.calls[0]


def test_provision_app_venv_writes_marker_file(tmp_path):
    runner = FakeRunner()
    state_dir = tmp_path / "home" / ".harnessmonkey"
    state_dir.mkdir(parents=True)

    app_dir = provision_app_venv(tmp_path / "repo", state_dir, runner=runner)

    assert (app_dir / APP_MARKER_NAME).exists()


def test_provision_app_venv_raises_when_uv_venv_fails(tmp_path):
    runner = FailOnCallRunner(fail_on=0)
    state_dir = tmp_path / "home" / ".harnessmonkey"
    state_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError):
        provision_app_venv(tmp_path / "repo", state_dir, runner=runner)


def test_provision_app_venv_raises_when_uv_pip_install_fails(tmp_path):
    runner = FailOnCallRunner(fail_on=1)
    state_dir = tmp_path / "home" / ".harnessmonkey"
    state_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError):
        provision_app_venv(tmp_path / "repo", state_dir, runner=runner)


def test_uninstall_agent_removes_app_dir_when_marked_by_marker_file(tmp_path):
    runner = FakeRunner()
    app_dir = tmp_path / ".harnessmonkey" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / APP_MARKER_NAME).write_text("marker")

    uninstall_agent(home=tmp_path, runner=runner)

    assert not app_dir.exists()


def test_uninstall_agent_removes_app_dir_when_it_contains_gui_script(tmp_path):
    runner = FakeRunner()
    app_dir = tmp_path / ".harnessmonkey" / "app"
    (app_dir / "bin").mkdir(parents=True)
    (app_dir / "bin" / "harnessmonkey-gui").write_text("#!/bin/sh\n")

    uninstall_agent(home=tmp_path, runner=runner)

    assert not app_dir.exists()


def test_uninstall_agent_leaves_unrelated_app_dir_untouched(tmp_path):
    """Safety: only remove <state_dir>/app if it looks like our artifact --
    never blow away an unrelated directory that happens to be named 'app'."""
    runner = FakeRunner()
    app_dir = tmp_path / ".harnessmonkey" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "not-ours.txt").write_text("random stuff, not created by harnessmonkey")

    uninstall_agent(home=tmp_path, runner=runner)

    assert app_dir.exists()
    assert (app_dir / "not-ours.txt").exists()
