from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.fixtures_bun import MODULE_0, build_aligned_macho_fixture

from harnessmonkey.builder_v15 import BuildRequestV15, build_patchset_v15
from harnessmonkey.bun_graph import parse_bun_section
from harnessmonkey.macho import find_macho_layout
from harnessmonkey.smoke import CommandResult

MODULE_PATH = "/$bunfs/root/src/entrypoints/cli.js"


def runner(argv):
    if argv[0] == "codesign" and "--verify" in argv:
        return CommandResult(argv=argv, returncode=0, stdout="", stderr="valid")
    if argv[0] == "codesign":
        return CommandResult(argv=argv, returncode=0, stdout="", stderr="signed")
    if argv[-1] == "--version":
        return CommandResult(argv=argv, returncode=0, stdout="fixture (Claude Code)\n", stderr="")
    if argv[-1] == "--help":
        return CommandResult(
            argv=argv,
            returncode=0,
            stdout="Usage: claude [options]\nClaude Code help\n",
            stderr="",
        )
    return CommandResult(argv=argv, returncode=1, stdout="", stderr="unexpected")


def write_package(package: Path, binary: Path, package_id: str, payload: str, order: int) -> None:
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": package_id,
        "label": package_id,
        "description": "Shared-anchor insertion fixture",
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
                        "path": MODULE_PATH,
                        "contentSha256": hashlib.sha256(MODULE_0).hexdigest(),
                        "contentLength": len(MODULE_0),
                        "operations": [
                            {
                                "opId": f"{package_id}-insert",
                                "label": "Insert entry",
                                "type": "insert_after",
                                "anchor": "OLD_RENDER",
                                "insertOrder": order,
                                "replacement": {"inline": payload},
                            }
                        ],
                    }
                ],
                "postconditions": [
                    {
                        "type": "module_must_contain",
                        "modulePath": MODULE_PATH,
                        "value": payload,
                    }
                ],
            }
        ]},
    }
    package.mkdir()
    (package / "patch.json").write_text(json.dumps(manifest))


def build(tmp_path: Path, source: Path, package_dirs: list[Path], out: str):
    return build_patchset_v15(
        BuildRequestV15(
            source_path=source,
            output_dir=tmp_path / out,
            package_dirs=package_dirs,
            source_version="fixture",
            source_version_output="fixture (Claude Code)",
            platform="darwin",
            arch="arm64",
            command_runner=runner,
        )
    )


def output_module(report) -> bytes:
    data = Path(report.outputPath).read_bytes()
    layout = find_macho_layout(data)
    graph = parse_bun_section(
        data[layout.bun_section.offset : layout.bun_section.offset + layout.bun_section.size]
    )
    return graph.module_by_path(MODULE_PATH).content


def test_two_packages_share_one_anchor_deterministically(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "pkg-a"
    pkg_b = tmp_path / "pkg-b"
    write_package(pkg_a, source, "pkg-a", ",A_ENTRY", 100)
    write_package(pkg_b, source, "pkg-b", ",B_ENTRY", 200)

    report = build(tmp_path, source, [pkg_a, pkg_b], "out-ab")
    assert report.automatedStatus == "passed"
    module = output_module(report)
    assert b"OLD_RENDER,A_ENTRY,B_ENTRY" in module

    # determinism: reversed --package order produces identical module bytes
    report_ba = build(tmp_path, source, [pkg_b, pkg_a], "out-ba")
    assert report_ba.automatedStatus == "passed"
    assert output_module(report_ba) == module


def test_duplicate_insert_order_across_packages_fails_closed(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "pkg-a"
    pkg_b = tmp_path / "pkg-b"
    write_package(pkg_a, source, "pkg-a", ",A_ENTRY", 100)
    write_package(pkg_b, source, "pkg-b", ",B_ENTRY", 100)
    report = build(tmp_path, source, [pkg_a, pkg_b], "out")
    assert report.status == "failed"
    assert report.failureReason.startswith("patch_conflict:insert_order_duplicate")


def test_insertion_composes_with_disjoint_replacement_package(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "pkg-a"
    write_package(pkg_a, source, "pkg-a", ",A_ENTRY", 100)
    # replacement package owning a disjoint span ("return 1")
    pkg_c = tmp_path / "pkg-c"
    manifest = json.loads((pkg_a / "patch.json").read_text())
    manifest["id"] = "pkg-c"
    manifest["label"] = "pkg-c"
    manifest["patch"]["targets"][0]["modules"][0]["operations"] = [
        {
            "opId": "pkg-c-replace",
            "label": "Replace return",
            "type": "replace_exact",
            "exact": "return 1",
            "replacement": {"inline": "return 2"},
        }
    ]
    manifest["patch"]["targets"][0]["postconditions"] = [
        {"type": "module_must_contain", "modulePath": MODULE_PATH, "value": "return 2"}
    ]
    pkg_c.mkdir()
    (pkg_c / "patch.json").write_text(json.dumps(manifest))

    report = build(tmp_path, source, [pkg_a, pkg_c], "out")
    assert report.automatedStatus == "passed"
    module = output_module(report)
    assert b"OLD_RENDER,A_ENTRY" in module
    assert b"return 2" in module
