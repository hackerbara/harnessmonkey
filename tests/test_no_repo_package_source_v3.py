from __future__ import annotations

import pytest

import harnessmonkey.cli as cli
from harnessmonkey.paths import StatePaths


def test_resolve_package_does_not_use_repo_packages(tmp_path, monkeypatch):
    state = tmp_path / ".harnessmonkey"
    paths = StatePaths(state_dir=state)
    fake_repo = tmp_path / "fake-repo"
    repo_package = fake_repo / "packages" / "repo-only-package"
    repo_package.mkdir(parents=True)
    (repo_package / "repo-only-package.json").write_text("{}")
    monkeypatch.setattr(cli, "_repo_root", lambda: fake_repo, raising=False)

    with pytest.raises(FileNotFoundError):
        cli._resolve_package("repo-only-package", paths)
