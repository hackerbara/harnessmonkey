"""Install page: target picker (dropdown + Browse) and shim controls.

Follows `settings_window.py`'s rendering discipline: `install_target_choices`
and `InstallTargetSelection` (from `window_model.py`) decide the combo's
choices and the remembered user selection, and `install_plan_for_target`
(from `menubar_install.py`) decides the protected/user-writable status --
this page never re-derives that logic Qt-side. `install_button_enabled`/
`uninstall_button_enabled` (also `window_model.py`) likewise decide whether
the Install/Uninstall buttons are enabled, folding in `render`'s
`mutating_enabled` (from `window_model.mutating_controls_enabled`, via
`SettingsWindow.render`'s `busy_command`) so both buttons disable while a
Controller command is in flight, mirroring the tray's `TrayModel.
mutating_enabled`. The target combo/Browse never call the CLI themselves
(`set_install_target` is local selection state, applied on the next
install/uninstall), so they are not gated by busy-state.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from harnessmonkey.gui.pages.common import Banner
from harnessmonkey.gui.window_model import (
    InstallTargetChoice,
    InstallTargetSelection,
    abbreviate_home,
    install_button_enabled,
    install_target_choice_label,
    install_target_choices,
    uninstall_button_enabled,
)
from harnessmonkey.menubar_install import install_plan_for_target
from harnessmonkey.menubar_state import MenuState

BROWSE_LABEL = "Browse…"


class InstallPage(QWidget):
    """Install-target picker plus shim install/uninstall controls.

    Signals:
        action(str, dict): "set_install_target" (combo selection changed or
            "Browse…" picked a path -- payload is `{"path": str}`),
            "install_shim" / "uninstall_shim" (buttons clicked -- empty
            payload) -- bubbled through `SettingsWindow.action` by the
            caller.
    """

    action = Signal(str, dict)

    def __init__(self) -> None:
        super().__init__()
        self._state: MenuState | None = None
        self._selection = InstallTargetSelection()
        self._mutating_enabled: bool = True

        layout = QVBoxLayout(self)
        self.banner = Banner()
        layout.addWidget(self.banner)

        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._on_combo_index_changed)
        layout.addWidget(self.target_combo)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        self.shim_status_label = QLabel()
        layout.addWidget(self.shim_status_label)

        buttons_row = QHBoxLayout()
        self.install_button = QPushButton("Install")
        self.install_button.clicked.connect(lambda: self.action.emit("install_shim", {}))
        buttons_row.addWidget(self.install_button)
        self.uninstall_button = QPushButton("Uninstall")
        self.uninstall_button.clicked.connect(lambda: self.action.emit("uninstall_shim", {}))
        buttons_row.addWidget(self.uninstall_button)
        layout.addLayout(buttons_row)
        layout.addStretch(1)

        self.render(None)

    def render(self, state: MenuState | None, *, mutating_enabled: bool = True) -> None:
        self._state = state
        self._mutating_enabled = mutating_enabled
        if state is None:
            self.target_combo.blockSignals(True)
            self.target_combo.clear()
            self.target_combo.blockSignals(False)
            self.status_label.setText("")
            self.shim_status_label.setText("Not installed")
            self.install_button.setEnabled(False)
            self.uninstall_button.setEnabled(False)
            return

        choices = list(install_target_choices(state))
        current_target = self._selection.target(state)
        if current_target not in (choice.target for choice in choices):
            # An explicit user pick (combo selection or Browse…) is known
            # precisely -- render it plain, like the other detected entries,
            # never with a "standard location" guess suffix.
            choices.append(InstallTargetChoice(f"Use {current_target}", current_target, True))

        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for choice in choices:
            exists = None if choice.detected else choice.target.exists()
            label_text = install_target_choice_label(choice, exists=exists)
            self.target_combo.addItem(f"{label_text}: {choice.target}", choice.target)
        self.target_combo.addItem(BROWSE_LABEL, None)
        current_index = next(
            index for index, choice in enumerate(choices) if choice.target == current_target
        )
        self.target_combo.setCurrentIndex(current_index)
        self.target_combo.blockSignals(False)

        self._render_status(state, current_target)

        self.install_button.setEnabled(
            install_button_enabled(state, mutating_enabled=mutating_enabled)
        )
        self.uninstall_button.setEnabled(
            uninstall_button_enabled(state, mutating_enabled=mutating_enabled)
        )

    def _render_status(self, state: MenuState, target: Path) -> None:
        plan = install_plan_for_target(target, state_dir=state.state_dir)
        if plan.authorization_required:
            self.status_label.setText(f"{plan.target} (protected -- {plan.authorization_reason})")
        else:
            self.status_label.setText(f"{plan.target} (user-writable)")

        self.shim_status_label.setText(
            f"Installed at {abbreviate_home(state.shim_target_path)}"
            if state.shim_target_path
            else "Not installed"
        )

    def _on_combo_index_changed(self, index: int) -> None:
        if self._state is None or index < 0:
            return
        if self.target_combo.itemText(index) == BROWSE_LABEL:
            self._on_browse()
            return
        target = self.target_combo.itemData(index)
        if target is None:
            return
        self._selection.select(target)
        self.action.emit("set_install_target", {"path": str(target)})
        self.render(self._state, mutating_enabled=self._mutating_enabled)

    def _on_browse(self) -> None:
        # Deferred import to avoid a circular import with `gui/app.py` (see
        # `activate_app_for_window`'s docstring).
        from harnessmonkey.gui.app import activate_app_for_window

        activate_app_for_window()
        path, _selected_filter = QFileDialog.getSaveFileName(self, "Choose Install Target")
        if not path:
            # revert the combo off the transient "Browse…" row
            self.render(self._state, mutating_enabled=self._mutating_enabled)
            return
        target = Path(path).expanduser()
        self._selection.select(target)
        self.action.emit("set_install_target", {"path": str(target)})
        self.render(self._state, mutating_enabled=self._mutating_enabled)
