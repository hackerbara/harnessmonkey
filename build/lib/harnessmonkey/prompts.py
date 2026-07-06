from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPT_FLAG_PREFIXES = {
    "--system-prompt",
    "--system-prompt-file",
    "--append-system-prompt",
    "--append-system-prompt-file",
}
MANAGEMENT_TOKENS = {"--help", "-h", "--version", "update", "mcp", "plugin"}


@dataclass(frozen=True)
class PromptProfile:
    id: str
    name: str
    path: Path
    mode: str = "append"


def is_prompt_flag(arg: str) -> bool:
    return arg in PROMPT_FLAG_PREFIXES or any(
        arg.startswith(flag + "=") for flag in PROMPT_FLAG_PREFIXES
    )


def has_user_prompt_flag(argv: list[str]) -> bool:
    return any(is_prompt_flag(arg) for arg in argv)


def is_management_invocation(argv: list[str]) -> bool:
    if not argv:
        return False
    return argv[0] in MANAGEMENT_TOKENS


def prompt_args_for_invocation(
    argv: list[str],
    profile: PromptProfile | None,
    supports_file_flags: bool,
    allow_direct_string_flags: bool = False,
) -> list[str]:
    if profile is None or has_user_prompt_flag(argv) or is_management_invocation(argv):
        return list(argv)
    if supports_file_flags:
        flag = "--append-system-prompt-file" if profile.mode == "append" else "--system-prompt-file"
        return [flag, str(profile.path), *argv]
    if not allow_direct_string_flags:
        return list(argv)
    text = profile.path.read_text()
    flag = "--append-system-prompt" if profile.mode == "append" else "--system-prompt"
    return [flag, text, *argv]
