"""Prompts page: "none"-first radio-style list + add/remove controls.

Follows `settings_window.py`'s rendering discipline: `remove_enabled` (from
`window_model.py`) decides Remove-button enable/disable + refusal reason;
this page never re-derives that rule. `render`'s `mutating_enabled` (from
`window_model.mutating_controls_enabled`, via `SettingsWindow.render`'s
`busy_command`) additionally gates every mutating control here -- the
prompt-set list, Add, and Remove -- while a Controller command is in
flight, mirroring how the tray already gates on `TrayModel.
mutating_enabled`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from harnessmonkey.gui.pages.common import Banner, slugify
from harnessmonkey.gui.window_model import remove_enabled
from harnessmonkey.menubar_state import MenuState

PROMPT_ID_ROLE = Qt.ItemDataRole.UserRole
NONE_PROMPT_LABEL = "(none)"
ACTIVE_MARKER = "● "


class _AddPromptDialog(QDialog):
    """Collects an id (pre-slugged from the filename) and a name."""

    def __init__(self, parent: QWidget | None, *, default_id: str, default_name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Prompt")
        form = QFormLayout(self)
        self.id_edit = QLineEdit(default_id)
        self.name_edit = QLineEdit(default_name)
        form.addRow("Id:", self.id_edit)
        form.addRow("Name:", self.name_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def id_value(self) -> str:
        return self.id_edit.text().strip()

    def name_value(self) -> str:
        return self.name_edit.text().strip()


class PromptsPage(QWidget):
    """"none"-first prompt list, plus add/remove controls.

    Signals:
        action(str, dict): "set_prompt" (row clicked), "add_prompt_file"
            (add dialog accepted -- never followed by "set_prompt"),
            "remove_package" (Remove clicked) -- bubbled through
            `SettingsWindow.action` by the caller.
    """

    action = Signal(str, dict)

    def __init__(self) -> None:
        super().__init__()
        self._state: MenuState | None = None
        self._mutating_enabled: bool = True

        layout = QVBoxLayout(self)
        self.banner = Banner()
        layout.addWidget(self.banner)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.itemSelectionChanged.connect(self._update_remove_button)
        layout.addWidget(self.list, 1)

        buttons_row = QHBoxLayout()
        self.add_button = QPushButton("Add Prompt…")
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
        self.list.setEnabled(mutating_enabled)
        self.add_button.setEnabled(mutating_enabled)
        self.list.blockSignals(True)
        self.list.clear()
        if state is not None:
            none_item = QListWidgetItem(
                (ACTIVE_MARKER if state.active_prompt is None else "") + NONE_PROMPT_LABEL
            )
            none_item.setData(PROMPT_ID_ROLE, None)
            self.list.addItem(none_item)
            for prompt in state.prompt_items:
                text = prompt.label
                if prompt.source_path is not None:
                    text += f" — {prompt.source_path}"
                item = QListWidgetItem((ACTIVE_MARKER if prompt.checked else "") + text)
                item.setData(PROMPT_ID_ROLE, prompt.prompt_id)
                self.list.addItem(item)
        self.list.blockSignals(False)
        self._update_remove_button()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.action.emit("set_prompt", {"prompt_id": item.data(PROMPT_ID_ROLE)})

    def _selected_package_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        return item.data(PROMPT_ID_ROLE)

    def _update_remove_button(self) -> None:
        package_id = self._selected_package_id()
        if package_id is None or self._state is None:
            self.remove_button.setEnabled(False)
            self.remove_button.setToolTip("")
            return
        can_remove, reason = remove_enabled("prompt", package_id, self._state)
        self.remove_button.setEnabled(self._mutating_enabled and can_remove)
        self.remove_button.setToolTip("" if can_remove else reason)

    def _on_add_clicked(self) -> None:
        # Deferred import: `gui/app.py` imports `settings_window.py`, which
        # imports this page, so a module-level import here would be
        # circular -- see `activate_app_for_window`'s docstring for why
        # every window/dialog presentation needs this call.
        from harnessmonkey.gui.app import activate_app_for_window

        activate_app_for_window()
        path, _selected_filter = QFileDialog.getOpenFileName(self, "Add Prompt")
        if not path:
            return
        stem = Path(path).stem
        dialog = _AddPromptDialog(self, default_id=slugify(stem), default_name=stem)
        activate_app_for_window()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        package_id = dialog.id_value()
        if not package_id:
            return
        name = dialog.name_value()
        # Adding a prompt file never activates it -- no "set_prompt" here.
        self.action.emit(
            "add_prompt_file",
            {"path": path, "package_id": package_id, "name": name or None},
        )

    def _on_remove_clicked(self) -> None:
        package_id = self._selected_package_id()
        if package_id is None:
            return
        self.action.emit("remove_package", {"kind": "prompt", "package_id": package_id})
