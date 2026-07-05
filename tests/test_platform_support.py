from __future__ import annotations

import os

from harnessmonkey import platform_support


def test_claude_executable_name_is_plain_on_non_windows(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "darwin")
    assert platform_support.claude_executable_name() == "claude"


def test_claude_executable_name_is_exe_on_windows(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    assert platform_support.claude_executable_name() == "claude.exe"


def test_is_windows_reflects_sys_platform(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    assert platform_support.is_windows() is True
    monkeypatch.setattr(platform_support.sys, "platform", "darwin")
    assert platform_support.is_windows() is False


def test_default_state_dir_uses_home_on_non_windows(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "darwin")
    result = platform_support.default_state_dir({"HOME": "/home/x"})
    assert result == platform_support.Path("/home/x/.harnessmonkey")


def test_default_state_dir_falls_back_to_path_home_when_home_unset(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "darwin")
    result = platform_support.default_state_dir({})
    assert result == platform_support.Path.home() / ".harnessmonkey"


def test_default_state_dir_uses_localappdata_on_windows(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    result = platform_support.default_state_dir(
        {"LOCALAPPDATA": "C:\\Users\\x\\AppData\\Local"}
    )
    assert result == platform_support.Path("C:\\Users\\x\\AppData\\Local") / "HarnessMonkey"


def test_default_state_dir_falls_back_to_appdata_on_windows(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    result = platform_support.default_state_dir({"APPDATA": "C:\\Users\\x\\AppData\\Roaming"})
    assert result == platform_support.Path("C:\\Users\\x\\AppData\\Roaming") / "HarnessMonkey"


def test_default_state_dir_falls_back_to_userprofile_on_windows(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    result = platform_support.default_state_dir({"USERPROFILE": "C:\\Users\\x"})
    assert result == platform_support.Path("C:\\Users\\x") / "AppData" / "Local" / "HarnessMonkey"


def test_default_state_dir_falls_back_to_path_home_on_windows_when_nothing_set(monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    result = platform_support.default_state_dir({})
    assert result == platform_support.Path.home() / "AppData" / "Local" / "HarnessMonkey"


def test_is_executable_file_true_for_exec_bit_on_non_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "darwin")
    path = tmp_path / "prog"
    path.write_text("x")
    path.chmod(0o755)
    assert platform_support.is_executable_file(path) is True


def test_is_executable_file_false_without_exec_bit_on_non_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "darwin")
    path = tmp_path / "prog"
    path.write_text("x")
    path.chmod(0o644)
    assert platform_support.is_executable_file(path) is False


def test_is_executable_file_missing_path_is_false_on_non_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "darwin")
    assert platform_support.is_executable_file(tmp_path / "nope") is False


def test_is_executable_file_true_for_exe_on_windows_with_pathext(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    # is_executable_file splits PATHEXT on os.pathsep, which is correct in
    # production (real Windows' os.pathsep is ";", matching real PATHEXT
    # formatting) but is tied to os.name, not the faked sys.platform -- so on
    # this host it's still ":". Use the host's actual os.pathsep here so the
    # test exercises the exact same split logic that runs in production.
    monkeypatch.setenv("PATHEXT", os.pathsep.join([".COM", ".EXE", ".BAT", ".CMD"]))
    path = tmp_path / "foo.exe"
    path.write_text("x")
    assert platform_support.is_executable_file(path) is True


def test_is_executable_file_false_for_txt_on_windows_with_pathext(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    monkeypatch.setenv("PATHEXT", os.pathsep.join([".COM", ".EXE", ".BAT", ".CMD"]))
    path = tmp_path / "foo.txt"
    path.write_text("x")
    assert platform_support.is_executable_file(path) is False


def test_is_executable_file_true_for_exe_on_windows_without_pathext_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    monkeypatch.delenv("PATHEXT", raising=False)
    path = tmp_path / "foo.exe"
    path.write_text("x")
    assert platform_support.is_executable_file(path) is True


def test_is_executable_file_false_for_txt_on_windows_without_pathext_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    monkeypatch.delenv("PATHEXT", raising=False)
    path = tmp_path / "foo.txt"
    path.write_text("x")
    assert platform_support.is_executable_file(path) is False


def test_windows_claude_install_candidates_launcher_stub_first(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    candidates = platform_support.windows_claude_install_candidates({"USERPROFILE": str(tmp_path)})
    assert candidates[0] == tmp_path / ".local" / "bin" / "claude.exe"


def test_windows_claude_install_candidates_includes_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    versions = tmp_path / ".local" / "share" / "claude" / "versions"
    v1 = versions / "1.0.0"
    v2 = versions / "2.0.0"
    v1.mkdir(parents=True)
    v2.mkdir(parents=True)
    (v1 / "claude.exe").write_text("x")
    (v2 / "claude.exe").write_text("x")

    candidates = platform_support.windows_claude_install_candidates({"USERPROFILE": str(tmp_path)})

    assert candidates[0] == tmp_path / ".local" / "bin" / "claude.exe"
    assert v2 / "claude.exe" in candidates
    assert v1 / "claude.exe" in candidates


def test_windows_claude_install_candidates_no_versions_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, "platform", "win32")
    candidates = platform_support.windows_claude_install_candidates({"USERPROFILE": str(tmp_path)})
    assert candidates == [tmp_path / ".local" / "bin" / "claude.exe"]
