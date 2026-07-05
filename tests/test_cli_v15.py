from __future__ import annotations

import json

from tests.fixtures_bun import build_aligned_macho_fixture, build_macho_fixture

from harnessmonkey.builder_v15 import BuildRequestV15
from harnessmonkey.cli import main
from harnessmonkey.reports_v2 import BuildReportV2


def read_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_inspect_binary_json_command(tmp_path, capsys):
    binary = tmp_path / "claude"
    binary.write_bytes(build_macho_fixture()[0])
    assert main(["inspect-binary", "--source", str(binary), "--json"]) == 0
    payload = read_json(capsys)
    assert payload["ok"] is True
    assert payload["sourcePath"] == str(binary)
    assert payload["modules"][0]["path"] == "/$bunfs/root/src/entrypoints/cli.js"


def test_validate_package_json_resolves_module_operation(tmp_path, capsys):
    import hashlib

    from tests.fixtures_bun import MODULE_0, build_macho_fixture

    binary = tmp_path / "claude"
    binary.write_bytes(build_macho_fixture()[0])
    old = MODULE_0[: MODULE_0.index(b"function after(){")]
    package = tmp_path / "pkg"
    package.mkdir()
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "pkg",
        "label": "Fixture V1.5",
        "description": "Fixture package",
        "packageVersion": "0.1.0",
        "patch": {"engine": "bun_graph_repack", "targets": [
            {
                "sourceIdentity": {
                    "claudeVersion": "fixture",
                    "versionOutput": "fixture",
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
                "manualSmoke": {"required": False},
            }
        ]},
    }
    (package / "patch.json").write_text(json.dumps(manifest))
    assert (
        main(
            [
                "validate-package",
                "--source",
                str(binary),
                "--package",
                str(package),
                "--source-version",
                "fixture",
                "--source-version-output",
                "fixture",
                "--json",
            ]
        )
        == 0
    )
    payload = read_json(capsys)
    assert payload["ok"] is True
    assert payload["operationsResolved"][0]["moduleStart"] == 0
    assert payload["operationsResolved"][0]["newLen"] > payload["operationsResolved"][0]["oldLen"]


def test_build_json_uses_v15_repack_engine_with_skip_gates(tmp_path, capsys):
    from tests.test_builder_v15 import write_fixture_package

    binary = tmp_path / "claude"
    binary.write_bytes(build_aligned_macho_fixture()[0])
    package = tmp_path / "fixture-v15"
    write_fixture_package(package, binary)
    out_dir = tmp_path / "out"

    assert (
        main(
            [
                "build",
                "--source",
                str(binary),
                "--package",
                str(package),
                "--output-dir",
                str(out_dir),
                "--source-version",
                "fixture",
                "--source-version-output",
                "fixture (Claude Code)",
                "--platform",
                "darwin",
                "--arch",
                "arm64",
                "--skip-signing",
                "--skip-smoke",
                "--json",
            ]
        )
        == 1
    )
    payload = read_json(capsys)
    assert payload["schemaVersion"] == 1
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["buildStrategy"] == "bun_graph_repack"
    assert payload["buildReportStatus"] == "skipped_gates"
    assert payload["error"]["code"] == "build_failed"
    assert (out_dir / "claude").exists()


def test_build_manual_smoke_pending_does_not_set_active_patchset(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_bytes(build_macho_fixture()[0])
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "patch.json").write_text("{}")

    def fake_build(request):
        request.output_dir.mkdir(parents=True, exist_ok=True)
        report = BuildReportV2(
            status="manual_smoke_pending",
            automatedStatus="passed",
            sourceClaudePath=str(source),
            sourceVersion="fixture",
            sourceVersionOutput="fixture (Claude Code)",
            activationEligible=False,
            activationBlockers=["manual_smoke_pending"],
        )
        report.outputPath = str(request.output_dir / "claude")
        return report

    monkeypatch.setattr("harnessmonkey.cli.build_patchset_v15", fake_build)

    rc = main(
        [
            "build",
            "--source",
            str(source),
            "--package",
            str(package),
            "--output-dir",
            str(tmp_path / "out"),
            "--source-version",
            "fixture",
            "--source-version-output",
            "fixture (Claude Code)",
        ]
    )

    assert rc == 0
    assert "manual_smoke_pending" in capsys.readouterr().out
    config_path = tmp_path / "home" / ".harnessmonkey" / "config.json"
    if config_path.exists():
        assert json.loads(config_path.read_text())["activePatchSet"] is None


def test_build_explicit_v3_package_snapshot_uses_actual_package_ids(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_bytes(b"source")
    package = tmp_path / "demo-patch"
    package.mkdir()
    (package / "demo-patch.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "patch",
                "id": "demo-patch",
                "label": "Demo Patch",
                "description": "Demo package",
                "patch": {"engine": "bun_graph_repack", "targets": []},
            }
        )
    )
    captured: dict[str, BuildRequestV15] = {}

    def fake_build(request: BuildRequestV15) -> BuildReportV2:
        captured["request"] = request
        request.output_dir.mkdir(parents=True, exist_ok=True)
        return BuildReportV2(
            status="verified",
            automatedStatus="passed",
            sourceClaudePath=str(source),
            sourceVersion="fixture",
            sourceVersionOutput="fixture (Claude Code)",
            activationEligible=True,
            activationStatus="skipped",
            enabledPatches=["demo-patch"],
        )

    monkeypatch.setattr("harnessmonkey.cli.build_patchset_v15", fake_build)

    assert (
        main(
            [
                "build",
                "--source",
                str(source),
                "--package",
                str(package),
                "--output-dir",
                str(tmp_path / "out"),
                "--source-version",
                "fixture",
                "--source-version-output",
                "fixture (Claude Code)",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True
    request = captured["request"]
    assert request.build_input_snapshot["patches"] == ["demo-patch"]
    assert list(request.manifest_digests) == ["demo-patch"]


def test_validate_package_json_reports_schema_v1_without_traceback(tmp_path, capsys):
    binary = tmp_path / "claude"
    binary.write_bytes(b"notmacho")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "patch.json").write_text(json.dumps({"schemaVersion": 1}))

    rc = main(
        [
            "validate-package",
            "--source",
            str(binary),
            "--package",
            str(package),
            "--source-version",
            "fixture",
            "--source-version-output",
            "fixture",
            "--json",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["errorCode"] == "unsupported_manifest_format: expected schemaVersion 1 with kind"


def test_validate_package_json_reports_invalid_v3_envelope_with_machine_code(
    tmp_path, capsys
):
    binary = tmp_path / "claude"
    binary.write_bytes(b"notmacho")
    package = tmp_path / "demo-patch"
    package.mkdir()
    (package / "demo-patch.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "patch",
                "id": "different-id",
                "label": "Demo Patch",
                "description": "Invalid V3 patch envelope",
                "patch": {"engine": "bun_graph_repack", "targets": []},
            }
        )
    )

    rc = main(
        [
            "validate-package",
            "--source",
            str(binary),
            "--package",
            str(package),
            "--source-version",
            "fixture",
            "--source-version-output",
            "fixture",
            "--json",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["errorCode"] == "package_manifest_invalid"


def test_validate_package_json_reports_non_macho_without_traceback(tmp_path, capsys):
    package = tmp_path / "pkg"
    package.mkdir()
    binary = tmp_path / "claude"
    binary.write_bytes(b"notmacho")
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "pkg",
        "label": "Fixture V1.5",
        "description": "Fixture package",
        "packageVersion": "0.1.0",
        "patch": {"engine": "bun_graph_repack", "targets": [
            {
                "sourceIdentity": {
                    "claudeVersion": "fixture",
                    "versionOutput": "fixture",
                    "sha256": "0" * 64,
                    "sizeBytes": 8,
                    "platform": "darwin",
                    "arch": "arm64",
                },
                "requiredEngine": "bun_graph_repack",
                "requiredBinaryFormat": "bun_standalone_macho64",
                "modules": [
                    {
                        "path": "/$bunfs/root/src/entrypoints/cli.js",
                        "contentSha256": "1" * 64,
                        "contentLength": 1,
                        "operations": [
                            {
                                "opId": "replace-renderer",
                                "label": "Replace renderer",
                                "type": "replace_exact",
                                "exact": "x",
                                "replacement": {"inline": "y"},
                            }
                        ],
                    }
                ],
            }
        ]},
    }
    import hashlib

    manifest["patch"]["targets"][0]["sourceIdentity"]["sha256"] = hashlib.sha256(
        binary.read_bytes()
    ).hexdigest()
    (package / "patch.json").write_text(json.dumps(manifest))

    rc = main(
        [
            "validate-package",
            "--source",
            str(binary),
            "--package",
            str(package),
            "--source-version",
            "fixture",
            "--source-version-output",
            "fixture",
            "--platform",
            "darwin",
            "--arch",
            "arm64",
            "--json",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    # Container-format detection now runs before Mach-O-specific parsing (so PE
    # inputs can be routed correctly too), so unrecognized bytes are reported as
    # a generic unknown-format validation failure rather than a Mach-O-specific
    # magic error.
    assert payload["errorCode"] == "validation_failed"
    assert any("unknown_binary_format" in err for err in payload["errors"])
