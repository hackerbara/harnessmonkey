from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harnessmonkey.authorization import target_needs_authorization


@dataclass(frozen=True)
class InstallTargetPlan:
    target: Path
    authorization_required: bool
    authorization_reason: str | None
    planned_actions: tuple[str, ...]


def managed_user_target(state_dir: Path) -> Path:
    return state_dir.expanduser() / "bin" / "claude"


def install_plan_for_target(target: Path, *, state_dir: Path) -> InstallTargetPlan:
    del state_dir  # Reserved for later UI display and dry-run context.
    expanded = target.expanduser()
    authorization_required = target_needs_authorization(expanded)
    return InstallTargetPlan(
        target=expanded,
        authorization_required=authorization_required,
        authorization_reason=(
            "protected target requires narrow install authorization"
            if authorization_required
            else None
        ),
        planned_actions=(
            f"dry-run install-shim --target {expanded}",
            (
                "request authorization only for install/restore operation"
                if authorization_required
                else "install without elevation"
            ),
            "run CLI/core install transaction",
        ),
    )
