"""Table-driven tests for pure argv builder functions in harnessmonkey.gui.commands.

These builders map GUI intents to CLI argv lists. They must never include a
`harnessmonkey` prefix (CommandRunner adds that separately) and must never
import Qt/PySide6.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harnessmonkey.cli import build_parser
from harnessmonkey.gui import commands

# ---------------------------------------------------------------------------
# 1. command_for_patch_toggle
# ---------------------------------------------------------------------------


def test_patch_toggle_enabled_true_produces_disable():
    # enabled=True means the patch is CURRENTLY on, so the action is to
    # disable it. This direction is easy to invert accidentally.
    assert commands.command_for_patch_toggle("p", enabled=True) == [
        "disable-patch",
        "p",
        "--json",
    ]


def test_patch_toggle_enabled_false_produces_enable():
    assert commands.command_for_patch_toggle("p", enabled=False) == [
        "enable-patch",
        "p",
        "--json",
    ]


# ---------------------------------------------------------------------------
# 2. command_for_option_toggle
# ---------------------------------------------------------------------------


def test_option_toggle_enable_with_confirm():
    # --confirm must come BEFORE --json.
    assert commands.command_for_option_toggle("o", enabled=False, confirm=True) == [
        "enable-option",
        "o",
        "--confirm",
        "--json",
    ]


def test_option_toggle_enable_without_confirm():
    assert commands.command_for_option_toggle("o", enabled=False, confirm=False) == [
        "enable-option",
        "o",
        "--json",
    ]


def test_option_toggle_enable_default_confirm_is_false():
    assert commands.command_for_option_toggle("o", enabled=False) == [
        "enable-option",
        "o",
        "--json",
    ]


def test_option_toggle_disable_ignores_confirm_true():
    assert commands.command_for_option_toggle("o", enabled=True, confirm=True) == [
        "disable-option",
        "o",
        "--json",
    ]


def test_option_toggle_disable_ignores_confirm_false():
    assert commands.command_for_option_toggle("o", enabled=True, confirm=False) == [
        "disable-option",
        "o",
        "--json",
    ]


# ---------------------------------------------------------------------------
# 3. command_for_prompt
# ---------------------------------------------------------------------------


def test_prompt_with_id():
    result = commands.command_for_prompt("my-prompt")
    assert result == ["set-prompt", "my-prompt", "--json"]
    # Sanity: no file-path style flags should ever appear here.
    assert "--from-file" not in result


def test_prompt_with_none():
    result = commands.command_for_prompt(None)
    assert result == ["clear-prompt", "--json"]
    assert "--from-file" not in result


# ---------------------------------------------------------------------------
# 4. command_for_rebuild_apply
# ---------------------------------------------------------------------------


def test_rebuild_apply_takes_no_args_and_is_exact():
    assert commands.command_for_rebuild_apply() == [
        "build",
        "--json",
        "--activate",
        "--progress",
    ]


# ---------------------------------------------------------------------------
# 5. command_for_install_shim
# ---------------------------------------------------------------------------


def test_install_shim_dry_run_excludes_progress_str_target():
    result = commands.command_for_install_shim("/tmp/target", dry_run=True)
    assert result == ["install-shim", "--target", "/tmp/target", "--json", "--dry-run"]
    assert "--progress" not in result


def test_install_shim_dry_run_excludes_progress_path_target():
    result = commands.command_for_install_shim(Path("/tmp/target"), dry_run=True)
    assert result == ["install-shim", "--target", "/tmp/target", "--json", "--dry-run"]
    assert "--progress" not in result


def test_install_shim_real_run_includes_progress_excludes_dry_run():
    result = commands.command_for_install_shim(Path("/tmp/target"), dry_run=False)
    assert result == ["install-shim", "--target", "/tmp/target", "--json", "--progress"]
    assert "--dry-run" not in result


def test_install_shim_default_dry_run_is_false():
    result = commands.command_for_install_shim("/tmp/target")
    assert result == ["install-shim", "--target", "/tmp/target", "--json", "--progress"]


# ---------------------------------------------------------------------------
# 6. command_for_uninstall_shim
# ---------------------------------------------------------------------------


def test_uninstall_shim_no_args():
    assert commands.command_for_uninstall_shim() == ["uninstall-shim", "--json", "--progress"]


def test_uninstall_shim_target_only_dry_run_str():
    assert commands.command_for_uninstall_shim(target="/x", dry_run=True) == [
        "uninstall-shim",
        "--target",
        "/x",
        "--json",
        "--dry-run",
    ]


def test_uninstall_shim_target_only_path():
    result = commands.command_for_uninstall_shim(target=Path("/x"), dry_run=True)
    assert result == ["uninstall-shim", "--target", "/x", "--json", "--dry-run"]


def test_uninstall_shim_record_only_progress():
    assert commands.command_for_uninstall_shim(record="/r") == [
        "uninstall-shim",
        "--record",
        "/r",
        "--json",
        "--progress",
    ]


def test_uninstall_shim_record_only_path_dry_run():
    result = commands.command_for_uninstall_shim(record=Path("/r"), dry_run=True)
    assert result == ["uninstall-shim", "--record", "/r", "--json", "--dry-run"]


def test_uninstall_shim_target_takes_precedence_over_record():
    result = commands.command_for_uninstall_shim(target="/x", record="/r")
    assert result == ["uninstall-shim", "--target", "/x", "--json", "--progress"]


# ---------------------------------------------------------------------------
# 7. command_for_add_package
# ---------------------------------------------------------------------------


def test_add_package_patch():
    assert commands.command_for_add_package("/dir/patch", "patch") == [
        "add-patch",
        "/dir/patch",
        "--json",
    ]


def test_add_package_option():
    assert commands.command_for_add_package("/dir/option", "option") == [
        "add-option",
        "/dir/option",
        "--json",
    ]


def test_add_package_accepts_path():
    assert commands.command_for_add_package(Path("/dir/patch"), "patch") == [
        "add-patch",
        "/dir/patch",
        "--json",
    ]


def test_add_package_rejects_unknown_kind():
    # The real call site (`Controller._action_add_package`) only ever passes
    # "patch"/"option" -- prompts go through `add_prompt_file` instead (a
    # separate action/command). A future typo/new-kind must raise rather
    # than silently falling through to "add-option".
    with pytest.raises(ValueError):
        commands.command_for_add_package("/dir/x", "prompt")


# ---------------------------------------------------------------------------
# 8. command_for_remove_package
# ---------------------------------------------------------------------------


def test_remove_package_patch():
    assert commands.command_for_remove_package("p-id", "patch") == [
        "remove-patch",
        "p-id",
        "--json",
    ]


def test_remove_package_option():
    assert commands.command_for_remove_package("o-id", "option") == [
        "remove-option",
        "o-id",
        "--json",
    ]


def test_remove_package_prompt():
    assert commands.command_for_remove_package("pr-id", "prompt") == [
        "remove-prompt",
        "pr-id",
        "--json",
    ]


# ---------------------------------------------------------------------------
# 9. command_for_add_prompt_file
# ---------------------------------------------------------------------------


def test_add_prompt_file_without_name():
    result = commands.command_for_add_prompt_file(Path("/p/prompt.md"), "pkg-id")
    assert result == ["add-prompt", "/p/prompt.md", "--id", "pkg-id", "--json"]


def test_add_prompt_file_with_name():
    result = commands.command_for_add_prompt_file(
        Path("/p/prompt.md"), "pkg-id", name="My Prompt"
    )
    assert result == [
        "add-prompt",
        "/p/prompt.md",
        "--id",
        "pkg-id",
        "--name",
        "My Prompt",
        "--json",
    ]


def test_add_prompt_file_default_name_is_none():
    result = commands.command_for_add_prompt_file("/p/prompt.md", "pkg-id")
    assert result == ["add-prompt", "/p/prompt.md", "--id", "pkg-id", "--json"]


# ---------------------------------------------------------------------------
# 10. command_for_repair_shim
# ---------------------------------------------------------------------------


def test_repair_shim_takes_no_args_and_is_exact():
    # `repair-shim` (cli.py's repair_shim_parser) has no --dry-run/--progress
    # flags, and always resolves its target from the install record when
    # --target is omitted (cli._resolve_cache_or_repair_target) -- the exact
    # target the GUI wants to repair, so no --target is passed here either.
    assert commands.command_for_repair_shim() == ["repair-shim", "--json"]


# ---------------------------------------------------------------------------
# 11. argv round-trip against the real CLI parser (drift insurance)
# ---------------------------------------------------------------------------
#
# Every test above pins a builder's argv against a hardcoded literal list --
# useful for catching an accidental change to a builder, but it never checks
# that argv is actually valid according to cli.py's real argparse definition
# (`build_parser`). This enumerates every `command_for_*` builder in this
# module (one case per function, reusing the same representative args as the
# hardcoded-list tests above) and feeds each builder's real output straight
# into `build_parser().parse_args(...)` -- the exact argv `CommandRunner`
# passes to `main()`/`parser.parse_args()` (no leading "harnessmonkey"
# program-name entry: that's argv[0] for the *subprocess*
# `CommandRunner._run_command` launches, not part of what argparse itself
# parses -- see `CommandRunner.run_json`/`run_streaming` building
# `[*self.cli_argv, *args]` for `subprocess.Popen`, where `args` is exactly a
# builder's output). A future parser change that drops/renames a flag or
# positional a builder still emits will fail here even though the
# hardcoded-list test for that builder stays green.

_ROUND_TRIP_CASES = {
    "patch_toggle_disable": commands.command_for_patch_toggle("p", enabled=True),
    "patch_toggle_enable": commands.command_for_patch_toggle("p", enabled=False),
    "option_toggle_enable_confirm": commands.command_for_option_toggle(
        "o", enabled=False, confirm=True
    ),
    "option_toggle_disable": commands.command_for_option_toggle("o", enabled=True),
    "prompt_set": commands.command_for_prompt("my-prompt"),
    "prompt_clear": commands.command_for_prompt(None),
    "rebuild_apply": commands.command_for_rebuild_apply(),
    "install_shim_dry_run": commands.command_for_install_shim("/tmp/target", dry_run=True),
    "install_shim_real_run": commands.command_for_install_shim(Path("/tmp/target"), dry_run=False),
    "uninstall_shim_no_args": commands.command_for_uninstall_shim(),
    "uninstall_shim_target": commands.command_for_uninstall_shim(target="/x", dry_run=True),
    "uninstall_shim_record": commands.command_for_uninstall_shim(record="/r"),
    "add_package_patch": commands.command_for_add_package("/dir/patch", "patch"),
    "add_package_option": commands.command_for_add_package("/dir/option", "option"),
    "remove_package_patch": commands.command_for_remove_package("p-id", "patch"),
    "remove_package_option": commands.command_for_remove_package("o-id", "option"),
    "remove_package_prompt": commands.command_for_remove_package("pr-id", "prompt"),
    "add_prompt_file_without_name": commands.command_for_add_prompt_file(
        Path("/p/prompt.md"), "pkg-id"
    ),
    "add_prompt_file_with_name": commands.command_for_add_prompt_file(
        Path("/p/prompt.md"), "pkg-id", name="My Prompt"
    ),
    "repair_shim": commands.command_for_repair_shim(),
}


@pytest.mark.parametrize("argv", _ROUND_TRIP_CASES.values(), ids=_ROUND_TRIP_CASES.keys())
def test_command_builder_argv_parses_with_real_cli_parser(argv):
    build_parser().parse_args(argv)  # must not raise SystemExit/argparse error
