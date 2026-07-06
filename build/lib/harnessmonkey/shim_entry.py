from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from harnessmonkey.config import load_config
from harnessmonkey.launch_profile import (
    LaunchMergeInput,
    LaunchMergeResult,
    LaunchTarget,
    is_management_invocation,
    load_active_launch_packages,
    merge_launch_profile,
    select_launch_target,
)
from harnessmonkey.paths import StatePaths


def compute_launch(
    state_dir: Path, user_argv: list[str], process_env: Mapping[str, str]
) -> LaunchMergeResult:
    state_dir = state_dir.expanduser()
    paths = StatePaths(state_dir=state_dir)
    config = load_config(paths.config_path)
    return compute_launch_with_paths(paths, config, user_argv, process_env)


def compute_launch_with_paths(
    paths: StatePaths,
    config,
    user_argv: list[str],
    process_env: Mapping[str, str],
) -> LaunchMergeResult:
    loaded = load_active_launch_packages(paths, config)
    env = dict(process_env)
    target = select_launch_target(
        paths,
        config,
        env,
        prefer_official=is_management_invocation(user_argv),
    )
    if target is None:
        return LaunchMergeResult(
            target=LaunchTarget(path=paths.current_path, kind="missing"),
            argv=list(user_argv),
            env=env,
            env_preview=dict(env),
            skipped=list(loaded.skipped),
            warnings=list(loaded.warnings),
            errors=["no launch target found"],
            management=False,
        )
    return merge_launch_profile(
        LaunchMergeInput(
            user_argv=list(user_argv),
            process_env=env,
            prompt=loaded.prompt,
            options=loaded.options,
            target=target,
            initial_skipped=list(loaded.skipped),
            initial_warnings=list(loaded.warnings),
        )
    )


def main(state_dir_text: str | None = None) -> int:
    state_dir = (
        Path(state_dir_text)
        if state_dir_text is not None
        else Path.home() / ".harnessmonkey"
    )
    result = compute_launch(state_dir, sys.argv[1:], os.environ)
    if result.errors:
        for error in result.errors:
            print(f"HarnessMonkey: {error}", file=sys.stderr)
        return 2
    os.execvpe(str(result.target.path), [str(result.target.path), *result.argv], result.env)
    return 127
