from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.fixtures_bun import MODULE_0, build_aligned_macho_fixture

from harnessmonkey.builder_v15 import BuildRequestV15, build_patchset_v15
from harnessmonkey.package_model import PackageKind, load_package_manifest, manifest_digest
from harnessmonkey.reports_v2 import BuildReportV2
from harnessmonkey.smoke import CommandResult


def successful_fixture_runner(argv):
    if argv[0] == "codesign" and "--verify" in argv:
        return CommandResult(argv=argv, returncode=0, stdout="", stderr="valid")
    if argv[0] == "codesign":
        return CommandResult(argv=argv, returncode=0, stdout="", stderr="signed")
    if argv[-1] == "--version":
        return CommandResult(argv=argv, returncode=0, stdout="fixture\n", stderr="")
    if argv[-1] == "--help":
        return CommandResult(
            argv=argv,
            returncode=0,
            stdout="Usage: claude [options]\nClaude Code help\n",
            stderr="",
        )
    return CommandResult(argv=argv, returncode=1, stdout="", stderr="unexpected")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def v3_patch_manifest(package_id: str, source: Path, *, target_sha: str | None = None) -> dict:
    source_bytes = source.read_bytes()
    old = MODULE_0[: MODULE_0.index(b"function after(){")]
    return {
        "schemaVersion": 1,
        "kind": "patch",
        "id": package_id,
        "label": "Demo Patch",
        "description": "V3 patch envelope",
        "risk": {"level": "low"},
        "patch": {
            "engine": "bun_graph_repack",
            "targets": [
                {
                    "sourceIdentity": {
                        "claudeVersion": "fixture",
                        "versionOutput": "fixture",
                        "sha256": target_sha or hashlib.sha256(source_bytes).hexdigest(),
                        "sizeBytes": len(source_bytes),
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
                                    "replacement": {
                                        "inline": "function render(){NEW_RENDER_LONGER}\n"
                                    },
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
                    "manualSmoke": {"required": False},
                }
            ],
        },
    }


def write_v3_patch_package(
    package_dir: Path, source: Path, *, target_sha: str | None = None
) -> str:
    manifest = v3_patch_manifest(package_dir.name, source, target_sha=target_sha)
    write_json(package_dir / f"{package_dir.name}.json", manifest)
    return manifest_digest(load_package_manifest(package_dir, PackageKind.PATCH))


def request_for(
    source: Path,
    output_dir: Path,
    package_dir: Path,
    digest: str,
    *,
    command_runner=successful_fixture_runner,
) -> BuildRequestV15:
    return BuildRequestV15(
        source_path=source,
        output_dir=output_dir,
        package_dirs=[package_dir],
        source_version="fixture",
        source_version_output="fixture",
        platform="darwin",
        arch="arm64",
        command_runner=command_runner,
        manifest_digests={package_dir.name: digest},
        build_input_snapshot={
            "patches": [package_dir.name],
            "promptAtBuildTime": "research",
            "optionsAtBuildTime": ["local-session-defaults"],
        },
    )


def test_v3_patch_package_success_report_includes_summary_envelope_fields(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    package = tmp_path / "demo-patch"
    digest = write_v3_patch_package(package, source)

    report = build_patchset_v15(request_for(source, tmp_path / "out", package, digest))

    raw = json.loads((tmp_path / "out" / "build-report.json").read_text())
    assert report.status == "verified"
    assert raw["schemaVersion"] == 3
    assert raw["packageManifestDigests"] == {"demo-patch": digest}
    assert raw["sourceIdentity"] == {
        "claudeVersion": "fixture",
        "versionOutput": "fixture",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sizeBytes": source.stat().st_size,
        "platform": "darwin",
        "arch": "arm64",
    }
    assert raw["buildInputSnapshot"] == {
        "patches": ["demo-patch"],
        "promptAtBuildTime": "research",
        "optionsAtBuildTime": ["local-session-defaults"],
    }
    assert raw["compatibility"] == {"status": "compatible", "warnings": []}
    assert raw["enabledPatches"] == ["demo-patch"]


def test_v3_patch_package_failure_report_preserves_summary_envelope_fields(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(b"x" * 123)
    package = tmp_path / "demo-patch"
    digest = write_v3_patch_package(package, source, target_sha="0" * 64)

    report = build_patchset_v15(request_for(source, tmp_path / "out", package, digest))

    raw = json.loads((tmp_path / "out" / "build-report.json").read_text())
    assert report.status == "failed"
    assert raw["schemaVersion"] == 3
    assert raw["packageManifestDigests"] == {"demo-patch": digest}
    assert raw["sourceIdentity"] == {
        "claudeVersion": "fixture",
        "versionOutput": "fixture",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sizeBytes": 123,
        "platform": "darwin",
        "arch": "arm64",
    }
    assert raw["buildInputSnapshot"] == {
        "patches": ["demo-patch"],
        "promptAtBuildTime": "research",
        "optionsAtBuildTime": ["local-session-defaults"],
    }
    assert raw["compatibility"] == {"status": "source_sha_mismatch", "warnings": []}
    assert "source_identity_mismatch:demo-patch" in raw["failureReason"]


def test_invalid_v3_patch_package_writes_failure_report_with_summary_fields(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    package = tmp_path / "demo-patch"
    write_json(
        package / "demo-patch.json",
        {
            "schemaVersion": 1,
            "kind": "patch",
            "id": "different-id",
            "label": "Demo Patch",
            "description": "Invalid V3 patch envelope",
            "patch": {"engine": "bun_graph_repack", "targets": []},
        },
    )

    report = build_patchset_v15(request_for(source, tmp_path / "out", package, "0" * 64))

    raw = json.loads((tmp_path / "out" / "build-report.json").read_text())
    assert report.status == "failed"
    assert raw["schemaVersion"] == 3
    assert raw["packageManifestDigests"] == {"demo-patch": "0" * 64}
    assert raw["sourceIdentity"] == {
        "claudeVersion": "fixture",
        "versionOutput": "fixture",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sizeBytes": source.stat().st_size,
        "platform": "darwin",
        "arch": "arm64",
    }
    assert raw["buildInputSnapshot"] == {
        "patches": ["demo-patch"],
        "promptAtBuildTime": "research",
        "optionsAtBuildTime": ["local-session-defaults"],
    }
    assert raw["compatibility"] == {"status": "package_manifest_invalid", "warnings": []}
    assert "package_manifest_invalid:demo-patch" in raw["failureReason"]


def test_malformed_patch_json_writes_failure_report_with_summary_fields(tmp_path):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    package = tmp_path / "demo-patch"
    package.mkdir()
    (package / "patch.json").write_text("{not json")

    report = build_patchset_v15(request_for(source, tmp_path / "out", package, "0" * 64))

    raw = json.loads((tmp_path / "out" / "build-report.json").read_text())
    assert report.status == "failed"
    assert raw["schemaVersion"] == 3
    assert raw["packageManifestDigests"] == {"demo-patch": "0" * 64}
    assert raw["sourceIdentity"] == {
        "claudeVersion": "fixture",
        "versionOutput": "fixture",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sizeBytes": source.stat().st_size,
        "platform": "darwin",
        "arch": "arm64",
    }
    assert raw["buildInputSnapshot"] == {
        "patches": ["demo-patch"],
        "promptAtBuildTime": "research",
        "optionsAtBuildTime": ["local-session-defaults"],
    }
    assert "manifest_v2_invalid:" in raw["failureReason"]


def test_failure_report_write_error_keeps_original_failure_reason_visible(
    tmp_path, monkeypatch
):
    source = tmp_path / "claude-source"
    source.write_bytes(build_aligned_macho_fixture()[0])
    package = tmp_path / "demo-patch"
    write_json(
        package / "demo-patch.json",
        {
            "schemaVersion": 1,
            "kind": "patch",
            "id": "different-id",
            "label": "Demo Patch",
            "description": "Invalid V3 patch envelope",
            "patch": {"engine": "bun_graph_repack", "targets": []},
        },
    )

    def fail_write(self, path):
        raise OSError("disk full")

    monkeypatch.setattr(BuildReportV2, "write", fail_write)

    report = build_patchset_v15(request_for(source, tmp_path / "out", package, "0" * 64))

    assert report.status == "failed"
    assert "package_manifest_invalid:demo-patch" in report.failureReason
    assert "report_write_failed:OSError: disk full" in report.failureReason
