from __future__ import annotations

from pathlib import Path

from harnessmonkey.config import HarnessMonkeyConfig, LaunchProfile
from harnessmonkey.paths import StatePaths
from harnessmonkey.source_discovery import discover_official_claude, is_managed_launcher_path


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho claude\n")
    path.chmod(0o755)
    return path


def config(path: str | None = None) -> HarnessMonkeyConfig:
    return HarnessMonkeyConfig(
        activeProfile="default",
        profiles={"default": LaunchProfile()},
        officialClaudePath=path,
    )


def test_durable_config_source_wins_over_env(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    durable = executable(tmp_path / "durable" / "claude")
    env_source = executable(tmp_path / "env" / "claude")
    found = discover_official_claude(
        config(str(durable)),
        paths,
        {"HARNESSMONKEY_SOURCE": str(env_source)},
        lambda _: None,
    )
    assert found == durable.resolve()


def test_env_source_used_when_no_durable_source(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    env_source = executable(tmp_path / "env" / "claude")
    found = discover_official_claude(
        config(), paths, {"HARNESSMONKEY_SOURCE": str(env_source)}, lambda _: None
    )
    assert found == env_source.resolve()


def test_path_lookup_ignores_managed_shim(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    shim = executable(paths.bin_dir / "claude")
    assert is_managed_launcher_path(shim.resolve(), paths)
    found = discover_official_claude(config(), paths, {}, lambda _: str(shim))
    assert found is None


def test_current_symlink_target_is_rejected(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    current_target = executable(
        paths.state_dir / "versions" / "2.1.199" / "patchsets" / "default" / "claude"
    )
    paths.current_path.parent.mkdir(parents=True, exist_ok=True)
    paths.current_path.symlink_to(current_target)
    found = discover_official_claude(config(str(paths.current_path)), paths, {}, lambda _: None)
    assert found is None


def test_direct_managed_patchset_path_is_rejected(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    managed = executable(
        paths.state_dir / "versions" / "2.1.199" / "patchsets" / "default" / "claude"
    )
    found = discover_official_claude(config(str(managed)), paths, {}, lambda _: None)
    assert found is None


def test_managed_current_symlink_target_is_rejected(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    managed = executable(
        paths.state_dir / "versions" / "2.1.199" / "patchsets" / "default" / "claude"
    )
    paths.current_path.parent.mkdir(parents=True, exist_ok=True)
    paths.current_path.symlink_to(managed)

    found = discover_official_claude(config(str(managed.resolve())), paths, {}, lambda _: None)

    assert found is None


def test_external_official_current_target_remains_discoverable(tmp_path):
    paths = StatePaths(state_dir=tmp_path / ".harnessmonkey")
    official = executable(tmp_path / "official" / "claude")
    paths.current_path.parent.mkdir(parents=True, exist_ok=True)
    paths.current_path.symlink_to(official)

    found = discover_official_claude(config(str(official)), paths, {}, lambda _: None)

    assert found == official.resolve()
