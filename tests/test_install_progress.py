from harnessmonkey.install import SHIM_STAGES, install_shim_transaction, restore_install_transaction


def _stage_seq(events):
    return [(e["id"], e["status"]) for e in events if e["event"] == "stage"]


def test_shim_stages_defined():
    assert SHIM_STAGES == (
        ("preflight", "Preflight checks"),
        ("record", "Write install record"),
        ("swap", "Swap shim"),
    )


def test_install_emits_three_stages(tmp_path):
    events: list[dict] = []
    target = tmp_path / "bin" / "claude"
    record = install_shim_transaction(
        target, tmp_path / "state", dry_run=False, on_event=events.append
    )
    assert record.exists()
    assert events[0]["event"] == "plan"
    assert _stage_seq(events) == [
        ("preflight", "running"), ("preflight", "done"),
        ("record", "running"), ("record", "done"),
        ("swap", "running"), ("swap", "done"),
    ]


def test_dry_run_stops_after_preflight(tmp_path):
    events: list[dict] = []
    install_shim_transaction(
        tmp_path / "claude", tmp_path / "state", dry_run=True, on_event=events.append
    )
    assert _stage_seq(events) == [("preflight", "running"), ("preflight", "done")]


def test_restore_missing_record_fails_preflight(tmp_path):
    events: list[dict] = []
    ok = restore_install_transaction(
        tmp_path / "claude", tmp_path / "record.json", force=False, on_event=events.append
    )
    assert ok is False
    assert _stage_seq(events)[-1] == ("preflight", "failed")


def test_none_on_event_unchanged(tmp_path):
    record = install_shim_transaction(tmp_path / "claude", tmp_path / "state", dry_run=False)
    assert record.exists()
