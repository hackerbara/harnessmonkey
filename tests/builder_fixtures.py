from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from tests.fixtures_bun import MODULE_0, build_aligned_macho_fixture

from harnessmonkey.builder_v15 import BuildRequestV15
from harnessmonkey.smoke import CommandResult


def write_fixture_package(package: Path, binary: Path, *, manual_smoke: bool = False) -> None:
    old = MODULE_0[: MODULE_0.index(b"function after(){")]
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "fixture-v15",
        "label": "Fixture V1.5",
        "description": "Fixture package",
        "packageVersion": "0.1.0",
        "patch": {"engine": "bun_graph_repack", "targets": [
            {
                "sourceIdentity": {
                    "claudeVersion": "fixture",
                    "versionOutput": "fixture (Claude Code)",
                    "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                    "sizeBytes": binary.stat().st_size,
                    "platform": "darwin",
                    "arch": "arm64",
                },
                "requiredEngine": "bun_graph_repack",
                "requiredBinaryFormat": "bun_standalone_macho64",
                "modules": [
                    {
                        "path": "/$bunfs/root/src/entrypoints/cli.js",
                        "contentSha256": hashlib.sha256(MODULE_0).hexdigest(),
                        "contentLength": len(MODULE_0),
                        "operations": [
                            {
                                "opId": "replace-renderer",
                                "label": "Replace renderer",
                                "type": "replace_between",
                                "startMarker": "function render(){",
                                "endMarker": "function after(){",
                                "expectedStartMarkerCount": 1,
                                "expectedEndMarkerCount": 1,
                                "requireWithinRange": ["OLD_RENDER"],
                                "oldRangeSha256": hashlib.sha256(old).hexdigest(),
                                "oldRangeLength": len(old),
                                "replacement": {"inline": "function render(){NEW_RENDER_LONGER}\n"},
                            }
                        ],
                    }
                ],
                "postconditions": [
                    {
                        "type": "module_must_contain",
                        "modulePath": "/$bunfs/root/src/entrypoints/cli.js",
                        "value": "NEW_RENDER_LONGER",
                    }
                ],
                "manualSmoke": {"required": manual_smoke, "reason": "UI" if manual_smoke else None},
            }
        ]},
    }
    package.mkdir()
    (package / "patch.json").write_text(json.dumps(manifest))


def successful_runner(argv):
    if argv[0] == "codesign" and "--verify" in argv:
        return CommandResult(argv=argv, returncode=0, stdout="", stderr="valid")
    if argv[0] == "codesign":
        return CommandResult(argv=argv, returncode=0, stdout="", stderr="signed")
    if argv[-1] == "--version":
        return CommandResult(argv=argv, returncode=0, stdout="fixture (Claude Code)\n", stderr="")
    if argv[-1] == "--help":
        return CommandResult(
            argv=argv, returncode=0, stdout="Usage: claude [options]\nClaude Code help\n", stderr=""
        )
    return CommandResult(argv=argv, returncode=1, stdout="", stderr="unexpected")


def _default_source(tmp_path: Path) -> Path:
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    return source


@pytest.fixture
def successful_build_request(tmp_path: Path):
    """Factory fixture: build a BuildRequestV15 against a fake source binary with a
    matching, well-formed patch package. Pass `manual_smoke=True` to require manual
    smoke, or any BuildRequestV15 field to override its default."""

    def factory(**overrides: Any) -> BuildRequestV15:
        manual_smoke = overrides.pop("manual_smoke", False)
        source = _default_source(tmp_path)
        package = tmp_path / "fixture-v15"
        write_fixture_package(package, source, manual_smoke=manual_smoke)
        kwargs: dict[str, Any] = dict(
            source_path=source,
            output_dir=tmp_path / "out",
            package_dirs=[package],
            source_version="fixture",
            source_version_output="fixture (Claude Code)",
            platform="darwin",
            arch="arm64",
            command_runner=successful_runner,
        )
        kwargs.update(overrides)
        return BuildRequestV15(**kwargs)

    return factory


@pytest.fixture
def bad_manifest_build_request(tmp_path: Path):
    """Factory fixture: build a BuildRequestV15 pointed at a package whose manifest
    fails to load (schema v1, migration required), so _select_packages fails before
    any patch resolution happens."""

    def factory(**overrides: Any) -> BuildRequestV15:
        source = _default_source(tmp_path)
        package = tmp_path / "fixture-v15"
        package.mkdir()
        (package / "patch.json").write_text(json.dumps({"schemaVersion": 1}))
        kwargs: dict[str, Any] = dict(
            source_path=source,
            output_dir=tmp_path / "out",
            package_dirs=[package],
            source_version="fixture",
            source_version_output="fixture (Claude Code)",
            platform="darwin",
            arch="arm64",
            command_runner=successful_runner,
        )
        kwargs.update(overrides)
        return BuildRequestV15(**kwargs)

    return factory
