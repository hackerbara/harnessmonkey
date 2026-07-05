"""Tests for the HarnessMonkey v3 progress dialog (Task 15).

`ProgressDialog` is a thin Qt renderer over `ProgressModel` (Task 10): the
model owns every piece of stage/status interpretation (row statuses, stage
dedup, resolve-stuck-rows-on-result); this dialog only renders whatever the
model exposes. Tests here therefore drive the dialog through the same
event/result protocol the model already tests against
(`tests/test_gui_progress_model.py`) rather than asserting on any particular
stage message string, which is not a stable contract.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402

from harnessmonkey.gui.progress_dialog import ProgressDialog  # noqa: E402

PLAN = {
    "event": "plan",
    "stages": [
        {"id": "a", "label": "A"},
        {"id": "b", "label": "B"},
        {"id": "swap", "label": "Swap"},
    ],
}


def _dialog(qtbot, **overrides):
    kwargs = dict(
        title="Rebuild",
        confirm_text="This will apply 2 patches.",
        confirm_button="Rebuild",
        cancel_allowed_during_run=True,
    )
    kwargs.update(overrides)
    dialog = ProgressDialog(**kwargs)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_confirm_phase_shows_confirm_text(qtbot):
    dialog = _dialog(qtbot, confirm_text="Dry run: 3 files changed.")
    assert "Dry run: 3 files changed." in dialog.confirm_label.text()
    assert dialog.confirm_button.text() == "Rebuild"


def test_confirm_button_click_emits_confirmed(qtbot):
    dialog = _dialog(qtbot)
    with qtbot.waitSignal(dialog.confirmed, timeout=1000):
        qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)


def test_cancel_button_click_emits_cancel_requested(qtbot):
    dialog = _dialog(qtbot)
    with qtbot.waitSignal(dialog.cancel_requested, timeout=1000):
        qtbot.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)


def test_running_phase_renders_rows_with_status_prefixes(qtbot):
    dialog = _dialog(qtbot)
    dialog.start_running()
    dialog.apply_event(PLAN)
    dialog.apply_event({"event": "stage", "id": "a", "status": "done"})
    dialog.apply_event({"event": "stage", "id": "b", "status": "running"})
    dialog.apply_event({"event": "stage", "id": "swap", "status": "failed", "message": "boom"})

    assert dialog.stage_list.count() == 3
    assert dialog.stage_list.item(0).text().startswith("✔")  # done
    assert dialog.stage_list.item(1).text().startswith("⟳")  # running
    assert dialog.stage_list.item(2).text().startswith("✖")  # failed
    assert "boom" in dialog.stage_list.item(2).text()


def test_swap_stage_running_disables_cancel(qtbot):
    dialog = _dialog(qtbot, cancel_allowed_during_run=True)
    dialog.start_running()
    dialog.apply_event(PLAN)
    assert dialog.cancel_button.isEnabled()
    dialog.apply_event({"event": "stage", "id": "swap", "status": "running"})
    assert not dialog.cancel_button.isEnabled()


def test_cancel_hidden_entirely_when_not_allowed_during_run(qtbot):
    dialog = _dialog(qtbot, cancel_allowed_during_run=False)
    dialog.start_running()
    assert not dialog.cancel_button.isVisible()


def test_finish_failure_shows_summary_and_open_logs_button(qtbot):
    dialog = _dialog(qtbot)
    dialog.start_running()
    dialog.apply_event(PLAN)
    dialog.apply_event({"event": "stage", "id": "a", "status": "failed", "message": "build broke"})
    dialog.finish({"ok": False, "summary": "failed"}, report_path=None, logs_dir="/tmp/logs")

    assert "build broke" in dialog.summary_label.text()
    assert dialog.open_logs_button.isVisible()
    assert not dialog.open_report_button.isVisible()


def test_finish_success_with_report_path_shows_open_report_button(qtbot):
    dialog = _dialog(qtbot)
    dialog.start_running()
    dialog.apply_event(PLAN)
    dialog.apply_event({"event": "stage", "id": "a", "status": "done"})
    dialog.finish(
        {"ok": True, "summary": "built"}, report_path="/tmp/report.json", logs_dir="/tmp/logs"
    )

    assert dialog.open_report_button.isVisible()


def test_open_report_button_emits_open_path_requested(qtbot):
    dialog = _dialog(qtbot)
    dialog.start_running()
    dialog.finish(
        {"ok": True, "summary": "built"}, report_path="/tmp/report.json", logs_dir="/tmp/logs"
    )
    with qtbot.waitSignal(dialog.open_path_requested, timeout=1000) as blocker:
        qtbot.mouseClick(dialog.open_report_button, Qt.MouseButton.LeftButton)
    assert blocker.args == ["/tmp/report.json"]


def test_open_logs_button_emits_open_path_requested(qtbot):
    dialog = _dialog(qtbot)
    dialog.start_running()
    dialog.finish({"ok": True, "summary": "built"}, report_path=None, logs_dir="/tmp/logs")
    with qtbot.waitSignal(dialog.open_path_requested, timeout=1000) as blocker:
        qtbot.mouseClick(dialog.open_logs_button, Qt.MouseButton.LeftButton)
    assert blocker.args == ["/tmp/logs"]


def test_close_blocked_during_running_when_cancel_not_allowed(qtbot):
    dialog = _dialog(qtbot, cancel_allowed_during_run=False)
    dialog.start_running()
    dialog.close()
    assert dialog.isVisible()


def test_close_allowed_during_running_when_cancel_allowed(qtbot):
    dialog = _dialog(qtbot, cancel_allowed_during_run=True)
    dialog.start_running()
    dialog.close()
    assert not dialog.isVisible()


def test_details_toggle_shows_log_pane(qtbot):
    dialog = _dialog(qtbot)
    dialog.start_running()
    dialog.apply_event({"event": "log", "stage": None, "line": "hello"})
    assert not dialog.log_view.isVisible()
    dialog.details_button.setChecked(True)
    assert dialog.log_view.isVisible()
    assert "hello" in dialog.log_view.toPlainText()
