from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harnessmonkey.platform_support import default_state_dir


@dataclass(frozen=True)
class StatePaths:
    state_dir: Path

    @property
    def config_path(self) -> Path:
        return self.state_dir / "config.json"

    @property
    def current_path(self) -> Path:
        return self.state_dir / "current"

    @property
    def bin_dir(self) -> Path:
        return self.state_dir / "bin"

    @property
    def patches_dir(self) -> Path:
        return self.state_dir / "patches"

    @property
    def prompts_dir(self) -> Path:
        return self.state_dir / "prompts"

    @property
    def options_dir(self) -> Path:
        return self.state_dir / "options"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def versions_dir(self) -> Path:
        return self.state_dir / "versions"

    def patchset_dir(self, source_version: str, patchset_id: str) -> Path:
        return self.versions_dir / source_version / "patchsets" / patchset_id


def default_paths() -> StatePaths:
    return StatePaths(state_dir=default_state_dir())
