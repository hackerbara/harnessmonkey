from harnessmonkey.gui.progress_model import ProgressModel

PLAN = {"event": "plan", "stages": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}


def test_happy_path():
    m = ProgressModel()
    for e in (PLAN, {"event": "stage", "id": "a", "status": "running"},
              {"event": "stage", "id": "a", "status": "done"},
              {"event": "log", "stage": "b", "line": "working"},
              {"event": "stage", "id": "b", "status": "done"}):
        m.apply_event(e)
    m.apply_result({"ok": True, "summary": "built"})
    assert [r.status for r in m.rows] == ["done", "done"]
    assert m.log_lines == ["working"] and m.outcome == "success"


def test_failure_marks_stage_and_outcome():
    m = ProgressModel()
    m.apply_event(PLAN)
    m.apply_event({"event": "stage", "id": "a", "status": "failed", "message": "boom"})
    m.apply_result({"ok": False, "summary": "failed"})
    assert m.rows[0].status == "failed" and m.rows[0].message == "boom"
    assert m.outcome == "failure"


def test_unknown_stage_id_appends_row():
    m = ProgressModel()
    m.apply_event(PLAN)
    m.apply_event({"event": "stage", "id": "zz", "status": "running"})
    assert m.rows[-1].stage_id == "zz"


def test_result_without_any_stage_failure_but_not_ok():
    m = ProgressModel()
    m.apply_event(PLAN)
    m.apply_event({"event": "stage", "id": "a", "status": "running"})
    m.apply_result({"ok": False, "summary": "died"})  # process died mid-stage
    assert m.rows[0].status == "failed" and m.outcome == "failure"


def test_raw_log_event_with_none_stage_appends_line():
    m = ProgressModel()
    m.apply_event({"event": "log", "stage": None, "line": "raw output"})
    assert m.log_lines == ["raw output"]


def test_malformed_events_do_not_raise():
    m = ProgressModel()
    # Non-dict event
    m.apply_event(None)
    m.apply_event("not a dict")
    m.apply_event(123)
    # Missing "event" key
    m.apply_event({})
    # Unknown event type
    m.apply_event({"event": "mystery"})
    # plan with missing/malformed "stages"
    m.apply_event({"event": "plan"})
    m.apply_event({"event": "plan", "stages": "oops"})
    m.apply_event({"event": "plan", "stages": [{"id": "x"}, {"label": "no id"}]})
    # The entry with no "id" is skipped, so exactly one row survives.
    assert [r.stage_id for r in m.rows] == ["x"]
    assert m.rows[0].label == "x"
    # stage event missing "id"
    m.apply_event({"event": "stage", "status": "running"})
    # stage event missing "status"
    m.apply_event({"event": "stage", "id": "a"})
    # log event missing "line"
    m.apply_event({"event": "log", "stage": None})
    # No rows/log lines should have blown up; model still usable.
    assert isinstance(m.rows, list)
    assert isinstance(m.log_lines, list)


def test_apply_result_malformed_payload_does_not_raise():
    m = ProgressModel()
    m.apply_event(PLAN)
    m.apply_result(None)
    m.apply_result({})
    m.apply_result("nope")
    # outcome should reflect the last processed payload's ok-ish value,
    # but at minimum must not raise and must remain a valid state.
    assert m.outcome in (None, "success", "failure")


def test_duplicate_stage_id_in_plan_deduplicates():
    m = ProgressModel()
    plan = {
        "event": "plan",
        "stages": [
            {"id": "a", "label": "A1"},
            {"id": "a", "label": "A2"},
            {"id": "b", "label": "B"},
        ],
    }
    m.apply_event(plan)
    # Exactly one row for the duplicated id; no orphaned row left behind.
    assert [r.stage_id for r in m.rows] == ["a", "b"]
    # The surviving row is reachable by later stage events.
    m.apply_event({"event": "stage", "id": "a", "status": "done"})
    assert m.rows[0].status == "done"


def test_apply_result_ok_resolves_stuck_running_row():
    m = ProgressModel()
    m.apply_event(PLAN)
    m.apply_event({"event": "stage", "id": "a", "status": "running"})
    # No terminal "done" event arrives for "a" (e.g. dropped by the runner),
    # but the process reports overall success.
    m.apply_result({"ok": True, "summary": "built"})
    assert m.rows[0].status == "done"
    assert m.outcome == "success"


def test_stage_message_clears_on_status_only_transition():
    m = ProgressModel()
    m.apply_event(PLAN)
    m.apply_event({"event": "stage", "id": "a", "status": "running", "message": "retrying"})
    m.apply_event({"event": "stage", "id": "a", "status": "done"})
    assert m.rows[0].status == "done"
    assert m.rows[0].message is None


def test_apply_result_ok_clears_message_on_resolved_running_row():
    m = ProgressModel()
    m.apply_event(PLAN)
    m.apply_event({"event": "stage", "id": "a", "status": "running", "message": "retrying"})
    # No terminal "done" event arrives for "a", but the process succeeds
    # overall. The force-resolved row should not keep the stale in-flight
    # message — it never actually reached "done" with that message.
    m.apply_result({"ok": True, "summary": "built"})
    assert m.rows[0].status == "done"
    assert m.rows[0].message is None
