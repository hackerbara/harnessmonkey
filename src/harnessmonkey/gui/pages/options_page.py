"""Options page: checkbox|label|risk|notes|compatibility table + add/remove.

Follows `settings_window.py`'s rendering discipline: `option_item_enabled`
(row enable/disable), `option_notes` (Notes column text), and
`remove_enabled` (Remove-button enable/disable + refusal reason) are read
from `window_model.py`, never re-derived here. Toggling a checkbox always
emits the same `requires_confirmation` shape the tray already uses (see
`Tray._add_items_submenu`'s "Options" call) -- this page never shows its
own confirm dialog; `Controller` (`gui/app.py`) is the sole place that ever
confirms a high-risk enable (Item 1's unified high-risk-option confirm
dialog), and it corrects any checkbox Qt already flipped on a decline by
re-rendering from the true `MenuState` (`Controller.refresh()`), not by
this page reverting its own widget state. `render`'s
`mutating_enabled` (from `window_model.mutating_controls_enabled`, via
`SettingsWindow.render`'s `busy_command`) additionally gates every mutating
control here -- rows, Add, and Remove -- while a Controller command is in
flight, mirroring how the tray already gates on `TrayModel.
mutating_enabled`.

The checkbox, Risk, and (usually-blank) Compatibility columns are sized to
their contents; Option/Notes share the remaining width (`Stretch`), so the
table uses the page width sensibly instead of truncating the name column
("options should be wide"). A `PendingRebuildBanner` above the table
surfaces `MenuState.rebuild_required` (the "no feedback that we need to
rebuild to apply" fix).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from harnessmonkey.gui.pages.common import Banner, PendingRebuildBanner
from harnessmonkey.gui.window_model import (
    compatibility_display,
    option_item_enabled,
    option_notes,
    rebuild_pending_banner_visible,
    remove_enabled,
)
from harnessmonkey.menubar_state import MenuState, OptionMenuItem

COLUMN_LABELS = ("", "Option", "Risk", "Notes", "Compatibility")
CHECKBOX_COLUMN = 0
NAME_COLUMN = 1
RISK_COLUMN = 2
NOTES_COLUMN = 3
COMPATIBILITY_COLUMN = 4
OPTION_ID_ROLE = Qt.ItemDataRole.UserRole
HIGH_RISK_COLOR = QColor("#a00")


class OptionsPage(QWidget):
    """Table of installed option packages, plus add/remove controls.

    Signals:
        action(str, dict): "toggle_option" (checkbox toggled -- always
            carries "requires_confirmation", mirroring tray's kwargs shape;
            `Controller` alone decides whether/how to confirm), "add_package"
            (folder picked), "remove_package" (Remove clicked) -- bubbled
            through `SettingsWindow.action` by the caller.
    """

    action = Signal(str, dict)

    def __init__(self) -> None:
        super().__init__()
        self._state: MenuState | None = None
        self._mutating_enabled: bool = True

        layout = QVBoxLayout(self)
        self.banner = Banner()
        layout.addWidget(self.banner)
        self.pending_rebuild_banner = PendingRebuildBanner()
        self.pending_rebuild_banner.rebuild_requested.connect(
            lambda: self.action.emit("rebuild", {})
        )
        layout.addWidget(self.pending_rebuild_banner)

        self.table = QTableWidget(0, len(COLUMN_LABELS))
        self.table.setHorizontalHeaderLabels(COLUMN_LABELS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._update_remove_button)
        # Size columns to use the page width sensibly ("options should be
        # wide"): checkbox/Risk/(usually-blank) Compatibility shrink to fit
        # contents, Option/Notes share the remaining width.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(CHECKBOX_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(RISK_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COMPATIBILITY_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons_row = QHBoxLayout()
        self.add_button = QPushButton("Add Option Package…")
        self.add_button.clicked.connect(self._on_add_clicked)
        buttons_row.addWidget(self.add_button)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._on_remove_clicked)
        buttons_row.addWidget(self.remove_button)
        layout.addLayout(buttons_row)

        self.render(None)

    def render(self, state: MenuState | None, *, mutating_enabled: bool = True) -> None:
        self._state = state
        self._mutating_enabled = mutating_enabled
        self.add_button.setEnabled(mutating_enabled)
        self.pending_rebuild_banner.render(
            visible=rebuild_pending_banner_visible(state), mutating_enabled=mutating_enabled
        )
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        if state is not None:
            self.table.setRowCount(len(state.option_items))
            for row, option in enumerate(state.option_items):
                self._render_row(row, option)
        self.table.blockSignals(False)
        self._update_remove_button()

    def _render_row(self, row: int, option: OptionMenuItem) -> None:
        row_enabled = option_item_enabled(option, mutating_enabled=self._mutating_enabled)
        cell_flags = Qt.ItemFlag.ItemIsSelectable
        if row_enabled:
            cell_flags |= Qt.ItemFlag.ItemIsEnabled

        checkbox_item = QTableWidgetItem()
        checkbox_item.setFlags(cell_flags | Qt.ItemFlag.ItemIsUserCheckable)
        checkbox_item.setCheckState(
            Qt.CheckState.Checked if option.enabled else Qt.CheckState.Unchecked
        )
        checkbox_item.setData(OPTION_ID_ROLE, option.option_id)
        self.table.setItem(row, CHECKBOX_COLUMN, checkbox_item)

        label_item = QTableWidgetItem(option.label)
        label_item.setFlags(cell_flags)
        self.table.setItem(row, NAME_COLUMN, label_item)

        risk_item = QTableWidgetItem(option.risk_level)
        risk_item.setFlags(cell_flags)
        if option.risk_level == "high":
            risk_item.setForeground(HIGH_RISK_COLOR)
        self.table.setItem(row, RISK_COLUMN, risk_item)

        notes_item = QTableWidgetItem(option_notes(option))
        notes_item.setFlags(cell_flags)
        self.table.setItem(row, NOTES_COLUMN, notes_item)

        compat_item = QTableWidgetItem(compatibility_display(option.compatibility_status))
        compat_item.setFlags(cell_flags)
        self.table.setItem(row, COMPATIBILITY_COLUMN, compat_item)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != CHECKBOX_COLUMN or self._state is None:
            return
        option = self._option_by_id(item.data(OPTION_ID_ROLE))
        if option is None:
            return

        # `enabled` reports the option's CURRENT (pre-toggle) state, matching
        # `command_for_option_toggle`'s enable/disable direction convention.
        # `requires_confirmation` mirrors tray's kwargs shape exactly (see
        # `Tray._add_items_submenu`'s "Options" call) -- Controller alone
        # decides whether/how to confirm now (Item 1's unified high-risk
        # confirm dialog); this page never shows its own QMessageBox, and a
        # decline is corrected by `Controller.refresh()` re-rendering from
        # the true `MenuState`, not by this page reverting its own checkbox.
        self.action.emit(
            "toggle_option",
            {
                "option_id": option.option_id,
                "enabled": option.enabled,
                "requires_confirmation": option.requires_confirmation,
            },
        )

    def _option_by_id(self, option_id: object) -> OptionMenuItem | None:
        if self._state is None:
            return None
        return next((o for o in self._state.option_items if o.option_id == option_id), None)

    def _selected_option(self) -> OptionMenuItem | None:
        if self._state is None:
            return None
        row = self.table.currentRow()
        if row < 0 or row >= len(self._state.option_items):
            return None
        return self._state.option_items[row]

    def _update_remove_button(self) -> None:
        option = self._selected_option()
        if option is None or self._state is None:
            self.remove_button.setEnabled(False)
            self.remove_button.setToolTip("")
            return
        can_remove, reason = remove_enabled("option", option.option_id, self._state)
        self.remove_button.setEnabled(self._mutating_enabled and can_remove)
        self.remove_button.setToolTip("" if can_remove else reason)

    def _on_add_clicked(self) -> None:
        # Deferred import to avoid a circular import with `gui/app.py` (see
        # `activate_app_for_window`'s docstring).
        from harnessmonkey.gui.app import activate_app_for_window

        activate_app_for_window()
        path = QFileDialog.getExistingDirectory(self, "Add Option Package")
        if not path:
            return
        self.action.emit("add_package", {"kind": "option", "path": path})

    def _on_remove_clicked(self) -> None:
        option = self._selected_option()
        if option is None:
            return
        self.action.emit("remove_package", {"kind": "option", "package_id": option.option_id})
