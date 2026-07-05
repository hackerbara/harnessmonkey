from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _clear_macos_immutable_flag_after_test(tmp_path):
    """Safety net for the shim-lock feature (install.py's `_lock_target`):
    a test that locks a real file under `tmp_path` and never explicitly
    unlocks it again would otherwise leave pytest's own tmp-dir cleanup
    unable to remove it -- `UF_IMMUTABLE` blocks unlink()/rmdir()
    unconditionally, regardless of ownership, until the flag is explicitly
    cleared (reproduced directly against this host's filesystem). Sweep
    `tmp_path` clear of the flag after every test, unconditionally; a no-op
    everywhere nothing was ever locked, and on any non-mac platform.
    """
    yield
    if not (sys.platform == "darwin" and hasattr(os, "chflags")):
        return
    for path in tmp_path.rglob("*"):
        if path.is_symlink():
            continue
        try:
            flags = path.stat().st_flags
        except OSError:
            continue
        if flags & stat.UF_IMMUTABLE:
            try:
                os.chflags(str(path), 0)
            except OSError:
                pass
