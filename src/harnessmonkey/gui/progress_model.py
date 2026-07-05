"""Pure state machine driving the GUI progress dialog's checklist.

`ProgressModel` consumes the progress-event protocol emitted by the CLI
runner (plan/stage/log dicts) plus a terminal result payload, and exposes
the resulting checklist state for a GUI to render. It has no dependency on
any GUI toolkit and performs no I/O.

Defensive by design: the producer side is a subprocess speaking a JSON
protocol, so malformed or drifted events (missing keys, wrong types, unknown
event names) must never raise here. Unrecognized input is treated as a
no-op rather than an error.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StageRow:
    stage_id: str
    label: str
    status: str = "pending"  # pending | running | done | failed | skipped
    message: str | None = None


class ProgressModel:
    """Accumulates plan/stage/log events into a checklist + outcome."""

    def __init__(self) -> None:
        self.rows: list[StageRow] = []
        self.log_lines: list[str] = []
        self.outcome: str | None = None
        self._by_id: dict[str, StageRow] = {}

    def apply_event(self, event: dict) -> None:
        if not isinstance(event, dict):
            return

        kind = event.get("event")
        if kind == "plan":
            self._apply_plan(event)
        elif kind == "stage":
            self._apply_stage(event)
        elif kind == "log":
            self._apply_log(event)
        # Unknown event types are silently ignored (protocol drift).

    def _apply_plan(self, event: dict) -> None:
        stages = event.get("stages")
        if not isinstance(stages, list):
            return

        rows: list[StageRow] = []
        by_id: dict[str, StageRow] = {}
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            stage_id = stage.get("id")
            if stage_id is None:
                continue
            if stage_id in by_id:
                # Duplicate id within the same plan event: first occurrence
                # wins. Silently keeping both would orphan the earlier row
                # in `rows` (unreachable by `_by_id`, forever "pending").
                continue
            label = stage.get("label")
            row = StageRow(stage_id=stage_id, label=label if label is not None else stage_id)
            rows.append(row)
            by_id[stage_id] = row

        self.rows = rows
        self._by_id = by_id

    def _apply_stage(self, event: dict) -> None:
        stage_id = event.get("id")
        status = event.get("status")
        if stage_id is None or status is None:
            return

        row = self._by_id.get(stage_id)
        if row is None:
            # Unknown stage id: append a row rather than crashing, so the
            # GUI stays usable even when the producer drifts from the plan.
            row = StageRow(stage_id=stage_id, label=stage_id)
            self.rows.append(row)
            self._by_id[stage_id] = row

        row.status = status
        # Only carry a message forward when the event actually supplies one;
        # otherwise clear it so a stale error message doesn't survive a
        # later status-only transition (e.g. a retried stage going back to
        # "running", or a subsequent "done").
        row.message = event.get("message") if "message" in event else None

    def _apply_log(self, event: dict) -> None:
        line = event.get("line")
        if line is None:
            return
        self.log_lines.append(line)

    def apply_result(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        if payload.get("ok"):
            self.outcome = "success"
            # A dropped terminal "done" event can leave a row stuck at
            # "running" even though the process reported overall success.
            # Reconcile every such row so the checklist doesn't lie. Also
            # clear any leftover in-flight message (e.g. "retrying") — it
            # described a stage that was still running, not one that
            # finished successfully, so keeping it would mislead the GUI.
            for row in self.rows:
                if row.status == "running":
                    row.status = "done"
                    row.message = None
            return

        self.outcome = "failure"
        if any(row.status == "failed" for row in self.rows):
            return

        # Process died mid-stage with no explicit failure reported: force-fail
        # whichever row was still running so the checklist doesn't lie. The
        # result payload carries no per-stage detail (just "died"), so we
        # deliberately keep the row's last in-flight message rather than
        # clearing it — it's the only clue left about what the stage was
        # doing when the process went away.
        for row in self.rows:
            if row.status == "running":
                row.status = "failed"
                break
