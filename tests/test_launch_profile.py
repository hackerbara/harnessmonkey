from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harnessmonkey.config import HarnessMonkeyConfig, LaunchProfile
from harnessmonkey.launch_profile import (
    MANAGEMENT_TOKENS,
    LaunchMergeInput,
    LaunchTarget,
    LoadedLaunchPackages,
    is_management_invocation,
    load_active_launch_packages,
    merge_launch_profile,
    select_launch_target,
)
from harnessmonkey.package_model import (
    EnvConflict,
    EnvValue,
    OptionPackage,
    PackageKind,
    PackageManifest,
    PromptPackage,
    PromptSource,
)
from harnessmonkey.paths import StatePaths


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho claude\n")
    path.chmod(0o755)
    return path


def manifest(
    tmp_path: Path,
    package_id: str,
    kind: PackageKind,
    *,
    prompt: PromptPackage | None = None,
    option: OptionPackage | None = None,
) -> PackageManifest:
    package_dir = tmp_path / package_id
    package_dir.mkdir(exist_ok=True)
    return PackageManifest(
        schema_version=1,
        kind=kind,
        id=package_id,
        label=package_id,
        description=package_id,
        package_version="0.0.0",
        package_dir=package_dir,
        manifest_path=package_dir / f"{package_id}.json",
        risk=None,
        compatibility=None,
        prompt=prompt,
        option=option,
        patch=None,
        raw={},
    )


def prompt_manifest(tmp_path: Path, package_id: str, mode: str) -> PackageManifest:
    source = tmp_path / package_id / "prompt.md"
    source.parent.mkdir(exist_ok=True)
    source.write_text("prompt")
    return manifest(
        tmp_path,
        package_id,
        PackageKind.PROMPT,
        prompt=PromptPackage(mode=mode, source=PromptSource(path=source)),
    )


def option_manifest(
    tmp_path: Path,
    package_id: str,
    *,
    argv: tuple[str, ...] = (),
    env: dict[str, EnvValue] | None = None,
    conflicts_with_argv: tuple[str, ...] = (),
    conflicts_with_options: tuple[str, ...] = (),
    conflicts_with_env: tuple[EnvConflict, ...] = (),
) -> PackageManifest:
    return manifest(
        tmp_path,
        package_id,
        PackageKind.OPTION,
        option=OptionPackage(
            argv=argv,
            env=env or {},
            conflicts_with_argv=conflicts_with_argv,
            conflicts_with_options=conflicts_with_options,
            conflicts_with_env=conflicts_with_env,
        ),
    )


def merge(
    *,
    user_argv: list[str] | None = None,
    process_env: dict[str, str] | None = None,
    prompt: PackageManifest | None = None,
    options: list[PackageManifest] | None = None,
) -> object:
    return merge_launch_profile(
        LaunchMergeInput(
            user_argv=user_argv or [],
            process_env=process_env or {},
            prompt=prompt,
            options=options or [],
            target=LaunchTarget(path=Path("/bin/claude"), kind="patched"),
            initial_skipped=[],
            initial_warnings=[],
        )
    )


@pytest.mark.parametrize(
    ("mode", "flag"),
    [("append", "--append-system-prompt-file"), ("replace", "--system-prompt-file")],
)
def test_prompt_append_and_replace_flag_mapping(tmp_path, mode, flag):
    prompt = prompt_manifest(tmp_path, "research", mode)

    result = merge(user_argv=["chat"], prompt=prompt)

    assert result.argv == [flag, str(prompt.prompt.source.path), "chat"]
    assert result.errors == []


def test_user_prompt_flag_skips_active_prompt(tmp_path):
    prompt = prompt_manifest(tmp_path, "research", "append")

    result = merge(user_argv=["--system-prompt", "mine"], prompt=prompt)

    assert result.argv == ["--system-prompt", "mine"]
    assert result.skipped == [{"kind": "prompt", "id": "research", "reason": "user_prompt_flag"}]


@pytest.mark.parametrize("token", sorted(MANAGEMENT_TOKENS))
def test_management_tokens_skip_prompt_and_option_injection(tmp_path, token):
    prompt = prompt_manifest(tmp_path, "research", "append")
    option = option_manifest(tmp_path, "debug", argv=("--debug",))

    result = merge(user_argv=[token, "extra"], prompt=prompt, options=[option])

    assert result.management is True
    assert result.argv == [token, "extra"]
    assert result.target.kind == "official_management"
    assert result.skipped == [
        {"kind": "launch_profile", "id": "default", "reason": "management_invocation"}
    ]


def test_double_dash_boundary_prevents_management_detection(tmp_path):
    prompt = prompt_manifest(tmp_path, "research", "append")

    assert is_management_invocation(["--", "doctor"]) is False
    result = merge(user_argv=["--", "doctor"], prompt=prompt)

    assert result.management is False
    assert result.argv[:2] == ["--append-system-prompt-file", str(prompt.prompt.source.path)]


def test_user_argv_conflict_skips_whole_option_argv_contribution(tmp_path):
    option = option_manifest(
        tmp_path,
        "opus",
        argv=("--model", "opus"),
        conflicts_with_argv=("--model",),
    )

    result = merge(user_argv=["--model", "sonnet"], options=[option])

    assert result.argv == ["--model", "sonnet"]
    assert result.skipped == [{"kind": "option_argv", "id": "opus", "reason": "user_argv_conflict"}]


def test_conflicts_with_options_between_enabled_options_creates_error(tmp_path):
    first = option_manifest(tmp_path, "first", conflicts_with_options=("second",))
    second = option_manifest(tmp_path, "second")

    result = merge(options=[first, second])

    assert result.errors == ["option first conflicts with enabled option second"]


def test_process_env_wins_unless_option_allows_override(tmp_path):
    option = option_manifest(
        tmp_path,
        "envs",
        env={
            "KEEP": EnvValue(value="option"),
            "OVERRIDE": EnvValue(value="option", allow_override_process_env=True),
        },
    )

    result = merge(process_env={"KEEP": "process", "OVERRIDE": "process"}, options=[option])

    assert result.env["KEEP"] == "process"
    assert result.env["OVERRIDE"] == "option"
    assert {"kind": "option_env", "id": "envs", "reason": "process_env_wins"} in result.skipped


def test_conflicts_with_env_error_blocks_merge(tmp_path):
    option = option_manifest(
        tmp_path,
        "proxy",
        conflicts_with_env=(EnvConflict(name="HTTP_PROXY", policy="error"),),
    )

    result = merge(process_env={"HTTP_PROXY": "http://proxy"}, options=[option])

    assert result.errors == ["option proxy conflicts with process env HTTP_PROXY"]


def test_value_from_env_and_secret_preview_redaction(tmp_path):
    option = option_manifest(
        tmp_path,
        "secrets",
        env={
            "API_KEY": EnvValue(value="secret-value", secret=True),
            "COPIED": EnvValue(value_from_env="SOURCE_TOKEN", secret=True),
            "MISSING": EnvValue(value_from_env="MISSING_SOURCE"),
        },
    )

    result = merge(process_env={"SOURCE_TOKEN": "copied-secret"}, options=[option])

    assert result.env["API_KEY"] == "secret-value"
    assert result.env["COPIED"] == "copied-secret"
    assert result.env_preview["API_KEY"] == "<redacted>"
    assert result.env_preview["COPIED"] == "<redacted>"
    assert "MISSING" not in result.env
    assert {
        "kind": "option_env",
        "id": "secrets",
        "reason": "missing_value_from_env",
    } in result.skipped


def test_conflicts_with_env_error_blocks_option_argv_and_env(tmp_path):
    option = option_manifest(
        tmp_path,
        "proxy",
        argv=("--proxy-mode", "local"),
        env={"CLAUDE_PROXY_MODE": EnvValue(value="local")},
        conflicts_with_env=(EnvConflict(name="HTTP_PROXY", policy="error"),),
    )

    result = merge(process_env={"HTTP_PROXY": "http://proxy"}, options=[option])

    assert result.errors == ["option proxy conflicts with process env HTTP_PROXY"]
    assert result.argv == []
    assert "CLAUDE_PROXY_MODE" not in result.env
    assert {"kind": "option", "id": "proxy", "reason": "conflicts_with_env"} in result.skipped


def test_secret_env_redacted_when_process_env_wins(tmp_path):
    option = option_manifest(
        tmp_path,
        "secrets",
        env={"API_KEY": EnvValue(value="option-secret", secret=True)},
    )

    result = merge(process_env={"API_KEY": "process-secret"}, options=[option])

    assert result.env["API_KEY"] == "process-secret"
    assert result.env_preview["API_KEY"] == "<redacted>"
    assert {"kind": "option_env", "id": "secrets", "reason": "process_env_wins"} in result.skipped


def test_load_active_launch_packages_skips_missing_packages_with_warnings(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    config = HarnessMonkeyConfig(
        activeProfile="default",
        profiles={"default": LaunchProfile(prompt="missing-prompt", options=["missing-option"])},
    )

    loaded = load_active_launch_packages(paths, config)

    assert isinstance(loaded, LoadedLaunchPackages)
    assert loaded.prompt is None
    assert loaded.options == []
    assert {"kind": "prompt", "id": "missing-prompt", "reason": "missing"} in loaded.skipped
    assert {"kind": "option", "id": "missing-option", "reason": "missing"} in loaded.skipped
    assert any("missing-prompt" in warning for warning in loaded.warnings)
    assert any("missing-option" in warning for warning in loaded.warnings)


def test_load_active_launch_packages_skips_invalid_option_with_warning(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    option_dir = paths.options_dir / "bad-option"
    option_dir.mkdir(parents=True)
    (option_dir / "bad-option.json").write_text(
        """
        {
          "schemaVersion": 1,
          "kind": "prompt",
          "id": "bad-option",
          "label": "Bad option",
          "description": "Wrong bucket",
          "prompt": {"mode": "append", "source": {"path": "prompt.md"}}
        }
        """
    )
    config = HarnessMonkeyConfig(
        activeProfile="default",
        profiles={"default": LaunchProfile(options=["bad-option"])},
    )

    loaded = load_active_launch_packages(paths, config)

    assert loaded.prompt is None
    assert loaded.options == []
    assert {"kind": "option", "id": "bad-option", "reason": "invalid"} in loaded.skipped
    assert any("bad-option" in warning and "invalid" in warning for warning in loaded.warnings)


def test_load_active_launch_packages_rejects_non_slug_active_ids_before_path_join(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    outside_dir = paths.state_dir / "outside-option"
    outside_dir.mkdir(parents=True)
    (outside_dir / "outside-option.json").write_text(
        """
        {
          "schemaVersion": 1,
          "kind": "option",
          "id": "outside-option",
          "label": "Outside option",
          "description": "Should not be loadable via ../",
          "option": {
            "argv": ["--outside"],
            "env": {},
            "conflictsWithArgv": [],
            "conflictsWithOptions": [],
            "conflictsWithEnv": []
          }
        }
        """
    )
    config = HarnessMonkeyConfig(
        activeProfile="default",
        profiles={"default": LaunchProfile(options=["../outside-option"])},
    )

    loaded = load_active_launch_packages(paths, config)

    assert loaded.options == []
    assert {"kind": "option", "id": "../outside-option", "reason": "invalid_id"} in loaded.skipped
    assert any(
        "../outside-option" in warning and "invalid id" in warning for warning in loaded.warnings
    )


def test_select_launch_target_uses_executable_managed_patched_current(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    patched = paths.patchset_dir("2.1.199", "default") / "claude"
    patched.parent.mkdir(parents=True)
    patched.write_text("#!/bin/sh\necho patched\n")
    patched.chmod(0o755)
    paths.current_path.parent.mkdir(parents=True, exist_ok=True)
    paths.current_path.symlink_to(patched)
    config = HarnessMonkeyConfig(activeProfile="default", profiles={"default": LaunchProfile()})

    target = select_launch_target(paths, config, {"PATH": ""})

    assert target is not None
    assert target.kind == "patched"
    assert target.path == patched.resolve()


def test_select_launch_target_uses_official_fallback_when_current_unusable(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    official = tmp_path / "official" / "claude"
    official.parent.mkdir(parents=True)
    official.write_text("#!/bin/sh\necho official\n")
    official.chmod(0o755)
    config = HarnessMonkeyConfig(
        activeProfile="default",
        profiles={"default": LaunchProfile()},
        officialClaudePath=str(official),
    )

    target = select_launch_target(paths, config, {"PATH": ""})

    assert target is not None
    assert target.kind == "official_fallback"
    assert target.path == official.resolve()


def test_user_argv_conflict_matches_equals_form(tmp_path):
    option = option_manifest(
        tmp_path,
        "opus",
        argv=("--model", "opus"),
        conflicts_with_argv=("--model",),
    )

    result = merge(user_argv=["--model=sonnet"], options=[option])

    assert result.argv == ["--model=sonnet"]
    assert result.skipped == [{"kind": "option_argv", "id": "opus", "reason": "user_argv_conflict"}]


def test_duplicate_option_argv_skips_whole_option_contribution(tmp_path):
    first = option_manifest(tmp_path, "opus", argv=("--model", "opus"))
    second = option_manifest(tmp_path, "sonnet", argv=("--model", "sonnet"))

    result = merge(options=[first, second])

    assert result.argv == ["--model", "opus"]
    assert result.skipped == [{"kind": "option_argv", "id": "sonnet", "reason": "duplicate_argv"}]


def test_conflicts_with_env_error_checks_earlier_option_env(tmp_path):
    first = option_manifest(
        tmp_path,
        "first",
        env={"FOO": EnvValue(value="one")},
    )
    second = option_manifest(
        tmp_path,
        "second",
        argv=("--second",),
        env={"FOO": EnvValue(value="two")},
        conflicts_with_env=(EnvConflict(name="FOO", policy="error"),),
    )

    result = merge(options=[first, second])

    assert result.errors == ["option second conflicts with env FOO"]
    assert result.env["FOO"] == "one"
    assert result.argv == []
    assert {"kind": "option", "id": "second", "reason": "conflicts_with_env"} in result.skipped


def test_duplicate_option_argv_checks_explicit_user_argv(tmp_path):
    option = option_manifest(tmp_path, "debug", argv=("--debug",))

    result = merge(user_argv=["--debug"], options=[option])

    assert result.argv == ["--debug"]
    assert result.skipped == [{"kind": "option_argv", "id": "debug", "reason": "duplicate_argv"}]


def test_select_launch_target_uses_cached_previous_source_when_shim_hides_path_source(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    shim_target = executable(tmp_path / "bin" / "claude")
    cached = executable(paths.state_dir / "sources" / "abc" / "claude")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "owner": "HarnessMonkey managed shim",
        "targetPath": str(shim_target),
        "stateDir": str(paths.state_dir),
        "installedShimSha256": "not-checked-here",
        "previousSourceCachePath": str(cached),
        "previousSourceSha256": hashlib.sha256(cached.read_bytes()).hexdigest(),
    }
    (paths.state_dir / "install-record.json").write_text(json.dumps(record))
    config = HarnessMonkeyConfig(activeProfile="default", profiles={"default": LaunchProfile()})

    target = select_launch_target(paths, config, {"PATH": str(shim_target.parent)})

    assert target is not None
    assert target.kind == "install_record_source"
    assert target.path == cached.resolve()


def test_select_launch_target_prefers_official_over_install_record_cache_when_both_available(
    tmp_path,
):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    official = executable(tmp_path / "official" / "claude")
    shim_target = executable(tmp_path / "bin" / "claude")
    cached = executable(paths.state_dir / "sources" / "abc" / "claude")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "owner": "HarnessMonkey managed shim",
        "targetPath": str(shim_target),
        "stateDir": str(paths.state_dir),
        "installedShimSha256": "not-checked-here",
        "previousSourceCachePath": str(cached),
        "previousSourceSha256": hashlib.sha256(cached.read_bytes()).hexdigest(),
    }
    (paths.state_dir / "install-record.json").write_text(json.dumps(record))
    config = HarnessMonkeyConfig(
        activeProfile="default",
        profiles={"default": LaunchProfile()},
        officialClaudePath=str(official),
    )

    target = select_launch_target(paths, config, {"PATH": str(shim_target.parent)})

    assert target is not None
    assert target.kind == "official_fallback"
    assert target.path == official.resolve()
