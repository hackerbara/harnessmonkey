from __future__ import annotations

import json
import os
import subprocess
import sys

from harnessmonkey.shim import render_shim_script


def test_shim_script_bootstraps_canonical_entrypoint():
    script = render_shim_script("/tmp/state")
    path_insert = "sys.path.insert"
    canonical_import = "from harnessmonkey.shim_entry import main"
    assert path_insert in script
    assert script.index(path_insert) < script.index(canonical_import)
    assert "from harnessmonkey.shim_entry import main" in script
    assert 'main("/tmp/state")' in script
    assert "shell=True" not in script


def test_shim_script_does_not_embed_legacy_prompt_merge_logic():
    script = render_shim_script("/tmp/state")
    assert "active_prompt_args" not in script
    assert "PROMPT_FLAGS" not in script
    assert "CONFIG.read_text" not in script


def test_rendered_shim_imports_package_without_pythonpath(tmp_path):
    state = tmp_path / "state"
    target = tmp_path / "bin" / "target"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho target reached\n")
    target.chmod(0o755)
    state.mkdir()
    (state / "config.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "activeProfile": "default",
                "installMode": "shim",
                "officialClaudePath": str(target),
                "profiles": {"default": {"prompt": None, "patches": [], "options": []}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    shim = tmp_path / "installed" / "claude"
    shim.parent.mkdir()
    shim.write_text(render_shim_script(str(state)))
    shim.chmod(0o755)
    outside_repo = tmp_path / "outside"
    outside_repo.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    env["PATH"] = os.environ.get("PATH", "")

    result = subprocess.run(
        [sys.executable, "-S", str(shim), "--version"],
        cwd=outside_repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "target reached\n"
    assert "ModuleNotFoundError" not in result.stderr
