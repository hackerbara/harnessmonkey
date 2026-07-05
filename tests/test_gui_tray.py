"""Tests for the tray renderer in harnessmonkey.gui.tray.

`Tray` makes no decisions of its own -- every visibility/enablement/label
choice must trace back directly to a `TrayModel` field or one of the
`window_model` helpers (`patch_item_enabled`, `option_item_enabled`,
`patch_menu_label`). These tests build `TrayModel` fixtures directly
(bypassing `MenuState`/`build_tray_model`) so each case is explicit about
which model field drives which rendered widget, and walk
`tray.menu.actions()` rather than requiring a visible/live system tray --
`QSystemTrayIcon` may report unavailable under `QT_QPA_PLATFORM=offscreen`,
so nothing here calls `.show()` or depends on `isSystemTrayAvailable()`.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction, QIcon  # noqa: E402
from PySide6.QtWidgets import QMenu  # noqa: E402

from harnessmonkey.gui.tray import Tray  # noqa: E402
from harnessmonkey.gui.window_model import NoticeModel, TrayModel  # noqa: E402
from harnessmonkey.menubar_state import OptionMenuItem, PatchMenuItem, PromptMenuItem  # noqa: E402


def _model(**overrides) -> TrayModel:
    defaults = dict(
        status_lines=("HarnessMonkey: OK", "Claude Code: 2.1.199"),
        running_label=None,
        mutating_enabled=True,
        show_install_shim=False,
        prompt_items=(PromptMenuItem("research", "Research", True, "append", None),),
        patch_items=(PatchMenuItem("p1", "Fable", True, True, True, "compatible", None),),
        option_items=(
            OptionMenuItem("o1", "Local proxy", False, True, "unconstrained", "low"),
        ),
    )
    defaults.update(overrides)
    return TrayModel(**defaults)


def _recorder():
    calls: list[tuple[str, dict]] = []

    def on_action(action_id: str, kwargs: dict) -> None:
        calls.append((action_id, kwargs))

    return calls, on_action


def _find_action(actions, text: str) -> QAction | None:
    for action in actions:
        if action.text() == text:
            return action
    return None


def _submenu(actions, text: str) -> QMenu:
    action = _find_action(actions, text)
    assert action is not None, f"no top-level action named {text!r}"
    menu = action.menu()
    assert menu is not None, f"{text!r} is not a submenu"
    return menu


# ---------------------------------------------------------------------------
# Status lines / running label
# ---------------------------------------------------------------------------


def test_status_lines_render_disabled(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    model = _model()
    tray.render(model)

    for line in model.status_lines:
        action = _find_action(tray.menu.actions(), line)
        assert action is not None, f"missing status line {line!r}"
        assert action.isEnabled() is False


def test_no_running_label_when_model_has_none(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model(running_label=None))

    assert _find_action(tray.menu.actions(), "Running: build") is None


# ---------------------------------------------------------------------------
# Install shim… visibility
# ---------------------------------------------------------------------------


def test_install_shim_shown_when_model_requests_it(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)

    tray.render(_model(show_install_shim=True))
    assert _find_action(tray.menu.actions(), "Install shim…") is not None

    tray.render(_model(show_install_shim=False))
    assert _find_action(tray.menu.actions(), "Install shim…") is None


def test_install_shim_triggers_on_action(qapp):
    calls, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model(show_install_shim=True))

    action = _find_action(tray.menu.actions(), "Install shim…")
    action.trigger()

    assert calls == [("install_shim", {})]


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------


def test_rebuild_action_triggers_on_action_with_no_kwargs(qapp):
    calls, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model())

    action = _find_action(tray.menu.actions(), "Rebuild / Apply…")
    assert action is not None
    action.trigger()

    assert calls == [("rebuild", {})]


# ---------------------------------------------------------------------------
# Pending-rebuild feedback (fix: "no feedback that we need to rebuild")
# ---------------------------------------------------------------------------


def test_no_rebuild_required_item_when_model_says_not_required(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model(rebuild_required=False))

    assert _find_action(tray.menu.actions(), "Rebuild to apply changes") is None


def test_rebuild_required_item_shown_and_triggers_rebuild(qapp):
    calls, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model(rebuild_required=True))

    action = _find_action(tray.menu.actions(), "Rebuild to apply changes")
    assert action is not None
    assert action.isEnabled() is True
    action.trigger()

    assert calls == [("rebuild", {})]


def test_rebuild_required_item_disabled_while_busy(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model(rebuild_required=True, mutating_enabled=False))

    action = _find_action(tray.menu.actions(), "Rebuild to apply changes")
    assert action is not None
    assert action.isEnabled() is False


def test_icon_variant_picks_pending_asset(qapp, monkeypatch):
    # `Tray.render` must ask `icons.tray_icon` for the model's chosen
    # variant on every render -- the decision itself (which variant) lives
    # in `window_model.tray_icon_variant`, this only checks the renderer
    # relays it through.
    import harnessmonkey.gui.tray as tray_module

    calls: list[str] = []

    def fake_tray_icon(variant: str = "normal") -> QIcon:
        calls.append(variant)
        return QIcon()

    monkeypatch.setattr(tray_module, "tray_icon", fake_tray_icon)
    tray = Tray(on_action=lambda *_: None)
    calls.clear()  # drop the __init__-time "normal" call

    tray.render(_model(icon_variant="pending"))
    assert calls == ["pending"]

    tray.render(_model(icon_variant="normal"))
    assert calls == ["pending", "normal"]


# ---------------------------------------------------------------------------
# Busy model
# ---------------------------------------------------------------------------


def test_busy_model_disables_submenus_and_shows_running_label(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    model = _model(mutating_enabled=False, running_label="Running: build")
    tray.render(model)

    running = _find_action(tray.menu.actions(), "Running: build")
    assert running is not None
    assert running.isEnabled() is False

    for label in ("Prompts", "Patches", "Options"):
        action = _find_action(tray.menu.actions(), label)
        assert action is not None, f"missing submenu {label!r}"
        assert action.isEnabled() is False


def test_not_busy_model_enables_submenus(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model(mutating_enabled=True))

    for label in ("Prompts", "Patches", "Options"):
        action = _find_action(tray.menu.actions(), label)
        assert action is not None
        assert action.isEnabled() is True


# ---------------------------------------------------------------------------
# Prompts submenu
# ---------------------------------------------------------------------------


def test_prompt_item_renders_checked_state_and_label(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model())

    prompts_menu = _submenu(tray.menu.actions(), "Prompts")
    item = _find_action(prompts_menu.actions(), "Research")
    assert item is not None
    assert item.isCheckable() is True
    assert item.isChecked() is True


def test_prompt_item_triggers_set_prompt_with_prompt_id(qapp):
    calls, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model())

    prompts_menu = _submenu(tray.menu.actions(), "Prompts")
    item = _find_action(prompts_menu.actions(), "Research")
    item.trigger()

    assert calls == [("set_prompt", {"prompt_id": "research"})]


# ---------------------------------------------------------------------------
# Patches submenu
# ---------------------------------------------------------------------------


def test_patch_label_uses_patch_menu_label_helper(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    incompatible = PatchMenuItem(
        "p2", "Fable", False, False, True, "version_mismatch", "targets 2.1.198"
    )
    tray.render(_model(patch_items=(incompatible,)))

    patches_menu = _submenu(tray.menu.actions(), "Patches")
    item = _find_action(patches_menu.actions(), "Fable — targets 2.1.198")
    assert item is not None


def test_patch_item_triggers_toggle_patch_with_current_state(qapp):
    calls, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model())

    patches_menu = _submenu(tray.menu.actions(), "Patches")
    item = _find_action(patches_menu.actions(), "Fable")
    item.trigger()

    assert calls == [("toggle_patch", {"patch_id": "p1", "enabled": True})]


def test_unavailable_patch_disabled_via_patch_item_enabled(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    unavailable = PatchMenuItem("p3", "Fable", False, False, False, "compatible", None)
    tray.render(_model(patch_items=(unavailable,)))

    patches_menu = _submenu(tray.menu.actions(), "Patches")
    item = _find_action(patches_menu.actions(), "Fable — unavailable")
    assert item is not None
    assert item.isEnabled() is False


# ---------------------------------------------------------------------------
# Options submenu
# ---------------------------------------------------------------------------


def test_option_item_triggers_toggle_option_with_requires_confirmation(qapp):
    calls, on_action = _recorder()
    tray = Tray(on_action=on_action)
    option = OptionMenuItem(
        "dangerous-permissions", "Dangerous permissions", True, True, "unconstrained", "high", True
    )
    tray.render(_model(option_items=(option,)))

    options_menu = _submenu(tray.menu.actions(), "Options")
    item = _find_action(options_menu.actions(), "Dangerous permissions")
    item.trigger()

    assert calls == [
        (
            "toggle_option",
            {"option_id": "dangerous-permissions", "enabled": True, "requires_confirmation": True},
        )
    ]


def test_invalid_option_disabled_via_option_item_enabled(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    option = OptionMenuItem("o2", "Broken option", False, False, "unconstrained", "low")
    tray.render(_model(option_items=(option,)))

    options_menu = _submenu(tray.menu.actions(), "Options")
    item = _find_action(options_menu.actions(), "Broken option")
    assert item is not None
    assert item.isEnabled() is False


# ---------------------------------------------------------------------------
# shim-update-resilience notice (spec sec4)
# ---------------------------------------------------------------------------


def test_no_notice_renders_no_extra_line_or_repair_action(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model(notice=None))

    assert _find_action(tray.menu.actions(), "Repair shim…") is None


def test_notice_message_renders_disabled_line(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    notice = NoticeModel(
        message="Claude 2.1.201 available — shim repair needed",
        digest="abcd1234",
        actions=("repair",),
    )
    tray.render(_model(notice=notice))

    action = _find_action(tray.menu.actions(), notice.message)
    assert action is not None
    assert action.isEnabled() is False


def test_notice_with_repair_action_shows_repair_menu_item(qapp):
    calls, on_action = _recorder()
    tray = Tray(on_action=on_action)
    notice = NoticeModel(message="repair needed", digest="abcd1234", actions=("repair",))
    tray.render(_model(notice=notice))

    action = _find_action(tray.menu.actions(), "Repair shim…")
    assert action is not None
    assert action.isEnabled() is True
    action.trigger()

    assert calls == [("repair_shim", {})]


def test_notice_without_repair_action_hides_repair_menu_item(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    notice = NoticeModel(message="rebuild to roll out", digest=None, actions=())
    tray.render(_model(notice=notice))

    assert _find_action(tray.menu.actions(), "Repair shim…") is None


def test_notice_repair_action_disabled_while_busy(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    notice = NoticeModel(message="repair needed", digest="abcd1234", actions=("repair",))
    tray.render(_model(notice=notice, mutating_enabled=False))

    action = _find_action(tray.menu.actions(), "Repair shim…")
    assert action is not None
    assert action.isEnabled() is False


# ---------------------------------------------------------------------------
# Remaining fixed actions
# ---------------------------------------------------------------------------


def test_open_window_refresh_and_quit_trigger_on_action(qapp):
    calls, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model())

    for label, action_id in (
        ("Open HarnessMonkey…", "open_window"),
        ("Refresh", "refresh"),
        ("Quit", "quit"),
    ):
        action = _find_action(tray.menu.actions(), label)
        assert action is not None, f"missing action {label!r}"
        action.trigger()
        assert calls[-1] == (action_id, {})


def test_render_is_idempotent_and_rebuildable(qapp):
    _, on_action = _recorder()
    tray = Tray(on_action=on_action)
    tray.render(_model())
    first_count = len(tray.menu.actions())
    tray.render(_model())

    assert len(tray.menu.actions()) == first_count
