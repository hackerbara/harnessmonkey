from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CURRENT_SOURCE = Path.home() / ".local/share/claude/versions/2.1.201"
CASES = [
    ("capybara-onsen", "capybara-onsen-generator"),
    ("heraldic-dragons", "heraldic-dragons-generator"),
]
SKIP_FILE_NAMES = {"preview.png"}


def _files_under(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name not in SKIP_FILE_NAMES
    }


@pytest.mark.parametrize(("pkg", "gen"), CASES)
def test_generator_regenerates_live_package_from_target_binary(
    pkg: str, gen: str, tmp_path: Path
) -> None:
    """Generator output must byte-match packages/<pkg> for the requested target binary."""
    if not CURRENT_SOURCE.exists():
        pytest.skip(f"missing local Claude Code binary: {CURRENT_SOURCE}")
    out = tmp_path / pkg
    env = {**os.environ, "HM_GENERATE_OUT": str(out)}
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples" / gen / "generate_package.py"),
            "--source",
            str(CURRENT_SOURCE),
            "--source-version",
            "2.1.201",
            "--source-version-output",
            "2.1.201 (Claude Code)",
        ],
        check=True,
        env=env,
    )

    live = ROOT / "packages" / pkg
    assert _files_under(out) == _files_under(live)


@pytest.mark.parametrize(("pkg", "gen"), CASES)
def test_generator_contract_keeps_anchors_editable_and_rejects_copy_stub(pkg: str, gen: str) -> None:
    source = (ROOT / "examples" / gen / "generate_package.py").read_text()
    assert "VERSION_FRAGILE_ANCHORS" in source
    assert "shutil.copy" not in source
    assert "copytree" not in source
