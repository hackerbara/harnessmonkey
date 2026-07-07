from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from harnessmonkey.config import HarnessMonkeyConfig
from harnessmonkey.install import resolve_cached_source
from harnessmonkey.package_model import (
    PROMPT_FLAGS,
    PackageKind,
    PackageManifest,
    PackageValidationError,
    load_package_manifest,
    validate_package_id,
)
from harnessmonkey.paths import StatePaths
from harnessmonkey.source_discovery import discover_official_claude, is_managed_launcher_path

MANAGEMENT_TOKENS = frozenset(
    {
        "--help",
        "-h",
        "--version",
        "update",
        "upgrade",
        "doctor",
        "auth",
        "mcp",
        "plugin",
        "plugins",
        "install",
    }
)


@dataclass(frozen=True)
class LaunchTarget:
    path: Path
    kind: str


@dataclass(frozen=True)
class LoadedLaunchPackages:
    prompt: PackageManifest | None
    options: list[PackageManifest]
    skipped: list[dict[str, str]]
    warnings: list[str]


@dataclass(frozen=True)
class LaunchMergeInput:
    user_argv: list[str]
    process_env: dict[str, str]
    prompt: PackageManifest | None
    options: list[PackageManifest]
    target: LaunchTarget
    initial_skipped: list[dict[str, str]]
    initial_warnings: list[str]


@dataclass(frozen=True)
class LaunchMergeResult:
    target: LaunchTarget
    argv: list[str]
    env: dict[str, str]
    env_preview: dict[str, str]
    skipped: list[dict[str, str]]
    warnings: list[str]
    errors: list[str]
    management: bool


def _skip(kind: str, package_id: str, reason: str) -> dict[str, str]:
    return {"kind": kind, "id": package_id, "reason": reason}


def _warning(kind: str, package_id: str, reason: str) -> str:
    return f"{kind} {package_id} skipped: {reason}"


def _has_prompt_flag_token(token: str) -> bool:
    return token in PROMPT_FLAGS or any(token.startswith(f"{flag}=") for flag in PROMPT_FLAGS)


def has_user_prompt_flag(user_argv: list[str]) -> bool:
    return any(_has_prompt_flag_token(item) for item in user_argv)


def is_management_invocation(user_argv: list[str]) -> bool:
    if not user_argv or user_argv[0] == "--":
        return False
    return user_argv[0] in MANAGEMENT_TOKENS


def _load_optional_package(
    root: Path, package_id: str, kind: PackageKind
) -> tuple[PackageManifest | None, dict[str, str] | None, str | None]:
    try:
        safe_package_id = validate_package_id(package_id)
    except PackageValidationError as exc:
        skipped = _skip(kind.value, package_id, "invalid_id")
        return None, skipped, f"{kind.value} {package_id} skipped: invalid id ({exc})"
    package_dir = root / safe_package_id
    if not package_dir.exists():
        skipped = _skip(kind.value, package_id, "missing")
        return None, skipped, _warning(kind.value, package_id, "missing")
    try:
        return load_package_manifest(package_dir, kind), None, None
    except PackageValidationError as exc:
        skipped = _skip(kind.value, package_id, "invalid")
        return None, skipped, f"{kind.value} {package_id} skipped: invalid ({exc})"


def load_active_launch_packages(
    paths: StatePaths, config: HarnessMonkeyConfig
) -> LoadedLaunchPackages:
    profile = config.profiles.get(config.activeProfile)
    skipped: list[dict[str, str]] = []
    warnings: list[str] = []
    prompt_manifest: PackageManifest | None = None
    options: list[PackageManifest] = []
    if profile is None:
        return LoadedLaunchPackages(
            prompt=None,
            options=[],
            skipped=[_skip("profile", config.activeProfile, "missing")],
            warnings=[_warning("profile", config.activeProfile, "missing")],
        )

    if profile.prompt:
        prompt_manifest, prompt_skipped, prompt_warning = _load_optional_package(
            paths.prompts_dir, profile.prompt, PackageKind.PROMPT
        )
        if prompt_skipped is not None:
            skipped.append(prompt_skipped)
        if prompt_warning is not None:
            warnings.append(prompt_warning)

    for option_id in profile.options:
        option, option_skipped, option_warning = _load_optional_package(
            paths.options_dir, option_id, PackageKind.OPTION
        )
        if option is not None:
            options.append(option)
        if option_skipped is not None:
            skipped.append(option_skipped)
        if option_warning is not None:
            warnings.append(option_warning)

    return LoadedLaunchPackages(
        prompt=prompt_manifest,
        options=options,
        skipped=skipped,
        warnings=warnings,
    )


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _which_from_env(process_env: dict[str, str]):
    def which(command: str) -> str | None:
        return shutil.which(command, path=process_env.get("PATH"))

    return which


def _install_record_source(paths: StatePaths) -> LaunchTarget | None:
    record_path = paths.state_dir / "install-record.json"
    try:
        record = json.loads(record_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict) or record.get("owner") != "HarnessMonkey managed shim":
        return None

    # Shared with install.py's clean_source_from_install_record: sha proves
    # internal consistency, not provenance, so containment to the state
    # directory's own sources cache is required too (see
    # resolve_cached_source's docstring for the full rationale).
    cache_path = resolve_cached_source(record, paths.state_dir)
    if cache_path is None:
        return None
    if is_managed_launcher_path(cache_path, paths):
        return None
    return LaunchTarget(path=cache_path, kind="install_record_source")


def select_launch_target(
    paths: StatePaths,
    config: HarnessMonkeyConfig,
    process_env: dict[str, str],
    *,
    prefer_official: bool = False,
) -> LaunchTarget | None:
    which = _which_from_env(process_env)
    official = (
        discover_official_claude(
            config, paths, process_env, which, include_install_record=False
        )
        if prefer_official
        else None
    )
    if official is not None:
        return LaunchTarget(path=official, kind="official_fallback")

    try:
        current = paths.current_path.resolve(strict=True)
    except OSError:
        current = None
    if (
        current is not None
        and _is_executable(current)
        and is_managed_launcher_path(current, paths)
        and current.is_relative_to(paths.versions_dir.resolve(strict=False))
    ):
        return LaunchTarget(path=current, kind="patched")

    if official is None:
        official = discover_official_claude(
            config, paths, process_env, which, include_install_record=False
        )
    if official is not None:
        return LaunchTarget(path=official, kind="official_fallback")

    install_record_source = _install_record_source(paths)
    if install_record_source is not None:
        return install_record_source
    return None


def _management_target(target: LaunchTarget) -> LaunchTarget:
    return LaunchTarget(path=target.path, kind="official_management")


def _merge_prompt(
    prompt: PackageManifest | None,
    user_argv: list[str],
    argv: list[str],
    skipped: list[dict[str, str]],
    warnings: list[str],
) -> None:
    if prompt is None or prompt.prompt is None:
        return
    if has_user_prompt_flag(user_argv):
        skipped.append(_skip("prompt", prompt.id, "user_prompt_flag"))
        warnings.append(_warning("prompt", prompt.id, "user_prompt_flag"))
        return
    flag = (
        "--system-prompt-file" if prompt.prompt.mode == "replace" else "--append-system-prompt-file"
    )
    argv.extend([flag, str(prompt.prompt.source.path)])


def _token_matches_conflict(token: str, conflict: str) -> bool:
    return token == conflict or token.startswith(f"{conflict}=")


def _user_has_conflict(user_argv: list[str], conflicts: tuple[str, ...]) -> bool:
    return any(
        _token_matches_conflict(token, conflict) for token in user_argv for conflict in conflicts
    )


def _merge_option_argv(
    option: PackageManifest,
    user_argv: list[str],
    argv: list[str],
    skipped: list[dict[str, str]],
    warnings: list[str],
) -> None:
    if option.option is None or not option.option.argv:
        return
    if _user_has_conflict(user_argv, option.option.conflicts_with_argv):
        skipped.append(_skip("option_argv", option.id, "user_argv_conflict"))
        warnings.append(_warning("option_argv", option.id, "user_argv_conflict"))
        return
    if any(item in argv or item in user_argv for item in option.option.argv):
        skipped.append(_skip("option_argv", option.id, "duplicate_argv"))
        warnings.append(_warning("option_argv", option.id, "duplicate_argv"))
        return
    argv.extend(option.option.argv)


def _option_conflict_errors(options: list[PackageManifest]) -> list[str]:
    enabled_ids = {option.id for option in options}
    errors: list[str] = []
    for option in options:
        if option.option is None:
            continue
        for conflict_id in option.option.conflicts_with_options:
            if conflict_id in enabled_ids:
                errors.append(f"option {option.id} conflicts with enabled option {conflict_id}")
    return errors


def _env_conflict_errors(
    option: PackageManifest,
    env: dict[str, str],
    process_env: dict[str, str],
    skipped: list[dict[str, str]],
    warnings: list[str],
) -> list[str]:
    if option.option is None:
        return []
    errors: list[str] = []
    for conflict in option.option.conflicts_with_env:
        if conflict.policy == "error" and conflict.name in env:
            conflict_source = "process env" if conflict.name in process_env else "env"
            errors.append(f"option {option.id} conflicts with {conflict_source} {conflict.name}")
    if errors:
        skipped.append(_skip("option", option.id, "conflicts_with_env"))
        warnings.append(_warning("option", option.id, "conflicts_with_env"))
    return errors


def _merge_option_env(
    options: list[PackageManifest],
    process_env: dict[str, str],
    env: dict[str, str],
    secret_names: set[str],
    skipped: list[dict[str, str]],
    warnings: list[str],
) -> None:
    for option in options:
        if option.option is None:
            continue
        for name, value in option.option.env.items():
            if value.secret:
                secret_names.add(name)
            if value.value_from_env is not None:
                if value.value_from_env not in process_env:
                    skipped.append(_skip("option_env", option.id, "missing_value_from_env"))
                    warnings.append(
                        f"option_env {option.id} skipped: missing {value.value_from_env}"
                    )
                    continue
                resolved = process_env[value.value_from_env]
            else:
                resolved = value.value or ""

            if name in process_env and not value.allow_override_process_env:
                skipped.append(_skip("option_env", option.id, "process_env_wins"))
                warnings.append(_warning("option_env", option.id, "process_env_wins"))
                continue
            env[name] = resolved


def merge_launch_profile(merge_input: LaunchMergeInput) -> LaunchMergeResult:
    skipped = list(merge_input.initial_skipped)
    warnings = list(merge_input.initial_warnings)
    errors: list[str] = []
    env = dict(merge_input.process_env)
    secret_names: set[str] = set()
    management = is_management_invocation(merge_input.user_argv)
    target = merge_input.target

    if management:
        skipped.append(_skip("launch_profile", "default", "management_invocation"))
        return LaunchMergeResult(
            target=_management_target(target),
            argv=list(merge_input.user_argv),
            env=env,
            env_preview=dict(env),
            skipped=skipped,
            warnings=warnings,
            errors=errors,
            management=True,
        )

    argv: list[str] = []
    _merge_prompt(merge_input.prompt, merge_input.user_argv, argv, skipped, warnings)
    errors.extend(_option_conflict_errors(merge_input.options))
    for option in merge_input.options:
        env_errors = _env_conflict_errors(option, env, merge_input.process_env, skipped, warnings)
        if env_errors:
            errors.extend(env_errors)
            continue
        _merge_option_argv(option, merge_input.user_argv, argv, skipped, warnings)
        _merge_option_env(
            [option],
            merge_input.process_env,
            env,
            secret_names,
            skipped,
            warnings,
        )
    argv.extend(merge_input.user_argv)
    env_preview = {
        name: ("<redacted>" if name in secret_names else value) for name, value in env.items()
    }
    return LaunchMergeResult(
        target=target,
        argv=argv,
        env=env,
        env_preview=env_preview,
        skipped=skipped,
        warnings=warnings,
        errors=errors,
        management=False,
    )
