from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harnessmonkey.package_model import (
    PackageKind,
    PackageValidationError,
    discover_packages,
    load_package_manifest,
    manifest_digest,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def option_manifest(package_id: str, **overrides):
    payload = {
        "schemaVersion": 1,
        "kind": "option",
        "id": package_id,
        "label": package_id.replace("-", " ").title(),
        "description": "Option package",
        "option": {
            "argv": [],
            "env": {},
            "conflictsWithArgv": [],
            "conflictsWithOptions": [],
            "conflictsWithEnv": [],
        },
    }
    payload.update(overrides)
    return payload


def prompt_manifest(package_id: str, source_path: str = "prompt.md", sha256: str | None = None):
    source = {"path": source_path}
    if sha256 is not None:
        source["sha256"] = sha256
    return {
        "schemaVersion": 1,
        "kind": "prompt",
        "id": package_id,
        "label": package_id.title(),
        "description": "Prompt package",
        "prompt": {"mode": "append", "source": source},
    }


def patch_manifest(package_id: str):
    return {
        "schemaVersion": 1,
        "kind": "patch",
        "id": package_id,
        "label": package_id.title(),
        "description": "Patch package",
        "patch": {"engine": "bun_graph_repack", "targets": []},
    }


def test_discovers_valid_and_invalid_packages(tmp_path):
    root = tmp_path / ".harnessmonkey"
    write_json(root / "options" / "good-option" / "good.json", option_manifest("good-option"))
    write_json(
        root / "options" / "bad-option" / "bad.json",
        {"schemaVersion": 1, "kind": "option", "id": "wrong"},
    )

    result = discover_packages(root / "options", PackageKind.OPTION)

    assert [item.id for item in result.valid] == ["good-option"]
    assert len(result.invalid) == 1
    assert result.invalid[0].package_dir.name == "bad-option"
    assert result.invalid[0].errors


def test_id_must_match_folder_slug(tmp_path):
    package_dir = tmp_path / "options" / "actual"
    write_json(package_dir / "manifest.json", option_manifest("different"))
    with pytest.raises(PackageValidationError, match="id_must_match_folder"):
        load_package_manifest(package_dir, PackageKind.OPTION)


def test_kind_must_match_bucket(tmp_path):
    package_dir = tmp_path / "options" / "research"
    (package_dir / "prompt.md").parent.mkdir(parents=True)
    (package_dir / "prompt.md").write_text("prompt")
    write_json(package_dir / "research.json", prompt_manifest("research"))
    with pytest.raises(PackageValidationError, match="kind_must_match_bucket"):
        load_package_manifest(package_dir, PackageKind.OPTION)


def test_option_rejects_prompt_channel_flags(tmp_path):
    package_dir = tmp_path / "options" / "bad-option"
    payload = option_manifest("bad-option")
    payload["option"]["argv"] = ["--append-system-prompt-file", "prompt.md"]
    write_json(package_dir / "bad-option.json", payload)
    with pytest.raises(PackageValidationError, match="forbidden_prompt_flag"):
        load_package_manifest(package_dir, PackageKind.OPTION)


def test_prompt_sha_and_package_local_path_are_verified(tmp_path):
    package_dir = tmp_path / "prompts" / "research"
    prompt = package_dir / "prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("extra prompt")
    digest = hashlib.sha256(prompt.read_bytes()).hexdigest()
    write_json(package_dir / "research.json", prompt_manifest("research", sha256=digest))
    loaded = load_package_manifest(package_dir, PackageKind.PROMPT)
    assert loaded.prompt is not None
    assert loaded.prompt.source.path == prompt


def test_prompt_path_cannot_escape_package(tmp_path):
    package_dir = tmp_path / "prompts" / "research"
    write_json(
        package_dir / "research.json", prompt_manifest("research", source_path="../escape.md")
    )
    with pytest.raises(PackageValidationError, match="package_path_escape"):
        load_package_manifest(package_dir, PackageKind.PROMPT)


def test_multiple_valid_json_manifests_are_invalid(tmp_path):
    package_dir = tmp_path / "options" / "dupe"
    write_json(package_dir / "one.json", option_manifest("dupe"))
    write_json(package_dir / "two.json", option_manifest("dupe"))
    with pytest.raises(PackageValidationError, match="multiple_valid_manifests"):
        load_package_manifest(package_dir, PackageKind.OPTION)


def test_manifest_digest_is_stable(tmp_path):
    package_dir = tmp_path / "patches" / "demo-patch"
    write_json(package_dir / "demo.json", patch_manifest("demo-patch"))
    loaded = load_package_manifest(package_dir, PackageKind.PATCH)
    assert manifest_digest(loaded) == manifest_digest(loaded)


def test_option_env_literal_and_value_from_env_entries_parse(tmp_path):
    package_dir = tmp_path / "options" / "env-option"
    payload = option_manifest("env-option")
    payload["option"]["env"] = {
        "STATIC_VALUE": "literal",
        "FROM_PROCESS": {
            "valueFromEnv": "ANTHROPIC_API_KEY",
            "secret": True,
            "allowOverrideProcessEnv": True,
        },
    }
    write_json(package_dir / "env-option.json", payload)

    loaded = load_package_manifest(package_dir, PackageKind.OPTION)

    assert loaded.option is not None
    literal = loaded.option.env["STATIC_VALUE"]
    assert literal.value == "literal"
    assert literal.value_from_env is None
    assert literal.secret is False
    assert literal.allow_override_process_env is False
    forwarded = loaded.option.env["FROM_PROCESS"]
    assert forwarded.value is None
    assert forwarded.value_from_env == "ANTHROPIC_API_KEY"
    assert forwarded.secret is True
    assert forwarded.allow_override_process_env is True


def test_option_env_value_and_value_from_env_are_mutually_exclusive(tmp_path):
    package_dir = tmp_path / "options" / "bad-env"
    payload = option_manifest("bad-env")
    payload["option"]["env"] = {"BAD_ENV": {"value": "literal", "valueFromEnv": "SOURCE"}}
    write_json(package_dir / "bad-env.json", payload)

    with pytest.raises(PackageValidationError, match="env_value_source_exclusive"):
        load_package_manifest(package_dir, PackageKind.OPTION)


def test_option_env_value_from_env_must_be_env_name(tmp_path):
    package_dir = tmp_path / "options" / "bad-env"
    payload = option_manifest("bad-env")
    payload["option"]["env"] = {"BAD_ENV": {"valueFromEnv": "not-valid-env-name"}}
    write_json(package_dir / "bad-env.json", payload)

    with pytest.raises(PackageValidationError, match="env.valueFromEnv_invalid_env_name"):
        load_package_manifest(package_dir, PackageKind.OPTION)


def test_patch_rejects_unsupported_engine(tmp_path):
    package_dir = tmp_path / "patches" / "demo-patch"
    payload = patch_manifest("demo-patch")
    payload["patch"]["engine"] = "shell_script"
    write_json(package_dir / "demo.json", payload)

    with pytest.raises(PackageValidationError, match="patch_engine_unsupported"):
        load_package_manifest(package_dir, PackageKind.PATCH)


def test_compatibility_arches_and_risk_confirmation_warning_are_preserved(tmp_path):
    package_dir = tmp_path / "options" / "guarded-option"
    payload = option_manifest(
        "guarded-option",
        compatibility={"claudeVersions": ["2.1.199"], "platforms": ["darwin"], "arches": ["arm64"]},
        risk={
            "level": "high",
            "requiresConfirmation": True,
            "statusWarning": "Requires copied-binary patching.",
        },
    )
    write_json(package_dir / "guarded-option.json", payload)

    loaded = load_package_manifest(package_dir, PackageKind.OPTION)

    assert loaded.compatibility is not None
    assert loaded.compatibility.arches == ("arm64",)
    assert loaded.risk is not None
    assert loaded.risk.requires_confirmation is True
    assert loaded.risk.status_warning == "Requires copied-binary patching."


def test_option_rejects_prompt_channel_flags_equals_form(tmp_path):
    package_dir = tmp_path / "options" / "bad-option"
    payload = option_manifest("bad-option")
    payload["option"]["argv"] = ["--system-prompt-file=prompt.md"]
    write_json(package_dir / "bad-option-equals.json", payload)

    with pytest.raises(PackageValidationError, match="forbidden_prompt_flag"):
        load_package_manifest(package_dir, PackageKind.OPTION)


def test_patch_replacement_path_cannot_escape_package(tmp_path):
    package_dir = tmp_path / "patches" / "payload-escape"
    payload = patch_manifest("payload-escape")
    payload["patch"]["targets"] = [
        {
            "modules": [
                {
                    "path": "/$bunfs/root.js",
                    "operations": [
                        {
                            "replacement": {
                                "path": "../escape.js",
                                "sha256": "0" * 64,
                            }
                        }
                    ],
                }
            ]
        }
    ]
    write_json(package_dir / "payload-escape.json", payload)

    with pytest.raises(PackageValidationError, match="package_path_escape"):
        load_package_manifest(package_dir, PackageKind.PATCH)


def test_patch_inline_replacement_and_module_path_remain_valid(tmp_path):
    package_dir = tmp_path / "patches" / "inline-patch"
    payload = patch_manifest("inline-patch")
    payload["patch"]["targets"] = [
        {
            "modules": [
                {
                    "path": "/$bunfs/root.js",
                    "operations": [{"replacement": {"inline": "patched"}}],
                }
            ]
        }
    ]
    write_json(package_dir / "inline-patch.json", payload)

    loaded = load_package_manifest(package_dir, PackageKind.PATCH)

    assert loaded.patch is not None


def test_patch_replacement_path_requires_sha256(tmp_path):
    package_dir = tmp_path / "patches" / "missing-sha"
    payload = patch_manifest("missing-sha")
    payload["patch"]["targets"] = [
        {
            "modules": [
                {
                    "operations": [
                        {"replacement": {"path": "payloads/foo.js"}}
                    ]
                }
            ]
        }
    ]
    write_json(package_dir / "missing-sha.json", payload)

    with pytest.raises(PackageValidationError, match="replacement.sha256_required"):
        load_package_manifest(package_dir, PackageKind.PATCH)


def test_patch_replacement_path_rejects_invalid_sha256(tmp_path):
    package_dir = tmp_path / "patches" / "bad-sha"
    payload = patch_manifest("bad-sha")
    payload["patch"]["targets"] = [
        {
            "modules": [
                {
                    "operations": [
                        {"replacement": {"path": "payloads/foo.js", "sha256": "not-a-sha"}}
                    ]
                }
            ]
        }
    ]
    write_json(package_dir / "bad-sha.json", payload)

    with pytest.raises(PackageValidationError, match="replacement.sha256_invalid_sha256"):
        load_package_manifest(package_dir, PackageKind.PATCH)


def test_conflicts_with_env_defaults_to_override_and_preserves_error(tmp_path):
    package_dir = tmp_path / "options" / "env-conflicts"
    payload = option_manifest("env-conflicts")
    payload["option"]["conflictsWithEnv"] = [
        {"name": "ANTHROPIC_API_KEY"},
        {"name": "CLAUDE_CONFIG_DIR", "policy": "error"},
        "CLAUDE_CODE_ENTRYPOINT",
    ]
    write_json(package_dir / "env-conflicts.json", payload)

    loaded = load_package_manifest(package_dir, PackageKind.OPTION)

    assert loaded.option is not None
    assert loaded.option.conflicts_with_env[0].policy == "override"
    assert loaded.option.conflicts_with_env[1].policy == "error"
    assert loaded.option.conflicts_with_env[2].policy == "override"



def test_envelope_relationship_metadata_parses(tmp_path):
    package_dir = tmp_path / "thin-drawer"
    package_dir.mkdir()
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "thin-drawer",
        "label": "Thin drawer",
        "description": "Fixture",
        "requiresPackages": ["drawer-dock"],
        "conflictsWithPackages": ["old-drawer"],
        "patch": {"engine": "bun_graph_repack", "targets": [{}]},
    }
    (package_dir / "package.json").write_text(json.dumps(manifest))
    loaded = load_package_manifest(package_dir, PackageKind.PATCH)
    assert loaded.requires_packages == ("drawer-dock",)
    assert loaded.conflicts_with_packages == ("old-drawer",)


def test_envelope_relationship_metadata_defaults_empty(tmp_path):
    package_dir = tmp_path / "plain"
    package_dir.mkdir()
    manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "plain",
        "label": "Plain",
        "description": "Fixture",
        "patch": {"engine": "bun_graph_repack", "targets": [{}]},
    }
    (package_dir / "package.json").write_text(json.dumps(manifest))
    loaded = load_package_manifest(package_dir, PackageKind.PATCH)
    assert loaded.requires_packages == ()
    assert loaded.conflicts_with_packages == ()

def test_package_version_round_trips(tmp_path):
    pkg = tmp_path / "x"
    pkg.mkdir()
    (pkg / "patch.json").write_text(json.dumps({
        "schemaVersion": 1, "kind": "patch", "id": "x", "label": "X",
        "description": "d", "packageVersion": "1.2.3",
        "patch": {"engine": "bun_graph_repack", "targets": []},
    }))
    manifest = load_package_manifest(pkg, PackageKind.PATCH)
    assert manifest.package_version == "1.2.3"

