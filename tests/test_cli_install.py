from __future__ import annotations

import json
from pathlib import Path

from harnessmonkey import cli
from harnessmonkey.cli import main
from harnessmonkey.smoke import CommandResult


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def patch_manifest(package_id: str, *, label: str | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "patch",
        "id": package_id,
        "label": label or package_id.replace("-", " ").title(),
        "description": "Patch package",
        "risk": {"level": "low"},
        "patch": {"engine": "bun_graph_repack", "targets": []},
    }


def write_patch_package(packages_root: Path, package_id: str) -> Path:
    package_dir = packages_root / package_id
    write_json(package_dir / "patch.json", patch_manifest(package_id))
    return package_dir


def configure_install(monkeypatch, tmp_path: Path, package_ids=("alpha-patch", "beta-patch")):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    repo_root = tmp_path / "repo"
    packages_root = repo_root / "packages"
    for package_id in package_ids:
        write_patch_package(packages_root, package_id)
    monkeypatch.setattr(cli, "_repo_packages_root", lambda: packages_root)
    return home, packages_root


def read_cli_json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_install_copies_all_repo_packages_disabled(tmp_path, monkeypatch, capsys):
    home, _packages_root = configure_install(monkeypatch, tmp_path)

    assert main(["install", "--cli"]) == 0

    for package_id in ("alpha-patch", "beta-patch"):
        assert (home / ".harnessmonkey" / "patches" / package_id / "patch.json").exists()

    capsys.readouterr()
    assert main(["list-patches", "--json"]) == 0
    records = read_cli_json(capsys)["patches"]
    assert {record["id"]: record["enabled"] for record in records} == {
        "alpha-patch": False,
        "beta-patch": False,
    }


def test_install_cli_flag_skips_launch_agent(tmp_path, monkeypatch, capsys):
    configure_install(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        cli.launch_agent, "install_agent", lambda *args, **kwargs: calls.append(args)
    )

    assert main(["install", "--cli", "--json"]) == 0

    assert calls == []
    payload = read_cli_json(capsys)
    assert payload["ok"] is True
    assert payload["launchAgent"]["skipped"] is True


def test_install_default_installs_launch_agent(tmp_path, monkeypatch, capsys):
    """BUG 3 fix: the default (non --cli) install path provisions the
    dedicated app venv and points the LaunchAgent at its script, not the repo
    venv script next to the running interpreter."""
    configure_install(monkeypatch, tmp_path)
    gui = tmp_path / "home" / ".harnessmonkey" / "app" / "bin" / "harnessmonkey-gui"
    calls = []

    def fake_provision_app_venv(repo_root, state_dir, runner=None):
        return state_dir / "app"

    def fake_install_agent(gui_executable, *, home, runner=None):
        calls.append((gui_executable, home, runner))
        return CommandResult(argv=["launchctl", "bootstrap"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.launch_agent, "provision_app_venv", fake_provision_app_venv)
    monkeypatch.setattr(cli.launch_agent, "app_gui_executable", lambda state_dir: gui)
    monkeypatch.setattr(cli.launch_agent, "install_agent", fake_install_agent)

    assert main(["install", "--json"]) == 0

    assert calls == [(gui, tmp_path / "home", None)]
    payload = read_cli_json(capsys)
    assert payload["launchAgent"]["ok"] is True
    assert payload["launchAgent"]["skipped"] is False
    assert payload["launchAgent"]["guiExecutable"] == str(gui)


def test_install_provisions_app_venv_with_real_repo_root_and_state_dir(tmp_path, monkeypatch, capsys):
    """provision_app_venv must be called with the actual repo root (not the
    fake packages dir used for patch-package fixtures) and the real state
    dir, so the venv it builds installs the real project and lives under
    ~/.harnessmonkey."""
    home, _packages_root = configure_install(monkeypatch, tmp_path)
    gui = home / ".harnessmonkey" / "app" / "bin" / "harnessmonkey-gui"
    calls = []

    def fake_provision_app_venv(repo_root, state_dir, runner=None):
        calls.append((repo_root, state_dir))
        return state_dir / "app"

    monkeypatch.setattr(cli.launch_agent, "provision_app_venv", fake_provision_app_venv)
    monkeypatch.setattr(cli.launch_agent, "app_gui_executable", lambda state_dir: gui)
    monkeypatch.setattr(
        cli.launch_agent,
        "install_agent",
        lambda gui_executable, *, home, runner=None: CommandResult(
            argv=["launchctl", "bootstrap"], returncode=0, stdout="", stderr=""
        ),
    )

    assert main(["install", "--json"]) == 0

    assert len(calls) == 1
    repo_root, state_dir = calls[0]
    assert state_dir == home / ".harnessmonkey"
    assert (repo_root / "pyproject.toml").exists()


def test_install_falls_back_to_repo_venv_when_provisioning_fails(tmp_path, monkeypatch, capsys):
    """Provisioning failure (uv missing, network, etc.) must not fail the
    whole install: fall back to the repo venv script (pre-fix behavior),
    warn that login-launch may not work from a TCC-protected clone location,
    and exit 0."""
    configure_install(monkeypatch, tmp_path)
    fallback_gui = tmp_path / "venv" / "bin" / "harnessmonkey-gui"
    fallback_gui.parent.mkdir(parents=True)
    fallback_gui.write_text("#!/bin/sh\n")
    calls = []

    def fake_provision_app_venv(repo_root, state_dir, runner=None):
        raise RuntimeError("uv not found")

    def fake_install_agent(gui_executable, *, home, runner=None):
        calls.append(gui_executable)
        return CommandResult(argv=["launchctl", "bootstrap"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.launch_agent, "provision_app_venv", fake_provision_app_venv)
    monkeypatch.setattr(cli.launch_agent, "gui_executable", lambda: fallback_gui)
    monkeypatch.setattr(cli.launch_agent, "install_agent", fake_install_agent)

    assert main(["install"]) == 0

    assert calls == [fallback_gui]
    combined = "".join(capsys.readouterr())
    assert "uv run harnessmonkey-gui" in combined
    assert "TCC" in combined or "Documents" in combined


def test_install_prints_log_path_when_launch_agent_installed(tmp_path, monkeypatch, capsys):
    """BUG 2: if the menubar icon doesn't appear after install, the user needs
    to know where launchd redirected the GUI's stdout/stderr. Print it in the
    human-readable next-steps output (not just buried in --json)."""
    configure_install(monkeypatch, tmp_path)
    gui = tmp_path / "home" / ".harnessmonkey" / "app" / "bin" / "harnessmonkey-gui"

    def fake_install_agent(gui_executable, *, home, runner=None):
        return CommandResult(argv=["launchctl", "bootstrap"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        cli.launch_agent,
        "provision_app_venv",
        lambda repo_root, state_dir, runner=None: state_dir / "app",
    )
    monkeypatch.setattr(cli.launch_agent, "app_gui_executable", lambda state_dir: gui)
    monkeypatch.setattr(cli.launch_agent, "install_agent", fake_install_agent)

    assert main(["install"]) == 0

    out = capsys.readouterr().out
    expected_log = str(tmp_path / "home" / ".harnessmonkey" / "logs" / "menubar.launchd.log")
    assert expected_log in out


def test_install_prints_login_items_caveat_on_successful_registration(tmp_path, monkeypatch, capsys):
    """Honest caveat (BUG 3 handoff): registering the plist doesn't guarantee
    macOS shows the menubar icon -- a Login Items & Extensions approval gate
    can still block it. Tell the user where to look."""
    configure_install(monkeypatch, tmp_path)
    gui = tmp_path / "home" / ".harnessmonkey" / "app" / "bin" / "harnessmonkey-gui"

    monkeypatch.setattr(
        cli.launch_agent,
        "provision_app_venv",
        lambda repo_root, state_dir, runner=None: state_dir / "app",
    )
    monkeypatch.setattr(cli.launch_agent, "app_gui_executable", lambda state_dir: gui)
    monkeypatch.setattr(
        cli.launch_agent,
        "install_agent",
        lambda gui_executable, *, home, runner=None: CommandResult(
            argv=["launchctl", "bootstrap"], returncode=0, stdout="", stderr=""
        ),
    )

    assert main(["install"]) == 0

    out = capsys.readouterr().out
    assert "Login Items & Extensions" in out
    assert str(gui.parent.parent) in out  # the provisioned app runtime dir


def test_install_reports_per_package_failure_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    home, packages_root = configure_install(monkeypatch, tmp_path, package_ids=("good-patch",))
    bad = packages_root / "bad-patch"
    write_json(
        bad / "patch.json",
        {
            "schemaVersion": 1,
            "kind": "patch",
            "id": "bad-patch",
            "label": "Bad",
            "description": "Bad package",
            "risk": {"level": "low"},
        },
    )

    assert main(["install", "--cli", "--json"]) == 1

    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["packages"]["good-patch"]["ok"] is True
    assert payload["packages"]["bad-patch"]["ok"] is False
    assert (home / ".harnessmonkey" / "patches" / "good-patch" / "patch.json").exists()


def test_install_refreshes_stale_repo_package(tmp_path, monkeypatch, capsys):
    """BUG 1 regression: a stale on-disk copy (old schemaVersion/pins from an
    earlier dev install) must be REFRESHED by `install`, not silently skipped
    because the dest dir already exists."""
    home, packages_root = configure_install(monkeypatch, tmp_path, package_ids=("alpha-patch",))

    # Simulate a stale prior install: same id, old/different content already
    # sitting under state dir before `install` runs.
    stale_dest = home / ".harnessmonkey" / "patches" / "alpha-patch"
    write_json(stale_dest / "patch.json", patch_manifest("alpha-patch", label="Old Stale Label"))

    assert main(["install", "--cli", "--json"]) == 0

    payload = read_cli_json(capsys)
    assert payload["ok"] is True
    assert payload["packages"]["alpha-patch"]["ok"] is True
    assert payload["packages"]["alpha-patch"]["summary"] == "updated patch package alpha-patch"
    refreshed = json.loads((stale_dest / "patch.json").read_text())
    assert refreshed["label"] != "Old Stale Label"


def test_install_reports_unchanged_when_repo_package_already_current(tmp_path, monkeypatch, capsys):
    home, packages_root = configure_install(monkeypatch, tmp_path, package_ids=("alpha-patch",))

    assert main(["install", "--cli", "--json"]) == 0
    capsys.readouterr()

    # Second run: repo package content hasn't changed -> idempotent "unchanged".
    assert main(["install", "--cli", "--json"]) == 0
    payload = read_cli_json(capsys)
    assert payload["ok"] is True
    assert payload["packages"]["alpha-patch"]["summary"] == "unchanged alpha-patch"


def test_uninstall_removes_launch_agent_only_and_leaves_state(tmp_path, monkeypatch, capsys):
    home, _packages_root = configure_install(monkeypatch, tmp_path, package_ids=("kept-patch",))
    state = home / ".harnessmonkey"
    write_json(state / "patches" / "kept-patch" / "patch.json", patch_manifest("kept-patch"))
    shim = state / "bin" / "claude"
    shim.parent.mkdir(parents=True)
    shim.write_text("shim stays")
    calls = []

    def fake_uninstall_agent(*, home):
        calls.append(home)
        return CommandResult(argv=["launchctl", "bootout"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.launch_agent, "uninstall_agent", fake_uninstall_agent)

    assert main(["uninstall", "--json"]) == 0

    assert calls == [home]
    assert (state / "patches" / "kept-patch" / "patch.json").exists()
    assert shim.read_text() == "shim stays"
    payload = read_cli_json(capsys)
    assert payload["ok"] is True
    assert payload["stateDirUntouched"] is True
    assert payload["shimUntouched"] is True


def test_install_rejects_repo_schema_v2_patch_packages(tmp_path, monkeypatch, capsys):
    home, packages_root = configure_install(monkeypatch, tmp_path, package_ids=())
    package_dir = packages_root / "schema-two"
    write_json(
        package_dir / "patch.json",
        {
            "schemaVersion": 2,
            "id": "schema-two",
            "name": "Schema Two",
            "description": "V2 patch package",
            "packageVersion": "0.1.0",
            "targets": [
                {
                    "requiredEngine": "bun_graph_repack",
                    "requiredBinaryFormat": "bun_standalone_macho64",
                    "modules": [],
                }
            ],
        },
    )

    assert main(["install", "--cli", "--json"]) == 1

    payload = read_cli_json(capsys)
    assert payload["ok"] is False
    assert payload["packages"]["schema-two"]["ok"] is False
    assert payload["packages"]["schema-two"]["error"]["code"] == "invalid_package"
    assert "schemaVersion_must_be_1" in payload["packages"]["schema-two"]["error"]["message"]
    assert not (home / ".harnessmonkey" / "patches" / "schema-two" / "patch.json").exists()
