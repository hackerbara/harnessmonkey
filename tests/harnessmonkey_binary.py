"""Shared helper for locating locally installed Claude Code binaries in tests.

Several tests validate packages against a real, pinned Claude Code binary that
only exists on a developer's machine (it is never checked into the repo and
never present in CI/the public repo). Those tests must self-skip cleanly when
the binary is absent — this module centralizes *where* to look for it so the
skip behavior stays consistent and no test hardcodes a maintainer's home
directory layout.

Resolution order (first existing candidate wins, callers should still check
`.exists()` themselves since a missing binary is an expected, skip-worthy
condition rather than an error):

1. An explicit environment variable override (`HARNESSMONKEY_CLAUDE_BIN` for
   the "current/live" `claude` binary, `HARNESSMONKEY_CLAUDE_VERSIONS_DIR` for
   the root of the pinned-version install directories).
2. `claude` resolved via `PATH` (`shutil.which`).
3. The conventional per-machine install locations under `Path.home()`.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

CLAUDE_BIN_ENV = "HARNESSMONKEY_CLAUDE_BIN"
CLAUDE_VERSIONS_DIR_ENV = "HARNESSMONKEY_CLAUDE_VERSIONS_DIR"


def claude_bin_candidates() -> list[Path]:
    """Ordered candidate locations for the current/live `claude` binary."""
    candidates: list[Path] = []
    override = os.environ.get(CLAUDE_BIN_ENV)
    if override:
        candidates.append(Path(override))
    which = shutil.which("claude")
    if which:
        candidates.append(Path(which))
    candidates.append(Path.home() / ".local" / "bin" / "claude")
    return candidates


def claude_versions_dir() -> Path:
    """Root directory holding pinned Claude Code version installs."""
    override = os.environ.get(CLAUDE_VERSIONS_DIR_ENV)
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "claude" / "versions"


def claude_version_path(version: str) -> Path:
    """Path to a specific pinned Claude Code version's install directory.

    This does not check existence — callers should `pytest.skip()` when the
    returned path is absent, since the pinned binary is a developer-machine
    fixture that is never present in the public repo or CI.
    """
    return claude_versions_dir() / version
