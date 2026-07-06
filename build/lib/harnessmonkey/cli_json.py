from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ErrorPayload:
    message: str
    code: str | None = None


@dataclass(frozen=True)
class CommandEnvelope:
    schemaVersion: int = 1
    ok: bool = True
    status: str = "ok"
    summary: str = "ok"
    reportPath: str | None = None
    targetPath: str | None = None
    authorizationRequired: bool = False
    authorizationMethod: str | None = None
    buildStrategy: str | None = None
    changedModules: list[dict[str, Any]] | None = None
    repackSummary: dict[str, Any] | None = None
    dryRun: bool = False
    plannedActions: list[str] = field(default_factory=list)
    error: ErrorPayload | None = None


def envelope_ok(
    summary: str,
    *,
    report_path: Path | str | None = None,
    target_path: Path | str | None = None,
    authorization_required: bool = False,
    authorization_method: str | None = None,
    dry_run: bool = False,
    planned_actions: list[str] | None = None,
    status: str = "ok",
    build_strategy: str | None = None,
    changed_modules: list[dict[str, Any]] | None = None,
    repack_summary: dict[str, Any] | None = None,
) -> CommandEnvelope:
    return CommandEnvelope(
        ok=True,
        status=status,
        summary=summary,
        reportPath=str(report_path) if report_path is not None else None,
        targetPath=str(target_path) if target_path is not None else None,
        authorizationRequired=authorization_required,
        authorizationMethod=authorization_method,
        buildStrategy=build_strategy,
        changedModules=changed_modules,
        repackSummary=repack_summary,
        dryRun=dry_run,
        plannedActions=list(planned_actions or []),
        error=None,
    )


def envelope_error(
    message: str,
    *,
    code: str | None = None,
    dry_run: bool = False,
    planned_actions: list[str] | None = None,
    status: str = "error",
    report_path: Path | str | None = None,
    target_path: Path | str | None = None,
    authorization_required: bool = False,
    authorization_method: str | None = None,
) -> CommandEnvelope:
    return CommandEnvelope(
        ok=False,
        status=status,
        summary=message,
        reportPath=str(report_path) if report_path is not None else None,
        targetPath=str(target_path) if target_path is not None else None,
        authorizationRequired=authorization_required,
        authorizationMethod=authorization_method,
        dryRun=dry_run,
        plannedActions=list(planned_actions or []),
        error=ErrorPayload(message=message, code=code),
    )


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value


def print_json(value: Any) -> None:
    print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))
