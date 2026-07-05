from __future__ import annotations

from harnessmonkey.builder_v15 import BUILD_STAGES, build_patchset_v15

pytest_plugins = ["tests.builder_fixtures"]


def _stage_seq(events):
    return [(e["id"], e["status"]) for e in events if e["event"] == "stage"]


def test_success_emits_plan_then_stages_in_table_order(successful_build_request, tmp_path):
    events: list[dict] = []
    request = successful_build_request(on_event=events.append, activate=False)
    report = build_patchset_v15(request)
    assert report.status == "verified"
    assert events[0]["event"] == "plan"
    assert [s["id"] for s in events[0]["stages"]] == [i for i, _ in BUILD_STAGES]
    seq = _stage_seq(events)
    assert ("resolve", "done") in seq and ("smoke", "done") in seq
    assert seq[-1] == ("activate", "skipped")  # activate=False


def test_manifest_failure_fails_resolve_stage(bad_manifest_build_request):
    events: list[dict] = []
    report = build_patchset_v15(bad_manifest_build_request(on_event=events.append))
    assert report.status == "failed"
    failed = [e for e in events if e.get("status") == "failed"]
    assert failed and failed[-1]["id"] == "resolve"


def test_none_on_event_changes_nothing(successful_build_request):
    report = build_patchset_v15(successful_build_request(on_event=None, activate=False))
    assert report.status == "verified"
