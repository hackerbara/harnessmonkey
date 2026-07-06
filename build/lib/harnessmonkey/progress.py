from __future__ import annotations

from collections.abc import Callable

OnEvent = Callable[[dict], None] | None


def plan_event(stages: tuple[tuple[str, str], ...]) -> dict:
    return {"event": "plan", "stages": [{"id": i, "label": label} for i, label in stages]}


def stage_event(stage_id: str, status: str, message: str | None = None) -> dict:
    event: dict = {"event": "stage", "id": stage_id, "status": status}
    if message is not None:
        event["message"] = message
    return event


def log_event(stage_id: str | None, line: str) -> dict:
    return {"event": "log", "stage": stage_id, "line": line}


class StageTracker:
    def __init__(self, on_event: OnEvent) -> None:
        self._on_event = on_event
        self.current: str | None = None

    def _emit(self, event: dict) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:  # noqa: BLE001 - progress must never break the operation
            pass

    def plan(self, stages: tuple[tuple[str, str], ...]) -> None:
        self._emit(plan_event(stages))

    def start(self, stage_id: str) -> None:
        self.current = stage_id
        self._emit(stage_event(stage_id, "running"))

    def done(self) -> None:
        if self.current is not None:
            self._emit(stage_event(self.current, "done"))
            self.current = None

    def skip(self, stage_id: str, message: str | None = None) -> None:
        self._emit(stage_event(stage_id, "skipped", message))

    def fail(self, message: str) -> None:
        if self.current is not None:
            self._emit(stage_event(self.current, "failed", message))
            self.current = None

    def log(self, line: str) -> None:
        self._emit(log_event(self.current, line))
