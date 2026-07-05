from __future__ import annotations

import json
from pathlib import Path


def render_shim_script(state_dir: str) -> str:
    state_dir_literal = json.dumps(state_dir)
    package_root_literal = json.dumps(str(Path(__file__).resolve().parent.parent))
    return f'''#!/usr/bin/env python3
from __future__ import annotations

# HarnessMonkey managed shim

import sys

PACKAGE_ROOT = {package_root_literal}
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)

from harnessmonkey.shim_entry import main

if __name__ == "__main__":
    raise SystemExit(main({state_dir_literal}))
'''


def write_shim(path: Path, state_dir: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_shim_script(str(state_dir)))
    path.chmod(0o755)
