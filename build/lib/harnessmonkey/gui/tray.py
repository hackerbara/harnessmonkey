"""Qt tray renderer for the HarnessMonkey v3 GUI.

`Tray` is a thin renderer over `TrayModel` (`window_model.py`, Task 9): it
owns the `QSystemTrayIcon`/`QMenu` widgets and the single dispatcher that
funnels every menu action to the caller's `on_action` callback, but it makes
no decisions of its own. Every piece of rendered state -- which lines show,
which submenus/items are enabled, which labels are used, whether "Install
shim…" appears at all -- is read directly off the `TrayModel` passed to
`render()`, or from the pure helper functions in `window_model.py`
(`patch_menu_label`, `patch_item_enabled`, `option_item_enabled`) that
already encapsulate those decisions. Task 19 is responsible for
constructing this against a live `CommandRunner`/`CommandBridge` and wiring
`on_action` to actually run commands.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from harnessmonkey.gui.icons import tray_icon
from harnessmonkey.gui.window_model import (
    TrayModel,
    option_item_enabled,
    patch_item_enabled,
    patch_menu_label,
)

ActionCallback = Callable[[str, dict[str, Any]], None]


class Tray(QObject):
    """Owns the tray icon/menu and dispatches every action to `on_action`."""

    def __init__(self, *, on_action: ActionCallback) -> None:
        super().__init__()
        self.on_action = on_action
        self.menu = QMenu()
        self.icon = QSystemTrayIcon(tray_icon())
        self.icon.setContextMenu(self.menu)

    def render(self, model: TrayModel) -> None:
        self.icon.setIcon(tray_icon(model.icon_variant))
        self.menu.clear()

        for line in model.status_lines:
            self._add_action(self.menu, line, enabled=False)
        if model.running_label is not None:
            self._add_action(self.menu, model.running_label, enabled=False)
        self._add_notice(model)
        if model.rebuild_required:
            # Pending-rebuild feedback: a directly-clickable, prominently
            # labeled entry near the top of the menu, distinct from the
            # always-present "Rebuild / Apply…" item further down -- both
            # emit the same "rebuild" action id.
            self._add_action(
                self.menu,
                "Rebuild to apply changes",
                action_id="rebuild",
                enabled=model.mutating_enabled,
            )
        self.menu.addSeparator()

        self._add_action(self.menu, "Open HarnessMonkey…", action_id="open_window")
        self.menu.addSeparator()

        self._add_items_submenu(
            model,
            title="Prompts",
            items=model.prompt_items,
            action_id="set_prompt",
            label_fn=lambda prompt: prompt.label,
            kwargs_fn=lambda prompt: {"prompt_id": prompt.prompt_id},
            enabled_fn=lambda _prompt: model.mutating_enabled,
            checked_fn=lambda prompt: prompt.checked,
        )
        self._add_items_submenu(
            model,
            title="Patches",
            items=model.patch_items,
            action_id="toggle_patch",
            label_fn=patch_menu_label,
            kwargs_fn=lambda patch: {"patch_id": patch.patch_id, "enabled": patch.checked},
            enabled_fn=lambda patch: patch_item_enabled(
                patch, mutating_enabled=model.mutating_enabled
            ),
            checked_fn=lambda patch: patch.checked,
        )
        self._add_items_submenu(
            model,
            title="Options",
            items=model.option_items,
            action_id="toggle_option",
            label_fn=lambda option: option.label,
            kwargs_fn=lambda option: {
                "option_id": option.option_id,
                "enabled": option.enabled,
                "requires_confirmation": option.requires_confirmation,
            },
            enabled_fn=lambda option: option_item_enabled(
                option, mutating_enabled=model.mutating_enabled
            ),
            checked_fn=lambda option: option.enabled,
        )

        self.menu.addSeparator()
        self._add_action(
            self.menu,
            "Rebuild / Apply…",
            action_id="rebuild",
            enabled=model.mutating_enabled,
        )
        if model.show_install_shim:
            self._add_action(
                self.menu,
                "Install shim…",
                action_id="install_shim",
                enabled=model.mutating_enabled,
            )

        self.menu.addSeparator()
        self._add_action(self.menu, "Refresh", action_id="refresh")
        self._add_action(self.menu, "Quit", action_id="quit")

    def _add_notice(self, model: TrayModel) -> None:
        """Render the shim-update-resilience notice (spec sec4), if any.

        Every piece of this comes straight off `model.notice`
        (`window_model.build_notice_model`'s output) -- the message line is
        always shown, disabled, purely informational; "Repair shim…" only
        appears when `"repair"` is in `notice.actions` (R2: never an
        automatic action, always a user-triggered button), matching how
        `render()` already gates "Install shim…" on `show_install_shim`.
        """
        notice = model.notice
        if notice is None:
            return
        self._add_action(self.menu, notice.message, enabled=False)
        if "repair" in notice.actions:
            self._add_action(
                self.menu,
                "Repair shim…",
                action_id="repair_shim",
                enabled=model.mutating_enabled,
            )

    def _add_items_submenu(
        self,
        model: TrayModel,
        *,
        title: str,
        items: Sequence[Any],
        action_id: str,
        label_fn: Callable[[Any], str],
        kwargs_fn: Callable[[Any], dict[str, Any]],
        enabled_fn: Callable[[Any], bool],
        checked_fn: Callable[[Any], bool],
    ) -> None:
        """Build one checkable submenu (Prompts/Patches/Options), item-by-item.

        The three real submenus only differ in the title, the item
        collection, the emitted action id, and how each item's
        label/kwargs/enabled/checked are derived -- this parameterizes that
        shape once instead of near-duplicating the same loop three times.
        """
        submenu = self.menu.addMenu(title)
        submenu.menuAction().setEnabled(model.mutating_enabled)
        for item in items:
            self._add_action(
                submenu,
                label_fn(item),
                action_id=action_id,
                kwargs=kwargs_fn(item),
                enabled=enabled_fn(item),
                checkable=True,
                checked=checked_fn(item),
            )

    def _add_action(
        self,
        menu: QMenu,
        label: str,
        *,
        action_id: str | None = None,
        kwargs: dict[str, Any] | None = None,
        enabled: bool = True,
        checkable: bool = False,
        checked: bool = False,
    ) -> QAction:
        action = menu.addAction(label)
        action.setEnabled(enabled)
        if checkable:
            action.setCheckable(True)
            action.setChecked(checked)
        if action_id is not None:
            action.setData((action_id, kwargs or {}))
            action.triggered.connect(self._on_triggered)
        return action

    def _on_triggered(self) -> None:
        action = self.sender()
        if action is None:
            return
        data = action.data()
        if not data:
            return
        action_id, kwargs = data
        self.on_action(action_id, kwargs)
