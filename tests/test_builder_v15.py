from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from tests.builder_fixtures import write_fixture_package  # noqa: F401 - re-exported for other tests
from tests.fixtures_bun import MODULE_0, MODULE_1, MODULE_PATH_1, build_aligned_macho_fixture

from harnessmonkey.builder_v15 import BuildRequestV15, build_patchset_v15, load_manifest_v2
from harnessmonkey.manifest_v2 import ManifestV2Error
from harnessmonkey.smoke import CommandResult

pytest_plugins = ["tests.builder_fixtures"]




def test_flat_v2_manifest_rejected(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "patch.json").write_text(json.dumps({
        "schemaVersion": 2, "id": "x", "name": "X", "description": "d",
        "packageVersion": "0.0.1", "targets": [],
    }))
    with pytest.raises(ManifestV2Error, match="unsupported_manifest_format"):
        load_manifest_v2(pkg)


def test_schema_one_without_kind_rejected(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "patch.json").write_text(json.dumps({"schemaVersion": 1, "id": "x"}))
    with pytest.raises(ManifestV2Error, match="unsupported_manifest_format"):
        load_manifest_v2(pkg)


def test_build_patchset_v15_writes_copied_output_and_report(successful_build_request):
    request = successful_build_request()
    source = request.source_path
    report = build_patchset_v15(request)
    assert report.automatedStatus == "passed"
    assert report.activationEligible is True
    assert report.outputPath is not None
    assert Path(report.outputPath).exists()
    assert source.read_bytes() == build_aligned_macho_fixture()[0]


def test_build_patchset_v15_activates_despite_manual_smoke_flag(successful_build_request):
    # The manual-smoke activation gate is disabled: there is no GUI affordance to
    # perform manual smoke/activation, so a package declaring manualSmoke.required
    # no longer blocks activation. A successful build (automated validation
    # passing) activates directly; see builder_v15.py for the bypass comment.
    report = build_patchset_v15(successful_build_request(manual_smoke=True))
    assert report.status == "verified"
    assert report.activationEligible is True
    assert "manual_smoke_pending" not in report.activationBlockers
    assert report.manualSmoke["required"] is True
    assert report.manualSmoke["status"] == "bypassed"


def test_build_patchset_v15_activate_true_activates_with_manual_smoke_flag(
    successful_build_request, tmp_path
):
    # End-to-end version of the bypass: with --activate requested and a real
    # current_path target, a build from a manualSmoke-required package activates
    # the symlink directly instead of stalling with activationStatus="blocked".
    current_path = tmp_path / "current" / "claude"
    request = successful_build_request(manual_smoke=True, activate=True, current_path=current_path)
    report = build_patchset_v15(request)
    assert report.status == "verified"
    assert report.activationStatus == "activated"
    assert current_path.is_symlink()


def test_unsupported_manifest_format_fails_build(bad_manifest_build_request):
    report = build_patchset_v15(bad_manifest_build_request())
    assert report.status == "failed"
    assert report.failureReason == (
        "manifest_v2_invalid:unsupported_manifest_format: "
        "expected schemaVersion 1 with kind"
    )


def test_source_identity_mismatch_report_names_current_and_target(successful_build_request):
    report = build_patchset_v15(
        successful_build_request(
            source_version="2.1.199",
            source_version_output="2.1.199 (Claude Code)",
        )
    )

    assert report.status == "failed"
    assert report.failureReason is not None
    assert "source_identity_mismatch:fixture-v15" in report.failureReason
    assert "current source is Claude 2.1.199" in report.failureReason
    assert "package targets Claude fixture" in report.failureReason


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


def write_insertion_package(
    package: Path,
    binary: Path,
    *,
    package_id: str,
    payload: str,
    insert_order: int,
    postcondition_value: str,
) -> None:
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": package_id,
        "label": package_id,
        "description": "Insertion fixture",
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
                                "opId": f"{package_id}-insert",
                                "label": "Insert entry",
                                "type": "insert_after",
                                "anchor": "OLD_RENDER",
                                "insertOrder": insert_order,
                                "seamHint": "fixture.afterOldRender",
                                "replacement": {"inline": payload},
                            }
                        ],
                    }
                ],
                "postconditions": [
                    {
                        "type": "module_must_contain",
                        "modulePath": "/$bunfs/root/src/entrypoints/cli.js",
                        "value": postcondition_value,
                    }
                ],
            }
        ]},
    }
    package.mkdir(parents=True)
    (package / "patch.json").write_text(json.dumps(manifest))


def _build(tmp_path, source, package_dirs):
    return build_patchset_v15(
        BuildRequestV15(
            source_path=source,
            output_dir=tmp_path / "out",
            package_dirs=package_dirs,
            source_version="fixture",
            source_version_output="fixture (Claude Code)",
            platform="darwin",
            arch="arm64",
            command_runner=successful_runner,
        )
    )


def test_insertion_build_reports_evidence_and_extended_fields(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg = tmp_path / "pkg-a"
    write_insertion_package(
        pkg, source, package_id="pkg-a", payload=",A_ENTRY",
        insert_order=100, postcondition_value="A_ENTRY",
    )
    report = _build(tmp_path, source, [pkg])
    assert report.automatedStatus == "passed"
    applied = report.operationsApplied[0]
    assert applied["type"] == "insert_after"
    assert applied["kind"] == "insertion"
    assert applied["insertOrder"] == 100
    assert applied["anchor"] == "OLD_RENDER"
    assert applied["seamHint"] == "fixture.afterOldRender"
    assert applied["insertionVerified"] is True
    assert applied["oldLen"] == 0
    assert applied["moduleStart"] == applied["moduleEnd"]
    assert isinstance(applied["finalOffset"], int)


def test_composition_sensitive_postcondition_fails_build(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "pkg-a"
    pkg_b = tmp_path / "pkg-b"
    write_insertion_package(
        pkg_a, source, package_id="pkg-a", payload=",A_ENTRY",
        insert_order=100,
        postcondition_value="OLD_RENDER,A_ENTRY",  # asserts adjacency across a SHARED point
    )
    write_insertion_package(
        pkg_b, source, package_id="pkg-b", payload=",B_ENTRY",
        insert_order=200, postcondition_value="B_ENTRY",
    )
    report = _build(tmp_path, source, [pkg_a, pkg_b])
    assert report.status == "failed"
    assert report.failureReason.startswith("postcondition_composition_sensitive:pkg-a")



def _add_relationships(package: Path, *, requires=None, conflicts=None) -> None:
    manifest = json.loads((package / "patch.json").read_text())
    if requires is not None:
        manifest["requiresPackages"] = requires
    if conflicts is not None:
        manifest["conflictsWithPackages"] = conflicts
    (package / "patch.json").write_text(json.dumps(manifest))


def test_required_package_missing_fails_before_planning(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg = tmp_path / "pkg-a"
    write_insertion_package(
        pkg, source, package_id="pkg-a", payload=",A_ENTRY",
        insert_order=100, postcondition_value="A_ENTRY",
    )
    _add_relationships(pkg, requires=["drawer-dock"])
    report = _build(tmp_path, source, [pkg])
    assert report.status == "failed"
    assert report.failureReason == "patch_conflict:required_package_missing:pkg-a:drawer-dock"


def test_package_conflict_fails_before_planning(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "pkg-a"
    pkg_b = tmp_path / "pkg-b"
    write_insertion_package(
        pkg_a, source, package_id="pkg-a", payload=",A_ENTRY",
        insert_order=100, postcondition_value="A_ENTRY",
    )
    write_insertion_package(
        pkg_b, source, package_id="pkg-b", payload=",B_ENTRY",
        insert_order=200, postcondition_value="B_ENTRY",
    )
    _add_relationships(pkg_a, conflicts=["pkg-b"])
    report = _build(tmp_path, source, [pkg_a, pkg_b])
    assert report.status == "failed"
    assert report.failureReason == "patch_conflict:package_conflict:pkg-a:pkg-b"


def test_requirements_satisfied_build_passes(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "pkg-a"
    pkg_b = tmp_path / "pkg-b"
    write_insertion_package(
        pkg_a, source, package_id="pkg-a", payload=",A_ENTRY",
        insert_order=100, postcondition_value="A_ENTRY",
    )
    write_insertion_package(
        pkg_b, source, package_id="pkg-b", payload=",B_ENTRY",
        insert_order=200, postcondition_value="B_ENTRY",
    )
    _add_relationships(pkg_a, requires=["pkg-b"])
    report = _build(tmp_path, source, [pkg_a, pkg_b])
    assert report.automatedStatus == "passed"



def test_v3_bridge_carries_relationship_metadata(tmp_path):
    from harnessmonkey.builder_v15 import _v3_manifest_as_v2_dict

    package_dir = tmp_path / "thin-drawer"
    package_dir.mkdir()
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "thin-drawer",
        "label": "Thin drawer",
        "description": "Fixture",
        "requiresPackages": ["drawer-dock"],
        "patch": {"engine": "bun_graph_repack", "targets": [{}]},
    }
    (package_dir / "package.json").write_text(json.dumps(manifest))
    bridged = _v3_manifest_as_v2_dict(package_dir)
    assert bridged["requiresPackages"] == ["drawer-dock"]
    assert bridged["conflictsWithPackages"] == []



def test_operations_applied_report_uses_render_order_for_shared_insertions(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "pkg-a"
    pkg_b = tmp_path / "pkg-b"
    write_insertion_package(
        pkg_a, source, package_id="pkg-a", payload=",A_ENTRY",
        insert_order=100, postcondition_value="A_ENTRY",
    )
    write_insertion_package(
        pkg_b, source, package_id="pkg-b", payload=",B_ENTRY",
        insert_order=200, postcondition_value="B_ENTRY",
    )

    report = _build(tmp_path, source, [pkg_b, pkg_a])

    assert report.automatedStatus == "passed"
    assert [item["opId"] for item in report.operationsApplied] == [
        "pkg-a-insert",
        "pkg-b-insert",
    ]
    assert [item["finalOffset"] for item in report.operationsApplied] == sorted(
        item["finalOffset"] for item in report.operationsApplied
    )



def write_module1_marker_package(package: Path, binary: Path) -> None:
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "module-one-guard",
        "label": "Module One Guard",
        "description": "Module one postcondition fixture",
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
                        "path": MODULE_PATH_1,
                        "contentSha256": hashlib.sha256(MODULE_1).hexdigest(),
                        "contentLength": len(MODULE_1),
                        "operations": [
                            {
                                "opId": "noop-other",
                                "label": "Keep other module stable",
                                "type": "replace_exact",
                                "exact": "true",
                                "replacement": {"inline": "true"},
                            }
                        ],
                    }
                ],
                "postconditions": [
                    {
                        "type": "module_must_not_contain",
                        "modulePath": MODULE_PATH_1,
                        "value": "OLD_RENDER",
                    }
                ],
            }
        ]},
    }
    package.mkdir(parents=True)
    (package / "patch.json").write_text(json.dumps(manifest))


def test_composition_sensitive_postcondition_scoped_to_assertion_module(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "pkg-a"
    pkg_b = tmp_path / "pkg-b"
    guard = tmp_path / "module-one-guard"
    write_insertion_package(
        pkg_a, source, package_id="pkg-a", payload=",A_ENTRY",
        insert_order=100, postcondition_value="A_ENTRY",
    )
    write_insertion_package(
        pkg_b, source, package_id="pkg-b", payload=",B_ENTRY",
        insert_order=200, postcondition_value="B_ENTRY",
    )
    write_module1_marker_package(guard, source)

    report = _build(tmp_path, source, [pkg_a, pkg_b, guard])

    assert report.automatedStatus == "passed"


def test_duplicate_package_id_fails_before_planning(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    pkg_a = tmp_path / "left" / "pkg-a"
    pkg_copy = tmp_path / "right" / "pkg-a"
    write_insertion_package(
        pkg_a, source, package_id="pkg-a", payload=",A_ENTRY",
        insert_order=100, postcondition_value="A_ENTRY",
    )
    write_insertion_package(
        pkg_copy, source, package_id="pkg-a", payload=",COPY_ENTRY",
        insert_order=200, postcondition_value="COPY_ENTRY",
    )

    report = _build(tmp_path, source, [pkg_a, pkg_copy])

    assert report.status == "failed"
    assert report.failureReason == "duplicate_package_id:pkg-a:pkg-a"
