from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 15.0
TIMEOUT_RETURN_CODE = 124


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


def run_command(argv: list[str], timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        message = f"command timed out after {timeout_seconds} seconds"
        stderr = f"{stderr}\n{message}" if stderr else message
        return CommandResult(
            argv=argv,
            returncode=TIMEOUT_RETURN_CODE,
            stdout=stdout,
            stderr=stderr,
        )
    except OSError as exc:
        return CommandResult(
            argv=argv,
            returncode=127,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
        )
    return CommandResult(
        argv=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
    )


def smoke_version_and_help(binary: Path, runner=run_command) -> list[CommandResult]:
    return [runner([str(binary), "--version"]), runner([str(binary), "--help"])]


def codesign_sign(binary: Path, runner=run_command) -> CommandResult:
    return runner(["codesign", "--force", "--sign", "-", str(binary)])


def codesign_verify(binary: Path, runner=run_command) -> CommandResult:
    return runner(["codesign", "--verify", "--deep", "--strict", "--verbose=4", str(binary)])


def smoke_claude_code_version_and_help(
    binary: Path, expected_version_output: str, runner=run_command
) -> dict[str, Any]:
    version = runner([str(binary), "--version"])
    help_result = runner([str(binary), "--help"])
    errors: list[str] = []
    version_text = (version.stdout.strip() or version.stderr.strip()).strip()
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    if version.returncode != 0:
        errors.append("version_nonzero_exit")
    if version_text != expected_version_output:
        errors.append("version_mismatch")
    if help_result.returncode != 0:
        errors.append("help_nonzero_exit")
    if "Claude Code" not in help_text:
        errors.append("claude_help_marker_missing")
    if "Bun is a fast JavaScript runtime" in help_text or version_text.startswith("1.4.0"):
        errors.append("bun_help_detected")
    return {
        "passed": not errors,
        "errors": errors,
        "commands": [version.__dict__, help_result.__dict__],
    }
