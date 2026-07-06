from __future__ import annotations

import os
import plistlib
import shutil
import sys
from pathlib import Path

from .smoke import CommandResult, run_command

LAUNCH_AGENT_LABEL = "com.hackerbara.harnessmonkey"

# Name of the dedicated venv provisioned under <state_dir> by `install`, and
# the marker file written inside it so `uninstall` can tell "this is ours" --
# a runtime provisioned outside any TCC-protected clone location (BUG 3).
APP_DIR_NAME = "app"
APP_MARKER_NAME = ".harnessmonkey-app"


def menubar_log_path(home: Path) -> Path:
    """Where launchd redirects the menubar GUI's stdout/stderr (BUG 2).

    Without this, a launch that dies in launchd's bare environment (before the
    menubar app ever opens its own `menubar.log`) leaves zero diagnostics: the
    install succeeds, the background-item notification fires, but no menubar
    icon appears and there is nothing to inspect. Must expand the real home
    passed in -- launchd does not expand a literal `~` in plist paths.
    """
    return Path(home).expanduser() / ".harnessmonkey" / "logs" / "menubar.launchd.log"


def render_plist(gui_executable: Path, home: Path) -> bytes:
    log_path = str(menubar_log_path(home))
    return plistlib.dumps(
        {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": [str(gui_executable)],
            "RunAtLoad": True,
            "ProcessType": "Interactive",
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
        }
    )


def agent_plist_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def _gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _ok_result(argv: list[str] | None = None) -> CommandResult:
    return CommandResult(argv=argv or [], returncode=0, stdout="", stderr="")


def install_agent(gui_executable: Path, home: Path, runner=run_command) -> CommandResult:
    plist = agent_plist_path(home)
    plist.parent.mkdir(parents=True, exist_ok=True)
    # Logs dir must exist before bootstrap: launchd opens StandardOutPath/
    # StandardErrorPath itself at launch time, and won't create missing parent
    # directories for them.
    menubar_log_path(home).parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(render_plist(gui_executable, home))

    runner(["launchctl", "bootout", _gui_domain(), str(plist)])
    return runner(["launchctl", "bootstrap", _gui_domain(), str(plist)])


def app_venv_dir(state_dir: Path) -> Path:
    """Where `install` provisions a dedicated venv, deliberately OUTSIDE any
    TCC-protected repo clone location (BUG 3): a LaunchAgent spawned by
    launchd has no Documents/Desktop/etc access grant (only Terminal.app
    does), so pointing ProgramArguments at a repo-venv script under
    ~/Documents kills the process at interpreter startup with a
    PermissionError on pyvenv.cfg. ~/.harnessmonkey is not TCC-protected."""
    return Path(state_dir) / APP_DIR_NAME


def app_gui_executable(state_dir: Path) -> Path:
    return app_venv_dir(state_dir) / "bin" / "harnessmonkey-gui"


def provision_app_venv(repo_root: Path, state_dir: Path, runner=run_command) -> Path:
    """Create/update the dedicated app venv at <state_dir>/app.

    Installs this repo into it NON-editable (`uv pip install --reinstall
    <repo_root>`, no `-e`) so the LaunchAgent keeps working even if the repo
    clone is later moved or deleted -- and re-running (e.g. after a repo
    update) upgrades the installed copy in place via --reinstall.

    Raises RuntimeError if either `uv` step fails; callers are expected to
    catch this and fall back to registering the LaunchAgent against the repo
    venv instead (current pre-fix behavior) rather than failing the whole
    install.
    """
    venv_dir = app_venv_dir(state_dir)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)

    # --clear: `uv venv` otherwise refuses to recreate a venv that already
    # exists at this path ("Use --clear to replace it"), which would break
    # re-running install after a repo update (the "updates a venv" half of
    # this function's contract).
    result = runner(["uv", "venv", "--clear", str(venv_dir)])
    if result.returncode != 0:
        raise RuntimeError(f"uv venv failed: {result.stderr or result.stdout}")

    python_path = venv_dir / "bin" / "python"
    result = runner(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python_path),
            "--reinstall",
            str(repo_root),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"uv pip install failed: {result.stderr or result.stdout}")

    # `uv venv` creates the directory in real usage; in unit tests the runner
    # is faked and never actually creates it, so make sure it exists before
    # writing the marker either way.
    venv_dir.mkdir(parents=True, exist_ok=True)
    (venv_dir / APP_MARKER_NAME).write_text(
        "Managed by `harnessmonkey install`. Safe to delete; "
        "will be recreated on the next install.\n"
    )
    return venv_dir


def _looks_like_our_app_dir(venv_dir: Path) -> bool:
    if not venv_dir.is_dir():
        return False
    if (venv_dir / APP_MARKER_NAME).exists():
        return True
    if (venv_dir / "bin" / "harnessmonkey-gui").exists():
        return True
    return False


def uninstall_agent(home: Path, runner=run_command) -> CommandResult:
    plist = agent_plist_path(home)
    runner(["launchctl", "bootout", _gui_domain(), str(plist)])
    plist.unlink(missing_ok=True)

    app_dir = app_venv_dir(Path(home) / ".harnessmonkey")
    if _looks_like_our_app_dir(app_dir):
        shutil.rmtree(app_dir, ignore_errors=True)

    return _ok_result(["launchctl", "bootout", _gui_domain(), str(plist)])


def gui_executable() -> Path:
    """Resolve the console script next to the currently-running interpreter.

    This stays as the direct-terminal / --cli fallback only: `uv run
    harnessmonkey-gui` runs fine here because Terminal.app holds its own
    TCC grant. It is NOT used to build the LaunchAgent's ProgramArguments
    anymore (see app_gui_executable) except as a last-resort fallback when
    provisioning the dedicated app venv fails.
    """
    executable = Path(sys.executable).parent / "harnessmonkey-gui"
    if not executable.exists():
        raise FileNotFoundError(
            "harnessmonkey-gui console script not found next to Python "
            f"interpreter: {executable}"
        )
    return executable
