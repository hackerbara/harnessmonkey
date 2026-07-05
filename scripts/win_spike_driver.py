"""Thin driver for the Windows PE spike: apply a patch package to a PE claude.exe
through the genuine build vocab, skipping CLI plumbing (source auto-discovery,
arg parsing). Mirrors brief §12 Step 1's ~40-line driver.
"""
from __future__ import annotations

from pathlib import Path

from harnessmonkey.builder_v15 import BuildRequestV15, build_patchset_v15


def build_spike(source: Path, package_dir: Path, out_dir: Path) -> Path:
    source = Path(source)
    request = BuildRequestV15(
        source_path=source,
        output_dir=Path(out_dir),
        package_dirs=[Path(package_dir)],
        source_version="2.1.201",
        source_version_output="2.1.201 (Claude Code)",
        platform="win32",
        arch="x64",
        run_signing=False,   # PE builds skip signing (Task 6 also no-ops it)
        run_smoke=False,     # cannot execute a Windows PE on macOS -- deferred to Windows
        activate=False,
    )
    report = build_patchset_v15(request)
    if report.outputPath is None:
        raise SystemExit(f"build failed: {report.failureReason} ({report.status})")
    return Path(report.outputPath)


if __name__ == "__main__":
    import sys

    _ROOT = Path(__file__).resolve().parents[1]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from tests.harnessmonkey_binary import win_claude_bin

    pkg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures_win_package")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("build/win-spike")
    out.mkdir(parents=True, exist_ok=True)
    result = build_spike(win_claude_bin(), pkg, out)
    print(f"patched binary: {result}")
