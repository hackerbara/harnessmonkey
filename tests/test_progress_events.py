# tests/test_progress_events.py
from harnessmonkey.progress import StageTracker, log_event, plan_event, stage_event


def test_event_shapes():
    assert plan_event((("a", "A"),)) == {
        "event": "plan",
        "stages": [{"id": "a", "label": "A"}],
    }
    assert stage_event("a", "running") == {"event": "stage", "id": "a", "status": "running"}
    assert stage_event("a", "failed", "boom") == {
        "event": "stage", "id": "a", "status": "failed", "message": "boom",
    }
    assert log_event("a", "hi") == {"event": "log", "stage": "a", "line": "hi"}


def test_tracker_lifecycle_and_fail_targets_current_stage():
    seen: list[dict] = []
    t = StageTracker(seen.append)
    t.plan((("a", "A"), ("b", "B")))
    t.start("a")
    t.done()
    t.start("b")
    t.fail("boom")
    assert [e.get("status") for e in seen[1:]] == ["running", "done", "running", "failed"]
    assert seen[-1] == {"event": "stage", "id": "b", "status": "failed", "message": "boom"}


def test_tracker_none_callback_and_swallowed_exceptions():
    t = StageTracker(None)
    t.plan((("a", "A"),))  # no raise, on all methods
    t.start("a")
    t.done()
    t.fail("x")
    t.log("y")

    def bad(_e):
        raise RuntimeError("listener bug")
    t2 = StageTracker(bad)
    t2.start("a")  # must not raise
