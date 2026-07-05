from __future__ import annotations

import pytest

from harnessmonkey.manifest_v2 import ManifestV2Error, load_manifest_v2_dict


def valid_v2_manifest() -> dict:
    return {
        "schemaVersion": 2,
        "id": "example-v15",
        "name": "Example V1.5 patch",
        "description": "Module-coordinate example",
        "packageVersion": "0.1.0",
        "targets": [
            {
                "sourceIdentity": {
                    "claudeVersion": "2.1.198",
                    "versionOutput": "2.1.198 (Claude Code)",
                    "sha256": "a" * 64,
                    "sizeBytes": 229328464,
                    "platform": "darwin",
                    "arch": "arm64",
                },
                "requiredEngine": "bun_graph_repack",
                "requiredBinaryFormat": "bun_standalone_macho64",
                "modules": [
                    {
                        "path": "/$bunfs/root/src/entrypoints/cli.js",
                        "contentSha256": "b" * 64,
                        "contentLength": 64,
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
                                "oldRangeSha256": "c" * 64,
                                "oldRangeLength": 28,
                                "replacement": {"inline": "function render(){NEW_RENDER}\n"},
                                "knownBehaviorChange": "Changes renderer output",
                            }
                        ],
                    }
                ],
                "preconditions": [],
                "postconditions": [
                    {
                        "type": "module_must_contain",
                        "modulePath": "/$bunfs/root/src/entrypoints/cli.js",
                        "value": "NEW_RENDER",
                    }
                ],
                "manualSmoke": {"required": True, "reason": "UI renderer changed"},
            }
        ],
    }


def test_load_manifest_v2_accepts_valid_shape():
    manifest = load_manifest_v2_dict(valid_v2_manifest())
    assert manifest.schema_version == 2
    assert manifest.id == "example-v15"
    target = manifest.targets[0]
    assert target.required_engine == "bun_graph_repack"
    assert target.required_binary_format == "bun_standalone_macho64"
    assert target.modules[0].path == "/$bunfs/root/src/entrypoints/cli.js"
    assert target.modules[0].operations[0].op_id == "replace-renderer"


def test_schema_v1_is_rejected_with_migration_required():
    data = valid_v2_manifest()
    data["schemaVersion"] = 1
    with pytest.raises(ManifestV2Error, match="schema_v1_migration_required"):
        load_manifest_v2_dict(data)


@pytest.mark.parametrize("field", ["requiredEngine", "requiredBinaryFormat", "modules"])
def test_target_requires_engine_and_modules(field):
    data = valid_v2_manifest()
    del data["targets"][0][field]
    with pytest.raises(ManifestV2Error, match=field):
        load_manifest_v2_dict(data)


def test_manifest_v2_rejects_binary_shape_leak():
    data = valid_v2_manifest()
    data["targets"][0]["binaryShape"] = {"moduleRecordSize": 52}
    with pytest.raises(ManifestV2Error, match="binaryShape"):
        load_manifest_v2_dict(data)


def test_manifest_v2_rejects_padding_and_growth_flags():
    data = valid_v2_manifest()
    op = data["targets"][0]["modules"][0]["operations"][0]
    op["padding"] = "spaces"
    with pytest.raises(ManifestV2Error, match="padding"):
        load_manifest_v2_dict(data)
    del op["padding"]
    op["allowGrowth"] = True
    with pytest.raises(ManifestV2Error, match="allowGrowth"):
        load_manifest_v2_dict(data)


def test_manifest_v2_rejects_duplicate_op_ids_across_modules():
    data = valid_v2_manifest()
    module = dict(data["targets"][0]["modules"][0])
    module["path"] = "/$bunfs/root/src/other.js"
    module["operations"] = [dict(module["operations"][0])]
    data["targets"][0]["modules"].append(module)
    with pytest.raises(ManifestV2Error, match="duplicate opId"):
        load_manifest_v2_dict(data)


@pytest.mark.parametrize("bad", ["run_shell", "module_must_contain"])
def test_manifest_v2_rejects_non_mutating_operation_types(bad):
    data = valid_v2_manifest()
    data["targets"][0]["modules"][0]["operations"][0]["type"] = bad
    with pytest.raises(ManifestV2Error, match="unsupported operation type"):
        load_manifest_v2_dict(data)



def _insert_op(**overrides):
    op = {
        "opId": "append-entry",
        "label": "Append entry",
        "type": "insert_after",
        "anchor": 'Oe&&"frame"',
        "insertOrder": 200,
        "replacement": {"inline": ',"reminders"'},
    }
    op.update(overrides)
    return op


def _manifest_with_op(op):
    return {
        "schemaVersion": 2,
        "id": "fixture",
        "name": "Fixture",
        "description": "Fixture",
        "packageVersion": "0.1.0",
        "targets": [
            {
                "sourceIdentity": {
                    "claudeVersion": "fixture",
                    "versionOutput": "fixture (Claude Code)",
                    "sha256": "0" * 64,
                    "sizeBytes": 1,
                    "platform": "darwin",
                    "arch": "arm64",
                },
                "requiredEngine": "bun_graph_repack",
                "requiredBinaryFormat": "bun_standalone_macho64",
                "modules": [
                    {
                        "path": "/$bunfs/root/src/entrypoints/cli.js",
                        "contentSha256": "0" * 64,
                        "contentLength": 1,
                        "operations": [op],
                    }
                ],
            }
        ],
    }


def test_insert_after_parses_with_anchor_and_order():
    manifest = load_manifest_v2_dict(_manifest_with_op(_insert_op()))
    operation = manifest.targets[0].modules[0].operations[0]
    assert operation.type == "insert_after"
    assert operation.anchor == 'Oe&&"frame"'
    assert operation.insert_order == 200
    assert operation.expected_anchor_count == 1


def test_insert_before_parses_without_order():
    op = _insert_op(type="insert_before")
    del op["insertOrder"]
    operation = load_manifest_v2_dict(_manifest_with_op(op)).targets[0].modules[0].operations[0]
    assert operation.type == "insert_before"
    assert operation.insert_order is None


def test_insertion_requires_anchor():
    op = _insert_op()
    del op["anchor"]
    with pytest.raises(ManifestV2Error, match="requires anchor"):
        load_manifest_v2_dict(_manifest_with_op(op))


def test_insertion_rejects_old_range_evidence():
    with pytest.raises(ManifestV2Error, match="old-range evidence"):
        load_manifest_v2_dict(_manifest_with_op(_insert_op(oldRangeLength=0)))


def test_insertion_rejects_expected_anchor_count_other_than_one():
    with pytest.raises(ManifestV2Error, match="expectedAnchorCount"):
        load_manifest_v2_dict(_manifest_with_op(_insert_op(expectedAnchorCount=2)))


def test_insertion_context_markers_must_pair():
    with pytest.raises(ManifestV2Error, match="context markers"):
        load_manifest_v2_dict(_manifest_with_op(_insert_op(startMarker="ji=")))


def test_insertion_context_sha_requires_context_markers():
    with pytest.raises(ManifestV2Error, match="contextSha256 requires context markers"):
        load_manifest_v2_dict(_manifest_with_op(_insert_op(contextSha256="0" * 64)))


def test_replace_exact_rejects_structured_splice_fields():
    op = {
        "opId": "legacy",
        "label": "Legacy",
        "type": "replace_exact",
        "exact": "OLD",
        "anchor": "OLD",
        "replacement": {"inline": "NEW"},
    }
    with pytest.raises(ManifestV2Error, match="not allowed on replace_exact"):
        load_manifest_v2_dict(_manifest_with_op(op))


def test_replace_exact_rejects_seam_hint():
    op = {
        "opId": "legacy-hint",
        "label": "Legacy",
        "type": "replace_exact",
        "exact": "OLD",
        "seamHint": "some.seam",
        "replacement": {"inline": "NEW"},
    }
    with pytest.raises(ManifestV2Error, match="not allowed on replace_exact"):
        load_manifest_v2_dict(_manifest_with_op(op))



def _subspan_op(**overrides):
    op = {
        "opId": "add-flag",
        "label": "Add selection flag",
        "type": "replace_substring_within",
        "startMarker": 'let qb=Du==="tasks"',
        "endMarker": ";function Sf",
        "subExact": 'Ap=Du==="frame"',
        "oldRangeLength": 15,
        "replacement": {"inline": 'Ap=Du==="frame",hC=Du==="hiddenContext"'},
        "seamHint": "footer.selection.afterFrame",
    }
    op.update(overrides)
    return op


def test_replace_substring_within_parses():
    operation = (
        load_manifest_v2_dict(_manifest_with_op(_subspan_op()))
        .targets[0].modules[0].operations[0]
    )
    assert operation.type == "replace_substring_within"
    assert operation.sub_exact == 'Ap=Du==="frame"'
    assert operation.old_range_length == 15
    assert operation.seam_hint == "footer.selection.afterFrame"


def test_replace_substring_within_requires_sub_exact():
    op = _subspan_op()
    del op["subExact"]
    with pytest.raises(ManifestV2Error, match="requires subExact"):
        load_manifest_v2_dict(_manifest_with_op(op))


def test_replace_substring_within_requires_markers():
    op = _subspan_op()
    del op["endMarker"]
    with pytest.raises(ManifestV2Error, match="requires startMarker and endMarker"):
        load_manifest_v2_dict(_manifest_with_op(op))


def test_replace_substring_within_rejects_insert_order():
    with pytest.raises(ManifestV2Error, match="not allowed on replace_substring_within"):
        load_manifest_v2_dict(_manifest_with_op(_subspan_op(insertOrder=5)))



def test_relationship_metadata_parses():
    data = _manifest_with_op(_insert_op())
    data["requiresPackages"] = ["drawer-dock"]
    data["conflictsWithPackages"] = ["mute-reminders"]
    manifest = load_manifest_v2_dict(data)
    assert manifest.requires_packages == ("drawer-dock",)
    assert manifest.conflicts_with_packages == ("mute-reminders",)


def test_relationship_metadata_defaults_empty():
    manifest = load_manifest_v2_dict(_manifest_with_op(_insert_op()))
    assert manifest.requires_packages == ()
    assert manifest.conflicts_with_packages == ()


def test_relationship_metadata_rejects_non_string_list():
    data = _manifest_with_op(_insert_op())
    data["requiresPackages"] = "drawer-dock"
    with pytest.raises(ManifestV2Error, match="requiresPackages"):
        load_manifest_v2_dict(data)



def test_insertion_context_marker_counts_must_be_one():
    with pytest.raises(ManifestV2Error, match="expectedStartMarkerCount"):
        load_manifest_v2_dict(
            _manifest_with_op(
                _insert_op(
                    startMarker="function one(){",
                    endMarker="}",
                    expectedStartMarkerCount=2,
                )
            )
        )


def test_replace_substring_within_marker_counts_must_be_one():
    with pytest.raises(ManifestV2Error, match="expectedEndMarkerCount"):
        load_manifest_v2_dict(_manifest_with_op(_subspan_op(expectedEndMarkerCount=2)))


@pytest.mark.parametrize("field", ["expectedAnchorCount", "expectedSubExactCount"])
def test_legacy_operations_reject_ignored_structured_count_fields(field):
    op = {
        "opId": "legacy-count",
        "label": "Legacy count",
        "type": "replace_exact",
        "exact": "OLD",
        field: 2,
        "replacement": {"inline": "NEW"},
    }
    with pytest.raises(ManifestV2Error, match=field):
        load_manifest_v2_dict(_manifest_with_op(op))
