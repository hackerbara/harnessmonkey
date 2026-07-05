from __future__ import annotations

from harnessmonkey.config import HarnessMonkeyConfig, LaunchProfile, load_config, save_config
from harnessmonkey.prompts import PromptProfile, prompt_args_for_invocation


def test_config_round_trip(tmp_path):
    config = HarnessMonkeyConfig(
        activeProfile="default",
        profiles={"default": LaunchProfile(patches=["fable-fallback"], prompt="research")},
        installMode="shim",
        activePatchSet="2.1.198-default",
    )
    path = tmp_path / "config.json"
    save_config(path, config)
    loaded = load_config(path)
    assert loaded.profiles["default"].patches == ["fable-fallback"]


def test_prompt_append_file_injected_for_session_invocation(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("extra prompt")
    profile = PromptProfile(id="research", name="Research", path=prompt, mode="append")
    args = prompt_args_for_invocation(["--resume"], profile, supports_file_flags=True)
    assert args == ["--append-system-prompt-file", str(prompt), "--resume"]


def test_user_prompt_flags_override_profile(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("extra prompt")
    profile = PromptProfile(id="research", name="Research", path=prompt, mode="append")
    args = prompt_args_for_invocation(
        ["--system-prompt", "mine", "hello"], profile, supports_file_flags=True
    )
    assert args == ["--system-prompt", "mine", "hello"]


def test_no_injection_for_management_invocation(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("extra prompt")
    profile = PromptProfile(id="research", name="Research", path=prompt, mode="append")
    assert prompt_args_for_invocation(["--version"], profile, supports_file_flags=True) == [
        "--version"
    ]
    assert prompt_args_for_invocation(["mcp", "list"], profile, supports_file_flags=True) == [
        "mcp",
        "list",
    ]


def test_prompt_equals_flags_override_profile(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("extra prompt")
    profile = PromptProfile(id="research", name="Research", path=prompt, mode="append")
    args = prompt_args_for_invocation(["--system-prompt=mine", "hello"], profile, True)
    assert args == ["--system-prompt=mine", "hello"]


def test_prompt_direct_string_fallback_requires_explicit_allow(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("extra prompt")
    profile = PromptProfile(id="research", name="Research", path=prompt, mode="append")
    assert prompt_args_for_invocation(["hello"], profile, supports_file_flags=False) == ["hello"]
    assert prompt_args_for_invocation(
        ["hello"], profile, supports_file_flags=False, allow_direct_string_flags=True
    ) == ["--append-system-prompt", "extra prompt", "hello"]
