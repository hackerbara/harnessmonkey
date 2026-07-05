from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class AuthorizationRequired(RuntimeError):
    def __init__(self, message: str, *, method: str | None = None) -> None:
        super().__init__(message)
        self.method = method


class AuthorizationDenied(RuntimeError):
    def __init__(self, message: str, *, method: str | None = None) -> None:
        super().__init__(message)
        self.method = method


@dataclass(frozen=True)
class AuthorizationResult:
    returncode: int
    stdout: str
    stderr: str
    method: str


PROTECTED_ROOTS = (
    Path("/bin"),
    Path("/sbin"),
    Path("/usr/bin"),
    Path("/usr/sbin"),
    Path("/usr/local/bin"),
    Path("/opt/homebrew/bin"),
)


def target_needs_authorization(target_path: Path) -> bool:
    expanded = target_path.expanduser()
    parent = expanded.parent
    if any(expanded == root or root in expanded.parents for root in PROTECTED_ROOTS):
        return True
    writable_parent = parent
    while not writable_parent.exists() and writable_parent != writable_parent.parent:
        writable_parent = writable_parent.parent
    return not os.access(writable_parent, os.W_OK)


def authorization_method_for_target(target_path: Path) -> str | None:
    if not target_needs_authorization(target_path):
        return None
    return "macos_gui" if Path("/usr/bin/osascript").exists() else "sudo"


def run_privileged_argv(argv: list[str], *, reason: str) -> AuthorizationResult:
    if not argv:
        raise ValueError("argv is required")
    osascript = Path("/usr/bin/osascript")
    if osascript.exists():
        command = " ".join(shlex.quote(item) for item in argv)
        script = f"do shell script {json.dumps(command)} with administrator privileges"
        result = subprocess.run(
            [str(osascript), "-e", script],
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AuthorizationDenied(result.stderr.strip() or reason, method="macos_gui")
        return AuthorizationResult(result.returncode, result.stdout, result.stderr, "macos_gui")
    sudo = shutil.which("sudo")
    if not sudo:
        raise AuthorizationRequired(reason, method="not_available")
    result = subprocess.run(
        [sudo, *argv],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AuthorizationDenied(result.stderr.strip() or reason, method="sudo")
    return AuthorizationResult(result.returncode, result.stdout, result.stderr, "sudo")
