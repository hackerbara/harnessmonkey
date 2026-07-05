"""Pure argv builder functions mapping GUI intents to CLI argv lists.

This module is the single source of truth for every command the HarnessMonkey
v3 GUI runs. Every function here is a pure function: no side effects, no I/O,
and no dependency on any GUI toolkit. `CommandRunner` (elsewhere) is
responsible for prefixing the returned argv with the `harnessmonkey`
executable name before executing it.
"""

from __future__ import annotations

from pathlib import Path


def command_for_patch_toggle(patch_id: str, *, enabled: bool) -> list[str]:
    """Build argv to flip a patch's enabled state.

    `enabled` describes the CURRENT state of the patch, so the command
    performs the opposite action: enabled=True (currently on) -> disable;
    enabled=False (currently off) -> enable.
    """
    action = "disable-patch" if enabled else "enable-patch"
    return [action, patch_id, "--json"]


def command_for_option_toggle(
    option_id: str, *, enabled: bool, confirm: bool = False
) -> list[str]:
    """Build argv to flip an option's enabled state.

    Same disable/enable direction as `command_for_patch_toggle`: `enabled`
    describes the CURRENT state. `confirm` only applies when enabling
    (enabled=False); it is ignored when disabling.
    """
    if enabled:
        return ["disable-option", option_id, "--json"]
    if confirm:
        return ["enable-option", option_id, "--confirm", "--json"]
    return ["enable-option", option_id, "--json"]


def command_for_prompt(prompt_id: str | None) -> list[str]:
    """Build argv to set or clear the active prompt.

    `prompt_id` is an id, never a file path -- this function never emits
    `--from-file` or does any path handling.
    """
    if prompt_id is None:
        return ["clear-prompt", "--json"]
    return ["set-prompt", prompt_id, "--json"]


def command_for_rebuild_apply() -> list[str]:
    """Build argv for a rebuild-and-activate run. Takes no arguments."""
    return ["build", "--json", "--activate", "--progress"]


def command_for_install_shim(target: Path | str, *, dry_run: bool = False) -> list[str]:
    """Build argv to install a shim at `target`.

    `target` is stringified with `str()` only -- no `.resolve()`, no
    `.expanduser()`, no other normalization. `--target` is a flag (not a
    positional) in the `install-shim` CLI grammar, and `--json` is required
    for the process to emit a parseable JSON payload on stdout -- both are
    load-bearing for `CommandRunner.run_json`/`run_streaming`.
    """
    mode_flag = "--dry-run" if dry_run else "--progress"
    return ["install-shim", "--target", str(target), "--json", mode_flag]


def command_for_uninstall_shim(
    *,
    target: Path | str | None = None,
    record: Path | str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Build argv to uninstall a shim, identified by `target` or `record`.

    `target` takes precedence if both are given. Neither value is
    normalized beyond `str()`. `--json` is required for the process to emit
    a parseable JSON payload on stdout -- load-bearing for
    `CommandRunner.run_json`/`run_streaming`.
    """
    argv = ["uninstall-shim"]
    if target is not None:
        argv.extend(["--target", str(target)])
    elif record is not None:
        argv.extend(["--record", str(record)])
    argv.append("--json")
    argv.append("--dry-run" if dry_run else "--progress")
    return argv


def command_for_add_package(path: Path | str, kind: str) -> list[str]:
    """Build argv to add a patch or option package located at `path`.

    `kind` is a closed set of `{"patch", "option"}` -- the only two kinds
    `Controller._action_add_package` ever passes (prompts go through
    `command_for_add_prompt_file`/`add_prompt_file` instead, a separate
    action/command). An unrecognized `kind` raises rather than silently
    falling through to "add-option", matching `command_for_remove_package`'s
    dict-literal `KeyError` behavior for the same kind of guard.
    """
    if kind == "patch":
        return ["add-patch", str(path), "--json"]
    if kind == "option":
        return ["add-option", str(path), "--json"]
    raise ValueError(f"unknown package kind: {kind!r}")


def command_for_remove_package(package_id: str, kind: str) -> list[str]:
    """Build argv to remove a patch, option, or prompt package by id."""
    action = {
        "patch": "remove-patch",
        "option": "remove-option",
        "prompt": "remove-prompt",
    }[kind]
    return [action, package_id, "--json"]


def command_for_repair_shim() -> list[str]:
    """Build argv to repair the managed shim after an official update.

    Deliberately takes no `target` argument: `repair-shim` (see
    `cli.py`'s `repair_shim_parser`) has no `--dry-run`/`--progress` flags,
    and when `--target` is omitted it resolves the target itself from the
    install record's own `targetPath`
    (`cli._resolve_cache_or_repair_target`) -- the exact target this
    action means to repair. This also sidesteps a real gap in `status
    --json`: `shimTargetPath`/`installRecordPath` are both `None`
    precisely when repair is needed (they're gated on `shimInstalled`,
    which is false in exactly that state), so `MenuState` has no target
    path for the GUI to pass explicitly anyway.
    """
    return ["repair-shim", "--json"]


def command_for_add_prompt_file(
    path: Path | str, package_id: str, name: str | None = None
) -> list[str]:
    """Build argv to register a prompt file under `package_id`.

    `path` is stringified with `str()` only -- no expansion.
    """
    argv = ["add-prompt", str(path), "--id", package_id]
    if name is not None:
        argv.extend(["--name", name])
    argv.append("--json")
    return argv
