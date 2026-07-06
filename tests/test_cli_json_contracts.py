from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from harnessmonkey import repair as repair_module
from harnessmonkey import source_discovery
from harnessmonkey.cli import main
from harnessmonkey.install import _unlock_target


@pytest.fixture(autouse=True)
def _tiny_plausible_official_size_floor(monkeypatch):
    """This file's fake "official"/replacement binaries are tiny shell-script
    fixtures, not real ~230MB Claude binaries. Patch the CMux-incident size
    floor (`source_discovery.MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES`) down to 0
    (no floor) so those fixtures classify as "plausible official" and
    install-shim's plausibility gate doesn't refuse them here -- the real,
    unpatched 50MB floor is exercised end-to-end by
    tests/test_plausible_official_size_floor.py.
    """
    monkeypatch.setattr(source_discovery, "MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES", 0)


def parse_json_output(capsys):
    out = capsys.readouterr().out
    return json.loads(out)


def test_status_json_contract(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["schemaVersion"] == 1
    assert payload["status"] in {"ok", "rebuild_required", "error", "not_installed", "unknown"}
    assert payload["stateDir"].endswith(".harnessmonkey")
    assert payload["logsDir"].endswith(".harnessmonkey/logs")
    assert isinstance(payload["desiredPatchIds"], list)
    assert isinstance(payload["activePatchIds"], list)
    assert "rebuildRequired" in payload
    assert payload["lastError"] is None or "message" in payload["lastError"]
    # Additive shim-update-resilience stage 1 fields (spec §1): a fresh HOME
    # with no install record was never managed by HarnessMonkey, so every new
    # field reports the empty/false/null case.
    assert payload["shimPreviouslyManaged"] is False
    assert payload["targetReplacedByOfficial"] is False
    assert payload["detectedOfficialSha256"] is None
    assert payload["detectedOfficialVersion"] is None
    assert payload["shimRepairAvailable"] is False
    assert payload["rolloutRequired"] is False
    # Reverted-shim visibility gap fix: never managed this machine -> null.
    assert payload["lastManagedTargetPath"] is None


def test_status_json_contract_shim_replaced_by_official_is_additive(
    monkeypatch, tmp_path, capsys
):
    """New detection fields must be additive and must not disturb existing
    consumers of shimInstalled/status (test_cli_json_contracts guards this
    per the spec's Non-goals + CLI/UI surfaces sections).
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "local-bin" / "claude"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    parse_json_output(capsys)

    assert main(["status", "--json"]) == 0
    payload_before = parse_json_output(capsys)
    assert payload_before["shimInstalled"] is True
    existing_keys = set(payload_before)

    official = tmp_path / "official-source" / "claude"
    official.parent.mkdir(parents=True)
    official.write_text("#!/bin/sh\necho '2.1.201 (Claude Code)'\n")
    official.chmod(official.stat().st_mode | 0o111)
    # Shim lock feature: a real locked shim can't be clobbered by an
    # external actor at all (that's the whole point -- see
    # tests/test_shim_lock.py), so lift the flag first to keep simulating
    # "already replaced" directly here.
    _unlock_target(target)
    target.unlink()
    target.symlink_to(official)

    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)

    # Existing consumers/fields are unaffected: same key set, and
    # shimInstalled correctly flips to False (the target is no longer the
    # bytes HarnessMonkey installed) -- unchanged semantics per the task spec.
    assert set(payload) == existing_keys
    assert payload["shimInstalled"] is False

    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    assert payload["shimPreviouslyManaged"] is True
    assert payload["targetReplacedByOfficial"] is True
    assert payload["detectedOfficialSha256"] == official_sha
    assert payload["shimRepairAvailable"] is True
    assert payload["rolloutRequired"] is True


def test_status_json_last_managed_target_path_is_additive_and_survives_revert(
    monkeypatch, tmp_path, capsys
):
    """Reverted-shim visibility gap fix: `lastManagedTargetPath` reports the
    install record's `targetPath` whenever a valid, HarnessMonkey-owned
    install-record.json exists -- REGARDLESS of whether `shimInstalled` is
    currently true -- so a consumer can distinguish "never managed this
    machine" (null) from "managed but something (e.g. the official Anthropic
    auto-updater) reverted the shim since" (non-null while shimInstalled is
    False). Purely additive: `installRecordPath`/`shimTargetPath` keep their
    existing `shimInstalled`-gated semantics unchanged.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "local-bin" / "claude"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    parse_json_output(capsys)

    assert main(["status", "--json"]) == 0
    payload_before = parse_json_output(capsys)
    assert payload_before["shimInstalled"] is True
    assert payload_before["lastManagedTargetPath"] == str(target)
    assert payload_before["shimTargetPath"] == str(target)
    assert payload_before["installRecordPath"] is not None
    existing_keys = set(payload_before)

    # The official Anthropic auto-updater (or anything else) reverts the
    # shim: same target path, different bytes.
    # Shim lock feature: a real locked shim can't be clobbered by an
    # external actor at all (see tests/test_shim_lock.py), so lift the flag
    # first to keep simulating the revert directly here.
    _unlock_target(target)
    target.unlink()
    target.write_text("#!/bin/sh\necho 'reverted by official updater'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["status", "--json"]) == 0
    payload_after = parse_json_output(capsys)

    # Additive: same key set as before.
    assert set(payload_after) == existing_keys
    # Existing, shimInstalled-gated fields keep their exact prior semantics
    # -- both go back to null the moment shimInstalled flips False.
    assert payload_after["shimInstalled"] is False
    assert payload_after["shimTargetPath"] is None
    assert payload_after["installRecordPath"] is None
    # The gap this closes: lastManagedTargetPath is NOT gated on
    # shimInstalled, so it stays populated -- this machine WAS managed, even
    # though something reverted the shim since.
    assert payload_after["lastManagedTargetPath"] == str(target)
    # This condition ("reverted since managed") is fully derivable from two
    # already-existing fields with no new boolean needed:
    assert payload_after["shimPreviouslyManaged"] is True
    assert payload_after["shimInstalled"] is False


def test_mutating_command_json_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["enable", "fable-fallback", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["schemaVersion"] == 1
    assert payload["ok"] is True
    assert payload["status"] in {"ok", "rebuild_required"}
    assert payload["summary"] == "enabled fable-fallback; rebuild required"
    assert payload["reportPath"] is None
    assert payload["targetPath"] is None
    assert payload["authorizationRequired"] is False
    assert payload["authorizationMethod"] is None
    assert payload["dryRun"] is False
    assert payload["plannedActions"] == []
    assert payload["error"] is None


def test_dry_run_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".harnessmonkey" / "bin" / "claude"
    assert main(["install-shim", "--target", str(target), "--json", "--dry-run"]) == 0
    payload = parse_json_output(capsys)
    assert payload["ok"] is True
    assert payload["dryRun"] is True
    assert payload["targetPath"] == str(target)
    assert "authorizationRequired" in payload
    assert isinstance(payload["plannedActions"], list)
    assert payload["error"] is None


def test_real_install_uninstall_json_wraps_cli_core_transaction(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".harnessmonkey" / "bin" / "claude"
    # Current install_shim_transaction does not require a built current symlink;
    # this is a real disposable user-writable install path.
    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    install_payload = parse_json_output(capsys)
    assert install_payload["ok"] is True
    assert install_payload["dryRun"] is False
    assert install_payload["targetPath"] == str(target)

    assert main(["uninstall-shim", "--target", str(target), "--json"]) == 0
    uninstall_payload = parse_json_output(capsys)
    assert uninstall_payload["ok"] is True
    assert uninstall_payload["dryRun"] is False
    assert uninstall_payload["targetPath"] == str(target)


def test_fresh_status_json_is_not_installed(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["status"] == "not_installed"
    assert payload["currentClaudePath"] is None
    assert payload["latestBuildReportPath"] is None


def test_build_json_preflight_failure_is_error_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    missing = tmp_path / "missing-claude"
    assert main(["build", "--source", str(missing), "--json"]) == 2
    payload = parse_json_output(capsys)
    assert payload["schemaVersion"] == 1
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error"]["message"] == f"source does not exist: {missing}"


def test_build_json_success_uses_command_envelope_schema(monkeypatch, tmp_path, capsys):
    from harnessmonkey.reports_v2 import BuildReportV2

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_text("source")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "patch.json").write_text("{}")

    def fake_build(request):
        request.output_dir.mkdir(parents=True, exist_ok=True)
        report = BuildReportV2(
            status="verified",
            automatedStatus="passed",
            sourceClaudePath=str(source),
            sourceVersion="fixture",
            sourceVersionOutput="fixture (Claude Code)",
            activationEligible=True,
            activationStatus="activated",
        )
        report.outputPath = str(request.output_dir / "claude")
        return report

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
    payload = parse_json_output(capsys)
    assert payload["schemaVersion"] == 1
    assert payload["ok"] is True
    assert payload["summary"] == "Build activated"
    assert payload["error"] is None
    assert payload["reportPath"] == str(tmp_path / "out" / "build-report.json")


def test_list_patches_json_reports_source_version_mismatch(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_bytes(b"latest source")
    package_root = tmp_path / "packages"
    package = package_root / "fable-fallback"
    package.mkdir(parents=True)
    (package / "patch.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "id": "fable-fallback",
                "name": "Fable fallback visibility",
                "targets": [
                    {
                        "sourceIdentity": {
                            "claudeVersion": "2.1.198",
                            "versionOutput": "2.1.198 (Claude Code)",
                            "sha256": "a" * 64,
                            "sizeBytes": 229328464,
                            "platform": "darwin",
                            "arch": "arm64",
                        }
                    }
                ],
            }
        )
    )
    monkeypatch.setattr("harnessmonkey.cli._package_roots", lambda paths: [package_root])
    monkeypatch.setattr("harnessmonkey.cli._discover_source", lambda source_arg: source)
    monkeypatch.setattr(
        "harnessmonkey.cli._source_version_output",
        lambda source_path, explicit_output: "2.1.199 (Claude Code)",
    )

    assert main(["list-patches", "--json"]) == 0
    payload = parse_json_output(capsys)
    patch = payload["patches"][0]
    assert patch["compatibilityStatus"] == "version_mismatch"
    assert "Package targets Claude 2.1.198" in patch["compatibilityMessage"]
    assert "current source is 2.1.199" in patch["compatibilityMessage"]


def test_list_patches_json_reports_exact_source_compatibility(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_bytes(b"latest source")
    package_root = tmp_path / "packages"
    package = package_root / "fable-fallback"
    package.mkdir(parents=True)
    (package / "patch.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "id": "fable-fallback",
                "name": "Fable fallback visibility",
                "targets": [
                    {
                        "sourceIdentity": {
                            "claudeVersion": "2.1.199",
                            "versionOutput": "2.1.199 (Claude Code)",
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                            "sizeBytes": source.stat().st_size,
                            "platform": "darwin",
                            "arch": "arm64",
                        }
                    }
                ],
            }
        )
    )
    monkeypatch.setattr("harnessmonkey.cli._package_roots", lambda paths: [package_root])
    monkeypatch.setattr("harnessmonkey.cli._discover_source", lambda source_arg: source)
    monkeypatch.setattr(
        "harnessmonkey.cli._source_version_output",
        lambda source_path, explicit_output: "2.1.199 (Claude Code)",
    )

    assert main(["list-patches", "--json"]) == 0
    payload = parse_json_output(capsys)
    patch = payload["patches"][0]
    assert patch["compatibilityStatus"] == "compatible"
    assert patch["compatibilityMessage"] == "Compatible with current source 2.1.199."


def test_list_patches_json_requires_exact_builder_source_identity(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_bytes(b"latest source")
    package_root = tmp_path / "packages"
    package = package_root / "fable-fallback"
    package.mkdir(parents=True)
    (package / "patch.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "id": "fable-fallback",
                "name": "Fable fallback visibility",
                "targets": [
                    {
                        "sourceIdentity": {
                            "claudeVersion": "2.1.199",
                            "versionOutput": "2.1.199-beta (Claude Code)",
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                            "sizeBytes": source.stat().st_size,
                            "platform": "linux",
                            "arch": "x86_64",
                        }
                    }
                ],
            }
        )
    )
    monkeypatch.setattr("harnessmonkey.cli._package_roots", lambda paths: [package_root])
    monkeypatch.setattr("harnessmonkey.cli._discover_source", lambda source_arg: source)
    monkeypatch.setattr(
        "harnessmonkey.cli._source_version_output",
        lambda source_path, explicit_output: "2.1.199 (Claude Code)",
    )
    monkeypatch.setattr("harnessmonkey.cli.sys.platform", "darwin")
    monkeypatch.setattr("harnessmonkey.cli.platform_module.machine", lambda: "arm64")

    assert main(["list-patches", "--json"]) == 0
    payload = parse_json_output(capsys)
    patch = payload["patches"][0]
    assert patch["compatibilityStatus"] == "sha_mismatch"
    assert "source identity differs" in patch["compatibilityMessage"]
    assert "linux/x86_64" in patch["compatibilityMessage"]
    assert "darwin/arm64" in patch["compatibilityMessage"]


def test_build_json_source_identity_failure_uses_specific_error_code(
    monkeypatch, tmp_path, capsys
):
    from harnessmonkey.reports_v2 import BuildReportV2

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_text("source")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "patch.json").write_text("{}")

    def fake_build(request):
        request.output_dir.mkdir(parents=True, exist_ok=True)
        return BuildReportV2(
            status="failed",
            automatedStatus="failed",
            sourceClaudePath=str(source),
            sourceVersion="2.1.199",
            sourceVersionOutput="2.1.199 (Claude Code)",
            failureReason=(
                "source_identity_mismatch:fable-fallback: current source is Claude 2.1.199; "
                "package targets Claude 2.1.198"
            ),
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
                "2.1.199",
                "--source-version-output",
                "2.1.199 (Claude Code)",
                "--json",
            ]
        )
        == 1
    )
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "source_identity_mismatch"
    assert "current source is Claude 2.1.199" in payload["error"]["message"]
    assert "package targets Claude 2.1.198" in payload["error"]["message"]


def test_build_json_invalid_v3_package_uses_machine_readable_error_code(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_text("source")
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
        == 1
    )

    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["buildReportStatus"] == "failed"
    assert payload["error"]["code"] == "package_manifest_invalid"


def test_default_source_discovery_uses_cached_install_source_when_path_is_managed_shim(
    monkeypatch, tmp_path
):
    from harnessmonkey.cli import _discover_source
    from harnessmonkey.install import install_shim_transaction

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    bin_dir = tmp_path / "bin"
    target = bin_dir / "claude"
    official = tmp_path / "versions" / "2.1.199"
    official.parent.mkdir(parents=True)
    official.write_bytes(b"official binary")
    official.chmod(0o755)
    bin_dir.mkdir()
    target.symlink_to(official)
    record = install_shim_transaction(target, tmp_path / "home" / ".harnessmonkey", dry_run=False)
    official.unlink()
    monkeypatch.setenv("PATH", str(bin_dir))

    discovered = _discover_source(None)

    raw = json.loads(record.read_text())
    assert discovered == Path(raw["previousSourceCachePath"])
    assert raw["sourcePath"].endswith("versions/2.1.199")


def test_status_ignores_stale_install_record(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    state = tmp_path / ".harnessmonkey"
    state.mkdir()
    (state / "install-record.json").write_text(
        json.dumps(
            {
                "owner": "HarnessMonkey managed shim",
                "targetPath": str(tmp_path / "missing-claude"),
                "installedShimSha256": "abc",
            }
        )
    )
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["shimInstalled"] is False
    assert payload["status"] == "not_installed"


def test_install_auth_failure_human_cli_uses_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "protected" / "claude"

    def fake_install(*args, **kwargs):
        from harnessmonkey.authorization import AuthorizationDenied

        raise AuthorizationDenied("denied", method="macos_gui")

    monkeypatch.setattr("harnessmonkey.cli.install_shim_transaction", fake_install)
    assert main(["install-shim", "--target", str(target)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "denied" in captured.err


def test_install_json_success_reports_authorization_metadata(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "protected" / "claude"

    monkeypatch.setattr("harnessmonkey.cli.target_needs_authorization", lambda path: True)
    monkeypatch.setattr(
        "harnessmonkey.cli.authorization_method_for_target", lambda path: "macos_gui"
    )

    def fake_install(target_path, state_dir, dry_run):
        return state_dir / "install-record.json"

    monkeypatch.setattr("harnessmonkey.cli.install_shim_transaction", fake_install)
    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["authorizationRequired"] is True
    assert payload["authorizationMethod"] == "macos_gui"
    assert payload["targetPath"] == str(target)


def test_protected_existing_target_install_json_refuses_without_safe_restore(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "protected" / "claude"
    target.parent.mkdir()
    target.write_text("official")
    monkeypatch.setattr("harnessmonkey.cli.target_needs_authorization", lambda path: True)
    monkeypatch.setattr(
        "harnessmonkey.cli.authorization_method_for_target", lambda path: "macos_gui"
    )
    monkeypatch.setattr(
        "harnessmonkey.install.authorization.target_needs_authorization", lambda path: True
    )

    assert main(["install-shim", "--target", str(target), "--json", "--dry-run"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "protected_restore_unavailable"
    assert payload["dryRun"] is True
    assert target.read_text() == "official"

    assert main(["install-shim", "--target", str(target), "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "protected_restore_unavailable"
    assert target.read_text() == "official"


def test_malformed_uninstall_record_json_returns_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    record = tmp_path / "bad-record.json"
    record.write_text("{bad json")
    assert main(["uninstall-shim", "--record", str(record), "--json"]) == 2
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_record"


def test_unreadable_uninstall_record_json_returns_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    record = tmp_path / "record-dir"
    record.mkdir()
    assert main(["uninstall-shim", "--record", str(record), "--json"]) == 2
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_record"
    assert str(record) in payload["error"]["message"]


def test_manager_cli_refuses_root_process(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("harnessmonkey.cli.os.geteuid", lambda: 0, raising=False)

    assert main(["status", "--json"]) == 1

    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "root_process_refused"


def test_manual_smoke_pending_json_summary_does_not_claim_activation(monkeypatch, tmp_path, capsys):
    from harnessmonkey.reports_v2 import BuildReportV2

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_text("source")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "patch.json").write_text("{}")

    def fake_build(request):
        request.output_dir.mkdir(parents=True, exist_ok=True)
        return BuildReportV2(
            status="manual_smoke_pending",
            automatedStatus="passed",
            sourceClaudePath=str(source),
            sourceVersion="fixture",
            sourceVersionOutput="fixture (Claude Code)",
            activationEligible=False,
            activationBlockers=["manual_smoke_pending"],
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
    payload = parse_json_output(capsys)
    assert payload["ok"] is True
    assert payload["summary"] == "Build requires manual smoke before activation"


def test_status_with_report_but_no_current_is_not_ok(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    report_dir = tmp_path / ".harnessmonkey" / "versions" / "fixture" / "patchsets" / "default"
    report_dir.mkdir(parents=True)
    (report_dir / "build-report.json").write_text(
        json.dumps({"schemaVersion": 2, "status": "verified", "enabledPatches": []})
    )
    config = tmp_path / ".harnessmonkey" / "config.json"
    config.write_text(
        json.dumps(
            {
                "activeProfile": "default",
                "profiles": {"default": {"prompt": None, "patches": [], "options": []}},
                "activePatchSet": str(report_dir),
            }
        )
    )
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["currentClaudePath"] is None
    assert payload["shimInstalled"] is False
    assert payload["status"] == "not_installed"


def test_status_ignores_install_record_target_directory(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target_dir = tmp_path / "target-dir"
    target_dir.mkdir()
    state = tmp_path / ".harnessmonkey"
    state.mkdir()
    (state / "install-record.json").write_text(
        json.dumps(
            {
                "owner": "HarnessMonkey managed shim",
                "targetPath": str(target_dir),
                "installedShimSha256": "abc",
            }
        )
    )
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["shimInstalled"] is False
    assert payload["status"] == "not_installed"


def test_verified_build_without_activation_does_not_claim_activation(monkeypatch, tmp_path, capsys):
    from harnessmonkey.reports_v2 import BuildReportV2

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_text("source")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "patch.json").write_text("{}")

    def fake_build(request):
        request.output_dir.mkdir(parents=True, exist_ok=True)
        return BuildReportV2(
            status="verified",
            automatedStatus="passed",
            sourceClaudePath=str(source),
            sourceVersion="fixture",
            sourceVersionOutput="fixture (Claude Code)",
            activationEligible=True,
            activationStatus="skipped",
        )

    monkeypatch.setattr("harnessmonkey.cli.build_patchset_v15", fake_build)
    assert main(
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
    ) == 0
    payload = parse_json_output(capsys)
    assert payload["summary"] == "Build verified; activation not performed"


def test_installed_shim_without_current_is_rebuild_required_not_ok(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".harnessmonkey" / "bin" / "claude"
    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    parse_json_output(capsys)

    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["shimInstalled"] is True
    assert payload["currentClaudePath"] is None
    assert payload["status"] == "rebuild_required"
    assert payload["rebuildRequired"] is True


def test_status_with_installed_shim_and_missing_active_report_is_rebuild_required(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path))
    state = tmp_path / ".harnessmonkey"
    patchset = state / "versions" / "fixture" / "patchsets" / "default"
    patchset.mkdir(parents=True)
    executable = tmp_path / "current-claude"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    (state / "current").symlink_to(executable)
    config = state / "config.json"
    config.write_text(
        json.dumps(
            {
                "activeProfile": "default",
                "profiles": {"default": {"prompt": None, "patches": [], "options": []}},
                "activePatchSet": str(patchset),
            }
        )
    )
    target = state / "bin" / "claude"
    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    parse_json_output(capsys)

    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["shimInstalled"] is True
    assert payload["currentClaudePath"] == str(executable)
    assert payload["latestBuildReportPath"] is None
    assert payload["activePatchSet"] == str(patchset)
    assert payload["activePatchIds"] == []
    assert payload["status"] == "rebuild_required"
    assert payload["rebuildRequired"] is True


def test_status_requires_current_to_resolve_to_executable(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    state = tmp_path / ".harnessmonkey"
    state.mkdir()
    (state / "current").symlink_to(tmp_path / "missing")
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["currentClaudePath"] is None
    assert payload["status"] == "not_installed"

    (state / "current").unlink()
    non_executable = tmp_path / "claude"
    non_executable.write_text("not executable")
    (state / "current").symlink_to(non_executable)
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["currentClaudePath"] is None
    assert payload["status"] == "not_installed"


def test_verified_build_without_activation_does_not_persist_active_patchset(
    monkeypatch, tmp_path, capsys
):
    from harnessmonkey.reports_v2 import BuildReportV2

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source = tmp_path / "claude"
    source.write_text("source")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "patch.json").write_text("{}")

    def fake_build(request):
        request.output_dir.mkdir(parents=True, exist_ok=True)
        return BuildReportV2(
            status="verified",
            automatedStatus="passed",
            sourceClaudePath=str(source),
            sourceVersion="fixture",
            sourceVersionOutput="fixture (Claude Code)",
            activationEligible=True,
            activationStatus="skipped",
            enabledPatches=[],
        )

    monkeypatch.setattr("harnessmonkey.cli.build_patchset_v15", fake_build)
    assert main(
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
    ) == 0
    parse_json_output(capsys)
    config_path = tmp_path / "home" / ".harnessmonkey" / "config.json"
    if config_path.exists():
        assert json.loads(config_path.read_text()).get("activePatchSet") is None


def test_status_does_not_trust_forged_install_record_digest(monkeypatch, tmp_path, capsys):
    import hashlib

    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "claude"
    target.write_text("not a harness monkey shim")
    state = tmp_path / ".harnessmonkey"
    state.mkdir()
    (state / "install-record.json").write_text(
        json.dumps(
            {
                "owner": "HarnessMonkey managed shim",
                "targetPath": str(target),
                "stateDir": str(state),
                "installedShimSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    )
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["shimInstalled"] is False
    assert payload["status"] == "not_installed"


def test_status_in_shim_mode_requires_installed_shim(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    current_target = tmp_path / "claude"
    current_target.write_text("#!/bin/sh\nexit 0\n")
    current_target.chmod(0o755)
    state = tmp_path / ".harnessmonkey"
    state.mkdir()
    (state / "current").symlink_to(current_target)
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["currentClaudePath"] == str(current_target)
    assert payload["shimInstalled"] is False
    assert payload["status"] == "not_installed"


def test_set_prompt_missing_file_json_returns_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    missing = tmp_path / "missing.md"
    assert main(["set-prompt", str(missing), "--from-file", "--json"]) == 2
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_prompt_file"


def test_stale_install_record_does_not_expose_shim_target(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    state = tmp_path / ".harnessmonkey"
    state.mkdir()
    (state / "install-record.json").write_text(
        json.dumps(
            {
                "owner": "HarnessMonkey managed shim",
                "targetPath": str(tmp_path / "missing-claude"),
                "stateDir": str(state),
                "installedShimSha256": "abc",
            }
        )
    )
    assert main(["status", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["shimInstalled"] is False
    assert payload["shimTargetPath"] is None


def test_use_official_json_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    official = tmp_path / "official"
    official.write_text("#!/bin/sh\nexit 0\n")
    official.chmod(0o755)
    assert main(["use-official", "--official", str(official), "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["ok"] is True
    assert payload["summary"] == "using official Claude binary"
    config = json.loads((tmp_path / ".harnessmonkey" / "config.json").read_text())
    assert config["officialClaudePath"] == str(official.resolve())

    assert main(["status", "--json"]) == 0
    status = parse_json_output(capsys)
    assert status["officialClaudePath"] == str(official.resolve())
    assert status["discoveredOfficialClaudePath"] == str(official.resolve())
    assert status["sourceClaudePath"] == str(official.resolve())


def test_add_patch_json_contract_installs_package(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "demo-patch"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "patch",
                "id": "demo-patch",
                "label": "Demo",
                "description": "d",
                "patch": {"engine": "bun_graph_repack", "targets": []},
            }
        )
    )

    assert main(["add-patch", str(source), "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["schemaVersion"] == 1
    assert payload["ok"] is True
    assert isinstance(payload["status"], str)
    assert isinstance(payload["summary"], str)
    assert payload["error"] is None
    assert isinstance(payload["warnings"], list)
    installed = tmp_path / ".harnessmonkey" / "patches" / "demo-patch" / "manifest.json"
    assert installed.exists()


def test_add_patch_json_contract_invalid_package(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "bad-patch"
    source.mkdir()
    (source / "manifest.json").write_text("{not json")

    assert main(["add-patch", str(source), "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_package"


def test_add_prompt_json_contract_installs_and_is_not_active(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "bare-prompt.md"
    source.write_text("be helpful and concise")

    assert main(["add-prompt", str(source), "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["ok"] is True

    prompt_path = tmp_path / ".harnessmonkey" / "prompts" / "bare-prompt" / "prompt.md"
    assert prompt_path.exists()
    assert prompt_path.read_text() == "be helpful and concise"

    assert main(["list-prompts", "--json"]) == 0
    list_payload = parse_json_output(capsys)
    records = [record for record in list_payload["prompts"] if record["id"] == "bare-prompt"]
    assert len(records) == 1
    assert records[0]["enabled"] is False


def test_add_prompt_json_contract_empty_slug_stem_returns_invalid_package(
    monkeypatch, tmp_path, capsys
):
    """Regression for Critical-2: a stem that slugifies to '' (e.g. '###.md') must
    not crash with a raw FileExistsError traceback — it must return the standard
    6-key invalid_package envelope."""
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "###.md"
    source.write_text("be helpful")

    assert main(["add-prompt", str(source), "--json"]) == 1
    payload = parse_json_output(capsys)
    assert set(payload.keys()) == {"schemaVersion", "ok", "status", "summary", "error", "warnings"}
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_package"
    assert not (tmp_path / ".harnessmonkey" / "prompts").exists()


def test_add_prompt_json_contract_traversal_id_returns_invalid_package(
    monkeypatch, tmp_path, capsys
):
    """Regression for Critical-1 (add-prompt instance): an explicit --id containing
    '..' must be rejected before any path construction, with no stray writes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Pin the staging tempdir under tmp_path so a traversal leak (one directory
    # above the tempdir) lands at a precise, assertable location.
    staging_root = tmp_path / "staging-root"
    staging_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(staging_root))
    source = tmp_path / "notes.md"
    source.write_text("be helpful")

    assert main(["add-prompt", str(source), "--id", "../evil-y", "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_package"
    assert not (tmp_path / ".harnessmonkey" / "prompts").exists()
    assert not (staging_root / "evil-y").exists()


def test_add_prompt_json_contract_missing_source_file_envelope(monkeypatch, tmp_path, capsys):
    """Regression for Important-3: missing source file must use the 6-key
    packages_admin envelope with code invalid_package and exit 1, not the 14-key
    CommandEnvelope with code missing_source_file and exit 2."""
    monkeypatch.setenv("HOME", str(tmp_path))
    missing = tmp_path / "does-not-exist.md"

    assert main(["add-prompt", str(missing), "--json"]) == 1
    payload = parse_json_output(capsys)
    assert set(payload.keys()) == {"schemaVersion", "ok", "status", "summary", "error", "warnings"}
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_package"


def test_remove_patch_json_contract_removes_uninstalled_package(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    installed = tmp_path / ".harnessmonkey" / "patches" / "demo-patch"
    installed.mkdir(parents=True)

    assert main(["remove-patch", "demo-patch", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["schemaVersion"] == 1
    assert payload["ok"] is True
    assert payload["error"] is None
    assert not installed.exists()


def test_remove_patch_json_contract_refuses_profile_referenced_package(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "demo-patch"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "patch",
                "id": "demo-patch",
                "label": "Demo",
                "description": "d",
                "patch": {"engine": "bun_graph_repack", "targets": []},
            }
        )
    )
    assert main(["add-patch", str(source), "--json"]) == 0
    assert main(["enable-patch", "demo-patch", "--json"]) == 0
    capsys.readouterr()  # drain add-patch/enable-patch output before the assertion below

    assert main(["remove-patch", "demo-patch", "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "package_in_use"
    installed = tmp_path / ".harnessmonkey" / "patches" / "demo-patch"
    assert installed.exists()


def test_remove_patch_json_contract_missing_package(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["remove-patch", "nope", "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "package_missing"


def test_remove_option_json_contract_refuses_enabled_option(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    installed = tmp_path / ".harnessmonkey" / "options" / "op1"
    installed.mkdir(parents=True)
    (installed / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "option",
                "id": "op1",
                "label": "Op1",
                "description": "d",
                "option": {},
            }
        )
    )
    assert main(["enable-option", "op1", "--json"]) == 0
    capsys.readouterr()  # drain enable-option output before the assertion below

    assert main(["remove-option", "op1", "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "package_in_use"
    assert installed.exists()


def test_remove_prompt_json_contract_refuses_active_prompt(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    installed = tmp_path / ".harnessmonkey" / "prompts" / "pr1"
    installed.mkdir(parents=True)
    (installed / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "prompt",
                "id": "pr1",
                "label": "Pr1",
                "description": "d",
                "prompt": {"mode": "append", "source": {"path": "prompt.md"}},
            }
        )
    )
    (installed / "prompt.md").write_text("be helpful")
    assert main(["set-prompt", "pr1", "--json"]) == 0
    capsys.readouterr()  # drain set-prompt output before the assertion below

    assert main(["remove-prompt", "pr1", "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "package_in_use"
    assert installed.exists()


def test_remove_patch_json_contract_traversal_id_returns_invalid_package(
    monkeypatch, tmp_path, capsys
):
    """Regression: an unvalidated traversal id must never reach `shutil.rmtree`."""
    monkeypatch.setenv("HOME", str(tmp_path))
    outside_target = tmp_path / "evil-target"
    outside_target.mkdir()
    (outside_target / "keepme.txt").write_text("do not delete")

    assert main(["remove-patch", "../evil-target", "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_package"
    assert outside_target.exists()
    assert (outside_target / "keepme.txt").exists()


def test_use_official_json_missing_inputs_return_envelopes(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["use-official", "--json"]) == 2
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_official"

    missing = tmp_path / "missing-official"
    assert main(["use-official", "--official", str(missing), "--json"]) == 2
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_official"


# -- shim-update-resilience stage 2: cache-source + repair-shim -------------
#
# docs/superpowers/specs/2026-07-04-harnessmonkey-shim-update-resilience.md
# Sec2/Sec3 + Refinements R1-R4, R6, R8, R9.


def _replace_with_official(target, tmp_path, version="2.1.201"):
    # `versions/<version>` mirrors the real official installer's own
    # versioned-directory layout -- repair.py's `_version_from_path` (C1)
    # parses this segment instead of executing the binary for `--version`.
    official = tmp_path / "official-source" / "versions" / version / "claude"
    official.parent.mkdir(parents=True)
    official.write_text(f"#!/bin/sh\necho '{version} (Claude Code)'\n")
    official.chmod(official.stat().st_mode | 0o111)
    # Shim lock feature: a real locked shim can't be clobbered by an
    # external actor at all (see tests/test_shim_lock.py), so lift the flag
    # first to keep simulating "already replaced" directly here.
    _unlock_target(target)
    target.unlink()
    target.symlink_to(official)
    return official


def test_cache_source_json_contract_via_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "local-bin" / "claude"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    parse_json_output(capsys)

    official = _replace_with_official(target, tmp_path)
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()

    assert main(["cache-source", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["ok"] is True
    assert payload["sha256"] == official_sha
    assert Path(payload["cachedSourcePath"]).read_bytes() == official.read_bytes()
    assert payload["version"] == "2.1.201"
    assert isinstance(payload["gcRemovedDigests"], list)
    # Never touches the target.
    assert target.is_symlink()


def test_cache_source_json_missing_target_returns_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["cache-source", "--json"]) == 2
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_target"


def test_repair_shim_json_contract_via_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Fix 1's post-swap revert re-check sleeps for real by default; keep this
    # contract test fast by collapsing that bounded delay to 0.
    monkeypatch.setattr(repair_module, "REPAIR_REVERT_RECHECK_DELAY_SECONDS", 0)
    target = tmp_path / "local-bin" / "claude"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    parse_json_output(capsys)

    official = _replace_with_official(target, tmp_path)
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()

    assert main(["status", "--json"]) == 0
    before = parse_json_output(capsys)
    assert before["shimInstalled"] is False
    assert before["targetReplacedByOfficial"] is True

    assert main(["repair-shim", "--json"]) == 0
    payload = parse_json_output(capsys)
    assert payload["ok"] is True
    assert payload["repaired"] is True
    assert payload["newOfficialSha256"] == official_sha
    assert payload["newOfficialVersion"] == "2.1.201"
    assert Path(payload["cachedSourcePath"]).read_bytes() == official.read_bytes()
    # Fix 1: additive field -- honest about whether an external actor (the
    # field-observed official-updater self-heal) already clobbered the
    # target again within seconds of this successful swap. Nothing touches
    # the target between the CLI's swap and this assertion, so it's False.
    assert payload["revertedImmediately"] is False

    assert main(["status", "--json"]) == 0
    after = parse_json_output(capsys)
    assert after["shimInstalled"] is True
    assert after["targetReplacedByOfficial"] is False


# -- shim lock: additive `targetLocked`/`shimLocked` fields ------------------
#
# Evidence (controlled experiment on a real machine, 2026-07-03/04): with
# `chflags uchg` set on the shim, the official installer's own self-heal
# leaves it untouched across fresh sessions (its own code swallows the
# resulting EPERM silently); without it, the shim is clobbered within ~15s.


def test_install_shim_json_contract_target_locked_is_additive(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "local-bin" / "claude"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    payload = parse_json_output(capsys)

    assert payload["ok"] is True
    assert isinstance(payload["targetLocked"], bool)
    if sys.platform == "darwin" and hasattr(os, "chflags"):
        assert payload["targetLocked"] is True


def test_repair_shim_json_contract_target_locked_is_additive(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(repair_module, "REPAIR_REVERT_RECHECK_DELAY_SECONDS", 0)
    target = tmp_path / "local-bin" / "claude"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    parse_json_output(capsys)

    _replace_with_official(target, tmp_path)

    assert main(["repair-shim", "--json"]) == 0
    payload = parse_json_output(capsys)

    assert payload["ok"] is True
    assert isinstance(payload["targetLocked"], bool)
    if sys.platform == "darwin" and hasattr(os, "chflags"):
        assert payload["targetLocked"] is True


def test_status_json_contract_shim_locked_is_additive(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "local-bin" / "claude"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["install-shim", "--target", str(target), "--json"]) == 0
    parse_json_output(capsys)

    assert main(["status", "--json"]) == 0
    payload_before = parse_json_output(capsys)
    existing_keys = set(payload_before)
    assert "shimLocked" in existing_keys
    assert isinstance(payload_before["shimLocked"], bool)
    if sys.platform == "darwin" and hasattr(os, "chflags"):
        assert payload_before["shimLocked"] is True

    _replace_with_official(target, tmp_path)

    assert main(["status", "--json"]) == 0
    payload_after = parse_json_output(capsys)
    assert set(payload_after) == existing_keys
    assert payload_after["shimLocked"] is False


def test_repair_shim_json_never_managed_target_returns_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "local-bin" / "claude"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    target.chmod(target.stat().st_mode | 0o111)

    assert main(["repair-shim", "--target", str(target), "--json"]) == 1
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "no_install_record"
    # No write attempted: target is exactly the fake binary, untouched.
    assert "HarnessMonkey" not in target.read_text()


def test_repair_shim_json_missing_target_returns_envelope(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["repair-shim", "--json"]) == 2
    payload = parse_json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_target"
