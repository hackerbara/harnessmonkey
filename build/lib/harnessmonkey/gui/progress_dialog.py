"""Qt confirm/progress/result dialog for the HarnessMonkey v3 GUI.

`ProgressDialog` is a thin renderer over `ProgressModel`
(`gui/progress_model.py`, Task 10): the model owns every piece of stage
interpretation (row statuses, stage dedup, resolving stuck rows on the
final result); this dialog only pushes the model's rows/log lines into
widgets. It never re-implements stage-state logic itself -- per the GUI
plan's discipline, view-models decide and Qt renders.

Stage messages are not a stable contract (the CLI producer side is a
subprocess speaking a drifting JSON protocol) -- this file renders whatever
`ProgressModel` exposes and never string-matches on message content.

Three phases, one dialog instance:
  CONFIRM -> shows the caller-supplied summary text with
      "[confirm_button] [Cancel]".
  RUNNING -> (entered via `start_running()`) a stage checklist fed by
      `apply_event()`, a collapsible log pane, and a Cancel button that is
      hidden outright when the caller disallows cancelling mid-run, or
      otherwise disabled while the "swap" stage is running (that stage
      is the point of no return -- see the design doc).
  RESULT -> (entered via `finish()`) a summary label and
      "[Open report] [Open logs] [Close]", built from the final payload
      plus whatever state `ProgressModel` ended up in -- not every stage is
      assumed to have reached a terminal status (a command can die
      mid-stage; `ProgressModel.apply_result` already reconciles that).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent, QColor, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from harnessmonkey.gui.progress_model import ProgressModel

# Row-status -> checklist prefix. Keys mirror `StageRow.status` in
# `progress_model.py`; an unrecognized/absent status renders as pending
# rather than raising, matching the model's own defensive posture.
_STATUS_PREFIX = {
    "done": "✔",  # done
    "running": "⟳",  # running
    "failed": "✖",  # failed
    "skipped": "–",  # skipped
    "pending": "○",  # pending
}

# The stage id that marks the point of no return: once it starts running,
# Cancel is disabled (though never hidden by this alone -- that's driven by
# `cancel_allowed_during_run`).
_POINT_OF_NO_RETURN_STAGE_ID = "swap"


class ProgressDialog(QDialog):
    """CONFIRM/RUNNING/RESULT dialog driven by `ProgressModel`.

    Signals:
        confirmed(): the CONFIRM-phase confirm button was clicked.
        cancel_requested(): the Cancel button was clicked (CONFIRM or
            RUNNING phase).
        open_path_requested(str): an "Open report"/"Open logs" button was
            clicked in the RESULT phase, carrying the path to open.
    """

    confirmed = Signal()
    cancel_requested = Signal()
    open_path_requested = Signal(str)

    def __init__(
        self,
        *,
        title: str,
        confirm_text: str,
        confirm_button: str,
        cancel_allowed_during_run: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._cancel_allowed_during_run = cancel_allowed_during_run
        self._phase = "CONFIRM"
        self._report_path: str | None = None
        self._logs_dir: str | None = None

        self.model = ProgressModel()

        outer = QVBoxLayout(self)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        self._confirm_page = self._build_confirm_page(confirm_text)
        self._running_page = self._build_running_page()
        self._result_page = self._build_result_page()
        for page in (self._confirm_page, self._running_page, self._result_page):
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(self._confirm_page)

        self._bottom_bar = QWidget()
        bottom_row = QHBoxLayout(self._bottom_bar)
        bottom_row.setContentsMargins(0, 0, 0, 0)
        self.confirm_button = QPushButton(confirm_button)
        self.cancel_button = QPushButton("Cancel")
        bottom_row.addWidget(self.confirm_button)
        bottom_row.addWidget(self.cancel_button)
        outer.addWidget(self._bottom_bar)

        self.confirm_button.clicked.connect(self.confirmed.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

        # Default palette snapshot so a failure's red summary text can be
        # reverted to normal if the dialog is ever reused for a success.
        self._default_summary_palette = QPalette(self.summary_label.palette())

    # -- page construction -------------------------------------------------

    def _build_confirm_page(self, confirm_text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.confirm_label = QLabel(confirm_text)
        self.confirm_label.setWordWrap(True)
        layout.addWidget(self.confirm_label)
        return page

    def _build_running_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.stage_list = QListWidget()
        layout.addWidget(self.stage_list, 1)

        self.details_button = QToolButton()
        self.details_button.setText("Details")
        self.details_button.setCheckable(True)
        self.details_button.setChecked(False)
        self.details_button.toggled.connect(self._on_details_toggled)
        layout.addWidget(self.details_button)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.hide()  # collapsed by default
        layout.addWidget(self.log_view, 1)

        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        buttons = QHBoxLayout()
        self.open_report_button = QPushButton("Open report")
        self.open_logs_button = QPushButton("Open logs")
        self.close_button = QPushButton("Close")
        for button in (self.open_report_button, self.open_logs_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.open_report_button.clicked.connect(self._open_report)
        self.open_logs_button.clicked.connect(self._open_logs)
        self.close_button.clicked.connect(self.close)

        return page

    # -- phase transitions ---------------------------------------------------

    def start_running(self) -> None:
        """Move from CONFIRM to RUNNING: show the stage checklist."""
        self._phase = "RUNNING"
        self._stack.setCurrentWidget(self._running_page)
        self.confirm_button.hide()
        self._sync_cancel_button()

    def apply_event(self, event: dict) -> None:
        """Feed one progress event to `ProgressModel` and re-render.

        Interpretation of the event (row statuses, stage dedup, message
        hygiene) is entirely `ProgressModel`'s job -- this only re-renders
        whatever the model ends up with afterwards.
        """
        self.model.apply_event(event)
        self._render_rows()
        self._sync_cancel_button()

    def finish(self, payload: dict, *, report_path: str | None, logs_dir: str) -> None:
        """Move to RESULT from the terminal `payload` plus model state.

        Not every stage is assumed to have reached "done"/"failed" --
        `ProgressModel.apply_result` already reconciles rows left stuck at
        "running" (dropped terminal event on success, or a process dying
        mid-stage on failure), so rendering after this call reflects that
        reconciled state rather than raw, possibly-incomplete rows.
        """
        self.model.apply_result(payload)
        self._render_rows()

        self._phase = "RESULT"
        self._report_path = report_path
        self._logs_dir = logs_dir

        self._stack.setCurrentWidget(self._result_page)
        self._bottom_bar.hide()

        ok = bool(payload.get("ok")) if isinstance(payload, dict) else False
        summary = payload.get("summary") if isinstance(payload, dict) else None
        if ok:
            self.summary_label.setPalette(self._default_summary_palette)
            self.summary_label.setText(summary or "Completed successfully.")
        else:
            failed_row = next((row for row in self.model.rows if row.status == "failed"), None)
            failed_message = failed_row.message if failed_row is not None else None
            self.summary_label.setText(failed_message or summary or "Failed.")
            palette = QPalette(self.summary_label.palette())
            palette.setColor(QPalette.ColorRole.WindowText, QColor("red"))
            self.summary_label.setPalette(palette)

        self.open_report_button.setVisible(report_path is not None)
        self.open_logs_button.setVisible(True)

    # -- rendering helpers ---------------------------------------------------

    def _render_rows(self) -> None:
        self.stage_list.clear()
        for row in self.model.rows:
            prefix = _STATUS_PREFIX.get(row.status, _STATUS_PREFIX["pending"])
            text = f"{prefix} {row.label}"
            if row.message:
                text += f" — {row.message}"
            QListWidgetItem(text, self.stage_list)
        self.log_view.setPlainText("\n".join(self.model.log_lines))

    def _sync_cancel_button(self) -> None:
        if not self._cancel_allowed_during_run:
            self.cancel_button.hide()
            return
        self.cancel_button.show()
        swap_row = next(
            (row for row in self.model.rows if row.stage_id == _POINT_OF_NO_RETURN_STAGE_ID),
            None,
        )
        swap_running = swap_row is not None and swap_row.status == "running"
        self.cancel_button.setEnabled(not swap_running)

    def _on_details_toggled(self, checked: bool) -> None:
        self.log_view.setVisible(checked)

    def _open_report(self) -> None:
        if self._report_path is not None:
            self.open_path_requested.emit(self._report_path)

    def _open_logs(self) -> None:
        if self._logs_dir is not None:
            self.open_path_requested.emit(self._logs_dir)

    # -- lifecycle -----------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Block closing while RUNNING unless the caller allows cancelling."""
        if self._phase == "RUNNING" and not self._cancel_allowed_during_run:
            event.ignore()
            return
        super().closeEvent(event)
