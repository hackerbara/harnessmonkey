"""HarnessMonkey v3 manager window: sidebar navigation + stacked pages.

Discipline (see `docs/superpowers/specs/2026-07-03-harnessmonkey-v3-gui-design.md`):
this file only *renders*. Every piece of business logic -- status
normalization, compatibility rules, enable/disable rules, label
formatting for status/version/prompt/patches -- already lives in
`menubar_state.py` / `gui/window_model.py`. `SettingsWindow.render()` reads
those view-models and pushes strings into widgets; it never re-derives
them.

Overview, Logs & Reports, Patches, Prompts, Options, and Install all have
real content now. Patches/Prompts/Options/Install pages live in
`gui/pages/` (moved out of this file once real content pushed it past the
~500-line split threshold noted in the GUI plan); this module re-exports
them for convenience.

Closing the window never quits the app -- it only hides, per the plan's
"tray keeps running" requirement; the singleton window is re-shown by the
tray's "Open HarnessMonkey..." action (a later task).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from harnessmonkey.gui.pages.common import Banner as _Banner
from harnessmonkey.gui.pages.install_page import InstallPage
from harnessmonkey.gui.pages.options_page import OptionsPage
from harnessmonkey.gui.pages.patches_page import PatchesPage
from harnessmonkey.gui.pages.prompts_page import PromptsPage
from harnessmonkey.gui.window_model import (
    NoticeModel,
    build_summary_label_text,
    build_tray_model,
    mutating_controls_enabled,
    notice_dismiss_key,
    patch_set_label_text,
    rebuild_button_enabled,
)
from harnessmonkey.menubar_state import MenuState

__all__ = [
    "SettingsWindow",
    "OverviewPage",
    "LogsPage",
    "PatchesPage",
    "PromptsPage",
    "OptionsPage",
    "InstallPage",
]

MAX_LOG_TAIL_LINES = 200
LOG_FILE_NAME = "menubar.log"  # historical name, kept for continuity -- see design doc.

# (page key used by show_banner/render, sidebar display label)
SIDEBAR_PAGES: tuple[tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("patches", "Patches"),
    ("prompts", "Prompts"),
    ("options", "Options"),
    ("install", "Install"),
    ("logs", "Logs & Reports"),
)


def _tail_lines(path: Path, max_lines: int = MAX_LOG_TAIL_LINES) -> str:
    """Return up to `max_lines` trailing lines of `path` as a single string.

    A missing log file is expected (nothing has run yet) rather than an
    error condition, so it renders a friendly placeholder instead of
    raising.
    """
    if not path.exists():
        return "(no log file yet)"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"(could not read log: {exc})"
    return "\n".join(lines[-max_lines:])


class OverviewPage(QWidget):
    """Status/version/prompt/patch-set summary, high-risk warnings, rebuild."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.banner = _Banner()
        layout.addWidget(self.banner)

        # shim-update-resilience notice (spec sec4/sec5, R2/R5): a plain
        # message line plus two optional buttons, all hidden until
        # `render_notice` supplies a `NoticeModel`. `notice_repair_button`
        # only shows when the model's `actions` includes "repair" (R2:
        # never automatic); `notice_dismiss_button` only shows when the
        # notice carries a digest to dismiss by (R5).
        self._notice: NoticeModel | None = None
        notice_row = QHBoxLayout()
        self.notice_label = QLabel()
        self.notice_label.setWordWrap(True)
        self.notice_label.hide()
        notice_row.addWidget(self.notice_label, 1)
        self.notice_repair_button = QPushButton("Repair shim…")
        self.notice_repair_button.hide()
        notice_row.addWidget(self.notice_repair_button)
        self.notice_dismiss_button = QPushButton("Dismiss")
        self.notice_dismiss_button.hide()
        notice_row.addWidget(self.notice_dismiss_button)
        layout.addLayout(notice_row)

        self.status_label = QLabel()
        self.version_label = QLabel()
        self.prompt_label = QLabel()
        self.options_label = QLabel()
        self.patches_label = QLabel()
        self.patch_set_label = QLabel()
        for label in (
            self.status_label,
            self.version_label,
            self.prompt_label,
            self.options_label,
            self.patches_label,
            self.patch_set_label,
        ):
            layout.addWidget(label)

        layout.addWidget(QLabel("High-risk option warnings:"))
        self.high_risk_list = QListWidget()
        layout.addWidget(self.high_risk_list)

        self.rebuild_button = QPushButton("Rebuild / Apply")
        layout.addWidget(self.rebuild_button)

        self.build_summary_label = QLabel()
        layout.addWidget(self.build_summary_label)
        self.open_report_button = QPushButton("Open report")
        layout.addWidget(self.open_report_button)
        layout.addStretch(1)

        self.report_path: Path | None = None
        self.render(None)

    def render(self, state: MenuState | None, *, mutating_enabled: bool = True) -> None:
        if state is None:
            for label in (
                self.status_label,
                self.version_label,
                self.prompt_label,
                self.options_label,
                self.patches_label,
                self.patch_set_label,
                self.build_summary_label,
            ):
                label.setText("")
            self.high_risk_list.clear()
            self.rebuild_button.setEnabled(False)
            self.open_report_button.setEnabled(False)
            self.report_path = None
            return

        # Status/version/prompt/options/patches lines are the exact strings
        # window_model already computes for the tray -- reused verbatim so
        # this page never re-derives the "N active", "⚠" suffix, etc. logic.
        model = build_tray_model(state, busy_command=None)
        self.status_label.setText(model.status_lines[0])
        self.version_label.setText(model.status_lines[1])
        self.prompt_label.setText(model.status_lines[2])
        self.options_label.setText(model.status_lines[3])
        self.patches_label.setText(model.status_lines[4])
        self.patch_set_label.setText(patch_set_label_text(state))

        self.high_risk_list.clear()
        self.high_risk_list.addItems(list(state.high_risk_warnings))

        self.rebuild_button.setEnabled(
            rebuild_button_enabled(state, mutating_enabled=mutating_enabled)
        )

        self.build_summary_label.setText(build_summary_label_text(state))
        self.report_path = state.latest_build_report_path
        self.open_report_button.setEnabled(self.report_path is not None)

    def render_notice(self, notice: NoticeModel | None, *, mutating_enabled: bool = True) -> None:
        self._notice = notice
        if notice is None:
            self.notice_label.hide()
            self.notice_repair_button.hide()
            self.notice_dismiss_button.hide()
            return
        self.notice_label.setText(notice.message)
        self.notice_label.show()
        self.notice_repair_button.setVisible("repair" in notice.actions)
        # `repair_shim` is a mutating CLI command (see `Controller.
        # _action_repair_shim`), so it disables while busy exactly like the
        # rebuild button -- `notice_dismiss_button` is pure Controller state
        # (no CLI call), so it stays live regardless.
        self.notice_repair_button.setEnabled(mutating_enabled)
        # Every notice is dismissable now, regardless of whether it carries a
        # real `digest` -- `notice_dismiss_key`/`_emit_dismiss_notice` supply
        # a sentinel key for the digest-less case (see `NoticeModel.digest`'s
        # docstring), so there is no longer a "no digest -> no Dismiss
        # button" gap.
        self.notice_dismiss_button.setVisible(True)


class LogsPage(QWidget):
    """Three "open" buttons plus a read-only tail of menubar.log."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.banner = _Banner()
        layout.addWidget(self.banner)

        buttons_row = QHBoxLayout()
        self.open_report_button = QPushButton("Open report")
        self.open_logs_folder_button = QPushButton("Open logs folder")
        self.open_state_folder_button = QPushButton("Open state folder")
        for button in (
            self.open_report_button,
            self.open_logs_folder_button,
            self.open_state_folder_button,
        ):
            buttons_row.addWidget(button)
        layout.addLayout(buttons_row)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, 1)

        self.report_path: Path | None = None
        self.logs_dir: Path | None = None
        self.state_dir: Path | None = None
        self.render(None)

    def render(self, state: MenuState | None, *, mutating_enabled: bool = True) -> None:
        # `mutating_enabled` is accepted for signature parity with every
        # other page (`SettingsWindow.render` calls all pages uniformly),
        # but unused here: opening a report/logs/state folder is never a
        # mutating CLI command, so this page has nothing to gate on busy.
        del mutating_enabled
        if state is None:
            self.report_path = None
            self.logs_dir = None
            self.state_dir = None
            self.open_report_button.setEnabled(False)
            self.open_logs_folder_button.setEnabled(False)
            self.open_state_folder_button.setEnabled(False)
            self.log_view.setPlainText("")
            return

        self.report_path = state.latest_build_report_path
        self.logs_dir = state.logs_dir
        self.state_dir = state.state_dir
        self.open_report_button.setEnabled(self.report_path is not None)
        self.open_logs_folder_button.setEnabled(True)
        self.open_state_folder_button.setEnabled(True)
        self.log_view.setPlainText(_tail_lines(state.logs_dir / LOG_FILE_NAME))


class SettingsWindow(QMainWindow):
    """Singleton manager window: sidebar navigation over stacked pages.

    Signals:
        action(str, dict): a user-triggered command intent, using the same
            action-id vocabulary as the tray, plus window-only ids
            ("uninstall_shim", "add_package", "remove_package",
            "add_prompt_file", "set_install_target", "open_path"). Overview
            emits "rebuild"/"open_path"; Logs & Reports emits "open_path";
            Patches/Prompts/Options/Install (their own page-local `action`
            signals, bubbled through this one) emit "toggle_patch"/
            "toggle_option"/"set_prompt"/"add_package"/"add_prompt_file"/
            "remove_package"/"install_shim"/"uninstall_shim"/
            "set_install_target".
        refresh_requested(): emitted by the disconnected-state Retry button.
    """

    action = Signal(str, dict)
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HarnessMonkey")

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        self.disconnected_banner = QLabel(
            "Disconnected from HarnessMonkey -- state could not be read."
        )
        self.disconnected_banner.setStyleSheet("color: #a00; font-weight: bold;")
        self.disconnected_banner.hide()
        outer.addWidget(self.disconnected_banner)

        self.retry_button = QPushButton("Retry")
        self.retry_button.hide()
        self.retry_button.clicked.connect(self.refresh_requested.emit)
        outer.addWidget(self.retry_button)

        body = QHBoxLayout()
        outer.addLayout(body, 1)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(160)
        for _key, label in SIDEBAR_PAGES:
            QListWidgetItem(label, self.sidebar)
        body.addWidget(self.sidebar)

        self.overview_page = OverviewPage()
        self.patches_page = PatchesPage()
        self.prompts_page = PromptsPage()
        self.options_page = OptionsPage()
        self.install_page = InstallPage()
        self.logs_page = LogsPage()

        self._pages_by_key: dict[str, QWidget] = {
            "overview": self.overview_page,
            "patches": self.patches_page,
            "prompts": self.prompts_page,
            "options": self.options_page,
            "install": self.install_page,
            "logs": self.logs_page,
        }

        self.stack = QStackedWidget()
        for _key, _label in SIDEBAR_PAGES:
            self.stack.addWidget(self._pages_by_key[_key])
        body.addWidget(self.stack, 1)

        self.sidebar.setCurrentRow(0)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

        self._banners: dict[str, _Banner] = {
            key: page.banner for key, page in self._pages_by_key.items()
        }

        self.overview_page.rebuild_button.clicked.connect(lambda: self.action.emit("rebuild", {}))
        self.overview_page.open_report_button.clicked.connect(
            lambda: self._emit_open_path(self.overview_page.report_path)
        )
        self.overview_page.notice_repair_button.clicked.connect(
            lambda: self.action.emit("repair_shim", {})
        )
        self.overview_page.notice_dismiss_button.clicked.connect(self._emit_dismiss_notice)
        self.logs_page.open_report_button.clicked.connect(
            lambda: self._emit_open_path(self.logs_page.report_path)
        )
        self.logs_page.open_logs_folder_button.clicked.connect(
            lambda: self._emit_open_path(self.logs_page.logs_dir)
        )
        self.logs_page.open_state_folder_button.clicked.connect(
            lambda: self._emit_open_path(self.logs_page.state_dir)
        )

        # Patches/Prompts/Options/Install each own a small `action` signal;
        # bubble every emission straight through this window's `action`
        # signal.
        self.patches_page.action.connect(self.action.emit)
        self.prompts_page.action.connect(self.action.emit)
        self.options_page.action.connect(self.action.emit)
        self.install_page.action.connect(self.action.emit)

    def render(self, state: MenuState | None, busy_command: str | None = None) -> None:
        """Repopulate every page from `state`; `None` shows a disconnected banner.

        `busy_command` mirrors `Controller._busy_command` -- the exact value
        `build_tray_model` already reads to compute `TrayModel.
        mutating_enabled` for the tray. `window_model.mutating_controls_enabled`
        turns it into the single `mutating_enabled` flag threaded into every
        page's `render()`, so every mutating control (patch/option checkboxes,
        add/remove buttons, the prompt-set list, install/uninstall buttons,
        the rebuild button) disables while a command is in flight exactly
        like the tray already does -- pages only consume the flag, they never
        decide busy-ness themselves. Non-mutating controls (sidebar
        navigation, log viewing, quit) never consult it.
        """
        if state is None:
            self.disconnected_banner.show()
            self.retry_button.show()
        else:
            self.disconnected_banner.hide()
            self.retry_button.hide()

        mutating_enabled = mutating_controls_enabled(busy_command)
        for page in self._pages_by_key.values():
            page.render(state, mutating_enabled=mutating_enabled)

    def show_banner(self, page: str, message: str) -> None:
        """Show a dismissible inline error banner on `page` (a sidebar key)."""
        banner = self._banners.get(page)
        if banner is None:
            raise ValueError(f"unknown settings page: {page!r}")
        banner.show_message(message)

    def render_notice(self, notice: NoticeModel | None, busy_command: str | None = None) -> None:
        """Render the shim-update-resilience notice (spec sec4) on Overview.

        Controller calls this alongside `render(state)` (both from
        `refresh()` and from `_action_dismiss_notice`) with the output of
        `window_model.build_notice_model` -- this method never re-derives
        that decision, only pushes the already-decided model into the page.
        `busy_command` is the same value fed to `render()`/`build_tray_model`
        -- it decides whether the notice's "Repair shim..." button (a
        mutating command) is enabled, via `mutating_controls_enabled`.
        """
        self.overview_page.render_notice(
            notice, mutating_enabled=mutating_controls_enabled(busy_command)
        )

    def _emit_dismiss_notice(self) -> None:
        notice = self.overview_page._notice
        key = notice_dismiss_key(notice) if notice is not None else None
        self.action.emit("dismiss_notice", {"digest": key})

    def _emit_open_path(self, path: Path | None) -> None:
        """Emit `open_path` for `path`, or do nothing if it's not set yet.

        Shared by the Overview "Open report" button and all three Logs &
        Reports buttons ("Open report"/"Open logs folder"/"Open state
        folder") -- they only differ in which page attribute supplies the
        path, so the emit itself is a single place.
        """
        if path is not None:
            self.action.emit("open_path", {"path": str(path)})

    def closeEvent(self, event: QCloseEvent) -> None:
        """Never quit the app on close -- just hide (tray keeps it alive)."""
        event.ignore()
        self.hide()
