from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class LaunchProfile:
    prompt: str | None = None
    patches: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)


@dataclass
class HarnessMonkeyConfig:
    activeProfile: str
    profiles: dict[str, LaunchProfile]
    schemaVersion: int = 1
    installMode: str = "shim"
    activePatchSet: str | None = None
    officialClaudePath: str | None = None


def default_config() -> HarnessMonkeyConfig:
    return HarnessMonkeyConfig(
        activeProfile="default", profiles={"default": LaunchProfile()}
    )


def _load_profile(value: dict) -> LaunchProfile:
    # V3 renamed the old V2 profile fields but existing local installs may
    # still carry the legacy shape. Treat that as an on-read migration so the
    # GUI does not silently forget the user's active patch/prompt selection.
    patches = value.get("patches")
    if patches is None:
        patches = value.get("enabledPatches")
    if patches is None:
        patches = value.get("patchIds")
    if patches is None:
        patches = []
    prompt = value.get("prompt")
    if prompt is None:
        prompt = value.get("promptProfile")
    return LaunchProfile(
        prompt=prompt,
        patches=list(patches),
        options=list(value.get("options", [])),
    )


def load_config(path: Path) -> HarnessMonkeyConfig:
    if not path.exists():
        return default_config()
    raw = json.loads(path.read_text())
    profiles_raw = raw["profiles"]
    if set(profiles_raw.keys()) != {"default"}:
        raise ValueError("only_default_profile_supported")
    if raw["activeProfile"] != "default":
        raise ValueError("active_profile_must_be_default")
    return HarnessMonkeyConfig(
        schemaVersion=raw.get("schemaVersion", 1),
        activeProfile=raw["activeProfile"],
        profiles={name: _load_profile(value) for name, value in profiles_raw.items()},
        installMode=raw.get("installMode", "shim"),
        activePatchSet=raw.get("activePatchSet"),
        officialClaudePath=raw.get("officialClaudePath"),
    )


def save_config(path: Path, config: HarnessMonkeyConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, sort_keys=True) + "\n")
