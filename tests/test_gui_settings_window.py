"""Tests for the HarnessMonkey v3 settings window (Task 16).

`SettingsWindow` is the Qt manager window skeleton: a sidebar + stacked
pages, with real content on Overview and Logs & Reports; Patches, Prompts,
Options, and Install are empty placeholders filled in by later tasks
(17/18). Per the GUI plan's discipline, this file only renders
`MenuState`/`window_model` view-models -- it must not re-derive any
business logic (compatibility, enable rules, status normalization) that
already lives in `menubar_state.py` / `gui/window_model.py`.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox  # noqa: E402

import harnessmonkey.gui.app as app_module  # noqa: E402
from harnessmonkey.gui.settings_window import SettingsWindow  # noqa: E402
from harnessmonkey.gui.window_model import NoticeModel  # noqa: E402
from harnessmonkey.menubar_state import (  # noqa: E402
    HighRiskOptionSummary,
    MenuState,
    OptionMenuItem,
    PatchMenuItem,
    PromptMenuItem,
)

SIDEBAR_LABELS = ("Overview", "Patches", "Prompts", "Options", "Install", "Logs & Reports")


def _state(tmp_path: Path, **overrides) -> MenuState:
    defaults = dict(
        status="ok",
        status_label="OK",
        source_claude_version="2.1.199",
        source_claude_path=None,
        detected_claude_command_path=None,
        install_mode="shim",
        shim_installed=True,
        active_profile="default",
        active_prompt="research",
        desired_patch_ids=("p1",),
        active_patch_ids=("p1",),
        rebuild_required=False,
        latest_build_report_path=tmp_path / "report.json",
        active_patch_set="everyday",
        current_claude_path=None,
        shim_target_path=None,
        install_record_path=None,
        last_build_strategy="repack",
        changed_modules=({"id": "m1"}, {"id": "m2"}),
        repack_summary=None,
        state_dir=tmp_path,
        logs_dir=tmp_path / "logs",
        last_error=None,
        patch_items=(PatchMenuItem("p1", "Fable", True, True, True, "compatible", None),),
        prompt_items=(
            PromptMenuItem("research", "Research", True, "append", tmp_path / "research.md"),
        ),
        active_option_ids=("dangerous-permissions",),
        high_risk_options=(
            HighRiskOptionSummary(
                "dangerous-permissions", "Dangerous permissions", "This is risky."
            ),
        ),
        high_risk_warnings=("This is risky.",),
        option_items=(
            OptionMenuItem(
                "dangerous-permissions",
                "Dangerous permissions",
                True,
                True,
                "unconstrained",
                "high",
                True,
            ),
        ),
    )
    defaults.update(overrides)
    return MenuState(**defaults)


@pytest.fixture
def fake_state(tmp_path: Path) -> MenuState:
    return _state(tmp_path)


def test_sidebar_has_six_entries(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)

    assert window.sidebar.count() == 6
    labels = [window.sidebar.item(i).text() for i in range(window.sidebar.count())]
    assert labels == list(SIDEBAR_LABELS)


def test_render_fake_state_fills_overview(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(fake_state)

    assert "HarnessMonkey: OK" in window.overview_page.status_label.text()
    assert "2.1.199" in window.overview_page.version_label.text()
    assert "research" in window.overview_page.prompt_label.text()
    assert "everyday" in window.overview_page.patch_set_label.text()
    assert window.overview_page.high_risk_list.count() == 1
    assert window.overview_page.high_risk_list.item(0).text() == "This is risky."
    assert window.overview_page.rebuild_button.isEnabled() is True
    assert window.overview_page.open_report_button.isEnabled() is True
    assert window.disconnected_banner.isVisible() is False


def test_render_none_shows_disconnected_banner_and_retry_emits_refresh(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    window.render(None)

    assert window.disconnected_banner.isVisible() is True
    assert window.retry_button.isVisible() is True

    with qtbot.waitSignal(window.refresh_requested, timeout=1000):
        qtbot.mouseClick(window.retry_button, Qt.MouseButton.LeftButton)


def test_rebuild_button_emits_action(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    window.render(fake_state)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.overview_page.rebuild_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["rebuild", {}]


def test_open_report_button_emits_open_path_action(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    window.render(fake_state)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.overview_page.open_report_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["open_path", {"path": str(fake_state.latest_build_report_path)}]


# ---------------------------------------------------------------------------
# shim-update-resilience notice (spec sec4/sec5, R2/R5)
# ---------------------------------------------------------------------------


def test_notice_hidden_by_default(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)

    assert window.overview_page.notice_label.isVisible() is False
    assert window.overview_page.notice_repair_button.isVisible() is False
    assert window.overview_page.notice_dismiss_button.isVisible() is False


def test_render_notice_shows_message_and_repair_button(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    notice = NoticeModel(
        message="Claude 2.1.201 available — shim repair needed",
        digest="abcd1234",
        actions=("repair",),
    )

    window.render_notice(notice)

    assert window.overview_page.notice_label.isVisible() is True
    assert notice.message in window.overview_page.notice_label.text()
    assert window.overview_page.notice_repair_button.isVisible() is True
    assert window.overview_page.notice_dismiss_button.isVisible() is True


def test_render_notice_hides_repair_button_when_no_repair_action(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    notice = NoticeModel(message="rebuild to roll out", digest=None, actions=())

    window.render_notice(notice)

    assert window.overview_page.notice_label.isVisible() is True
    assert window.overview_page.notice_repair_button.isVisible() is False
    # Every notice is dismissable now, even a digest-less one (see
    # window_model.notice_dismiss_key) -- there is no longer a "no digest ->
    # no way to dismiss" gap.
    assert window.overview_page.notice_dismiss_button.isVisible() is True


def test_render_notice_none_hides_everything(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render_notice(
        NoticeModel(message="repair needed", digest="abcd1234", actions=("repair",))
    )

    window.render_notice(None)

    assert window.overview_page.notice_label.isVisible() is False
    assert window.overview_page.notice_repair_button.isVisible() is False
    assert window.overview_page.notice_dismiss_button.isVisible() is False


def test_notice_repair_button_emits_repair_shim_action(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    window.render_notice(
        NoticeModel(message="repair needed", digest="abcd1234", actions=("repair",))
    )

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(
            window.overview_page.notice_repair_button, Qt.MouseButton.LeftButton
        )

    assert blocker.args == ["repair_shim", {}]


def test_notice_dismiss_button_emits_dismiss_notice_with_digest(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    window.render_notice(
        NoticeModel(message="repair needed", digest="abcd1234", actions=("repair",))
    )

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(
            window.overview_page.notice_dismiss_button, Qt.MouseButton.LeftButton
        )

    assert blocker.args == ["dismiss_notice", {"digest": "abcd1234"}]


def test_notice_dismiss_button_emits_sentinel_key_for_digest_less_notice(qtbot):
    # A digest-less notice (see NoticeModel.digest's docstring) must still be
    # dismissable -- clicking Dismiss emits window_model's shared sentinel
    # key rather than a raw `None` (which `Controller._action_dismiss_notice`
    # would treat as falsy and silently do nothing with).
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    window.render_notice(NoticeModel(message="rebuild to roll out", digest=None, actions=()))

    assert window.overview_page.notice_dismiss_button.isVisible() is True
    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(
            window.overview_page.notice_dismiss_button, Qt.MouseButton.LeftButton
        )

    action_id, payload = blocker.args
    assert action_id == "dismiss_notice"
    assert payload["digest"]  # truthy sentinel, not None -- see app.py's dismiss handler


def test_close_hides_instead_of_destroying(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.isVisible() is True
    window.close()

    assert window.isVisible() is False
    # Object must still be alive: further attribute access must not raise.
    assert window.sidebar.count() == 6


def test_show_banner_is_dismissible(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    window.show_banner("overview", "Something went wrong.")
    banner = window._banners["overview"]
    assert banner.isVisible() is True
    assert "Something went wrong." in banner.label.text()

    qtbot.mouseClick(banner.dismiss_button, Qt.MouseButton.LeftButton)
    assert banner.isVisible() is False


def test_show_banner_rejects_unknown_page(qtbot):
    window = SettingsWindow()
    qtbot.addWidget(window)

    with pytest.raises(ValueError):
        window.show_banner("no-such-page", "boom")


def test_placeholder_pages_render_without_crashing(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(fake_state)
    window.render(None)
    window.render(fake_state)  # renders must be idempotent/repeatable


def test_logs_page_tails_menubar_log(qtbot, tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_path = logs_dir / "menubar.log"
    lines = [f"line-{i}" for i in range(250)]
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    state = _state(tmp_path, logs_dir=logs_dir)

    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    text = window.logs_page.log_view.toPlainText()
    assert "line-249" in text
    assert "line-0" not in text  # only the last 200 lines are kept
    assert text.count("\n") == 199  # 200 lines -> 199 newlines


def test_logs_page_open_buttons_emit_open_path(qtbot, tmp_path):
    state = _state(tmp_path)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    window.render(state)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.logs_page.open_logs_folder_button, Qt.MouseButton.LeftButton)
    assert blocker.args == ["open_path", {"path": str(state.logs_dir)}]

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.logs_page.open_state_folder_button, Qt.MouseButton.LeftButton)
    assert blocker.args == ["open_path", {"path": str(state.state_dir)}]

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.logs_page.open_report_button, Qt.MouseButton.LeftButton)
    assert blocker.args == ["open_path", {"path": str(state.latest_build_report_path)}]


def test_logs_page_missing_log_file_is_handled(qtbot, tmp_path):
    state = _state(tmp_path, logs_dir=tmp_path / "no-such-logs-dir")
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)  # must not raise

    assert window.logs_page.log_view.toPlainText() != ""


# --- Patches page (Task 17) --------------------------------------------


def test_patches_toggle_emits_toggle_patch_action(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    checkbox_item = window.patches_page.table.item(0, 0)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        checkbox_item.setCheckState(Qt.CheckState.Unchecked)

    assert blocker.args == ["toggle_patch", {"patch_id": "p1", "enabled": True}]


def test_patches_incompatible_row_is_disabled(qtbot, tmp_path):
    state = _state(
        tmp_path,
        patch_items=(
            PatchMenuItem("p2", "Broken", False, False, True, "incompatible", "needs v16"),
        ),
    )
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    checkbox_item = window.patches_page.table.item(0, 0)
    assert not (checkbox_item.flags() & Qt.ItemFlag.ItemIsEnabled)


def test_patches_compatibility_column_hides_internal_status_words(qtbot, tmp_path):
    # "unconstrained"/"compatible" are internal jargon (Task: hide compat
    # status vocabulary) -- the column must show nothing for healthy rows
    # and short human text (never the raw status word) for problem rows.
    state = _state(
        tmp_path,
        patch_items=(
            PatchMenuItem("p1", "Fable", True, True, True, "unconstrained", None),
            PatchMenuItem("p2", "Compat", True, True, True, "compatible", None),
            PatchMenuItem(
                "p3", "Broken", False, False, True, "version_mismatch", "targets 2.1.198"
            ),
            PatchMenuItem("p4", "NoMessage", False, False, True, "sha_mismatch", None),
        ),
    )
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    table = window.patches_page.table
    compat_col = 3
    assert table.item(0, compat_col).text() == ""
    assert table.item(1, compat_col).text() == ""
    assert table.item(2, compat_col).text() == "targets 2.1.198"
    assert table.item(3, compat_col).text() == "Not compatible with this Claude version"
    for row in range(table.rowCount()):
        text = table.item(row, compat_col).text()
        assert text not in {"unconstrained", "compatible", "version_mismatch", "sha_mismatch"}


def test_patches_notes_column_shows_errors(qtbot, tmp_path):
    state = _state(
        tmp_path,
        patch_items=(
            PatchMenuItem("p1", "Fable", True, True, True, "unconstrained", None),
            PatchMenuItem(
                "p2",
                "Broken",
                False,
                False,
                False,
                "unknown",
                None,
                errors=("id_must_match_folder: different != p2",),
            ),
        ),
    )
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    table = window.patches_page.table
    notes_col = 2
    assert table.item(0, notes_col).text() == ""
    assert table.item(1, notes_col).text() == "id_must_match_folder: different != p2"


def test_patches_add_package_emits_action(qtbot, monkeypatch, fake_state, tmp_path):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    fake_dir = str(tmp_path / "new-patch")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: fake_dir)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.patches_page.add_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["add_package", {"kind": "patch", "path": fake_dir}]


def test_patches_add_activates_app_before_file_dialog(qtbot, monkeypatch, fake_state, tmp_path):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    calls: list[str] = []
    monkeypatch.setattr(
        app_module, "activate_app_for_window", lambda: calls.append("activate_app")
    )
    fake_dir = str(tmp_path / "new-patch")

    def fake_get_existing_directory(*_args, **_kwargs):
        calls.append("dialog")
        return fake_dir

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake_get_existing_directory)

    qtbot.mouseClick(window.patches_page.add_button, Qt.MouseButton.LeftButton)

    assert calls == ["activate_app", "dialog"]


def test_patches_remove_button_disabled_with_reason_tooltip(qtbot, fake_state):
    # Default fake_state has desired_patch_ids=("p1",) -- p1 is referenced by
    # the active profile, so remove_enabled refuses it.
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    window.patches_page.table.setCurrentCell(0, 0)

    assert window.patches_page.remove_button.isEnabled() is False
    assert "p1" in window.patches_page.remove_button.toolTip()


def test_patches_remove_button_enabled_when_not_referenced(qtbot, tmp_path):
    state = _state(tmp_path, desired_patch_ids=())
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    window.patches_page.table.setCurrentCell(0, 0)

    assert window.patches_page.remove_button.isEnabled() is True
    assert window.patches_page.remove_button.toolTip() == ""


def test_patches_remove_click_emits_action(qtbot, tmp_path):
    state = _state(tmp_path, desired_patch_ids=())
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)
    window.patches_page.table.setCurrentCell(0, 0)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.patches_page.remove_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["remove_package", {"kind": "patch", "package_id": "p1"}]


def test_patches_pending_rebuild_banner_hidden_when_not_required(qtbot, tmp_path):
    state = _state(tmp_path, rebuild_required=False)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    assert window.patches_page.pending_rebuild_banner.isVisible() is False


def test_patches_pending_rebuild_banner_shown_when_required(qtbot, tmp_path):
    state = _state(tmp_path, rebuild_required=True)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    window.stack.setCurrentWidget(window.patches_page)  # non-current pages report isVisible=False

    window.render(state)

    banner = window.patches_page.pending_rebuild_banner
    assert banner.isVisible() is True
    assert "rebuild" in banner.label.text().lower()


def test_patches_pending_rebuild_banner_button_emits_rebuild(qtbot, tmp_path):
    state = _state(tmp_path, rebuild_required=True)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(
            window.patches_page.pending_rebuild_banner.rebuild_button, Qt.MouseButton.LeftButton
        )

    assert blocker.args == ["rebuild", {}]


# --- Prompts page (Task 17) ---------------------------------------------


def test_prompts_click_emits_set_prompt(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    list_widget = window.prompts_page.list
    item = list_widget.item(1)  # row 0 is "(none)"
    rect = list_widget.visualItemRect(item)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(list_widget.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    assert blocker.args == ["set_prompt", {"prompt_id": "research"}]


def test_prompts_click_none_emits_set_prompt_with_none(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    list_widget = window.prompts_page.list
    item = list_widget.item(0)  # "(none)" row
    rect = list_widget.visualItemRect(item)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(list_widget.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    assert blocker.args == ["set_prompt", {"prompt_id": None}]


def test_add_prompt_emits_add_prompt_file_and_never_set_prompt(
    qtbot, monkeypatch, fake_state, tmp_path
):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    fake_path = str(tmp_path / "My Research Notes.md")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (fake_path, ""))
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    seen: list[tuple[str, dict]] = []
    window.action.connect(lambda action_id, payload: seen.append((action_id, payload)))

    qtbot.mouseClick(window.prompts_page.add_button, Qt.MouseButton.LeftButton)

    assert seen == [
        (
            "add_prompt_file",
            {
                "path": fake_path,
                "package_id": "my-research-notes",
                "name": "My Research Notes",
            },
        )
    ]


def test_add_prompt_activates_app_before_file_dialog_and_before_dialog_exec(
    qtbot, monkeypatch, fake_state, tmp_path
):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    calls: list[str] = []
    monkeypatch.setattr(
        app_module, "activate_app_for_window", lambda: calls.append("activate_app")
    )
    fake_path = str(tmp_path / "My Research Notes.md")

    def fake_get_open_file_name(*_args, **_kwargs):
        calls.append("file_dialog")
        return (fake_path, "")

    def fake_exec(self):
        calls.append("dialog_exec")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_get_open_file_name)
    monkeypatch.setattr(QDialog, "exec", fake_exec)

    qtbot.mouseClick(window.prompts_page.add_button, Qt.MouseButton.LeftButton)

    assert calls == ["activate_app", "file_dialog", "activate_app", "dialog_exec"]


def test_add_prompt_cancelled_file_picker_emits_nothing(qtbot, monkeypatch, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))

    seen: list[tuple[str, dict]] = []
    window.action.connect(lambda action_id, payload: seen.append((action_id, payload)))

    qtbot.mouseClick(window.prompts_page.add_button, Qt.MouseButton.LeftButton)

    assert seen == []


def test_prompts_remove_button_disabled_with_reason_tooltip(qtbot, fake_state):
    # Default fake_state has active_prompt="research" -- referenced, refused.
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    window.prompts_page.list.setCurrentRow(1)  # "research" row

    assert window.prompts_page.remove_button.isEnabled() is False
    assert "research" in window.prompts_page.remove_button.toolTip()


def test_prompts_remove_button_disabled_for_none_row(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    window.prompts_page.list.setCurrentRow(0)  # "(none)" row -- no package id

    assert window.prompts_page.remove_button.isEnabled() is False


# --- Options page (Task 17) ---------------------------------------------


def _high_risk_state(tmp_path: Path, *, enabled: bool) -> MenuState:
    return _state(
        tmp_path,
        active_option_ids=("dangerous-permissions",) if enabled else (),
        option_items=(
            OptionMenuItem(
                "dangerous-permissions",
                "Dangerous permissions",
                enabled,
                True,
                "unconstrained",
                "high",
                True,
            ),
        ),
        high_risk_options=(
            HighRiskOptionSummary(
                "dangerous-permissions", "Dangerous permissions", "This is risky."
            ),
        ),
        high_risk_warnings=("This is risky.",) if enabled else (),
    )


def test_high_risk_option_toggle_on_emits_requires_confirmation_without_dialog(
    qtbot, monkeypatch, tmp_path
):
    # Item 1 (unified high-risk confirm dialog): OptionsPage no longer shows
    # its own QMessageBox at all -- it emits the same requires_confirmation
    # shape the tray already uses, and Controller (gui/app.py) is the sole
    # place that ever confirms. See tests/test_gui_controller.py's
    # toggle_option tests for the Controller-side confirm/decline coverage,
    # and test_default_confirm_high_risk_activates_app_before_message_box in
    # tests/test_gui_app.py for the activate-before-QMessageBox coverage
    # (both now live at the Controller level, not the page level).
    state = _high_risk_state(tmp_path, enabled=False)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("OptionsPage must not call QMessageBox.question itself")

    monkeypatch.setattr(QMessageBox, "question", fail_if_called)

    checkbox_item = window.options_page.table.item(0, 0)
    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        checkbox_item.setCheckState(Qt.CheckState.Checked)

    assert blocker.args == [
        "toggle_option",
        {
            "option_id": "dangerous-permissions",
            "enabled": False,
            "requires_confirmation": True,
        },
    ]


def test_low_risk_option_toggle_emits_action_without_confirm_dialog(qtbot, monkeypatch, tmp_path):
    state = _state(
        tmp_path,
        option_items=(
            OptionMenuItem("safe-thing", "Safe thing", True, True, "compatible", "low", False),
        ),
    )
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("QMessageBox.question must not be called for non-confirm options")

    monkeypatch.setattr(QMessageBox, "question", fail_if_called)

    checkbox_item = window.options_page.table.item(0, 0)
    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        checkbox_item.setCheckState(Qt.CheckState.Unchecked)

    assert blocker.args == [
        "toggle_option",
        {"option_id": "safe-thing", "enabled": True, "requires_confirmation": False},
    ]


def test_disabling_high_risk_option_skips_confirm_dialog(qtbot, monkeypatch, tmp_path):
    # requires_confirmation only gates ENABLING; an already-enabled high-risk
    # option must be disable-able without a confirm dialog.
    state = _high_risk_state(tmp_path, enabled=True)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("QMessageBox.question must not be called when disabling")

    monkeypatch.setattr(QMessageBox, "question", fail_if_called)

    checkbox_item = window.options_page.table.item(0, 0)
    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        checkbox_item.setCheckState(Qt.CheckState.Unchecked)

    assert blocker.args == [
        "toggle_option",
        {"option_id": "dangerous-permissions", "enabled": True, "requires_confirmation": True},
    ]


def test_options_remove_button_disabled_with_reason_tooltip(qtbot, fake_state):
    # Default fake_state has active_option_ids=("dangerous-permissions",).
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    window.options_page.table.setCurrentCell(0, 0)

    assert window.options_page.remove_button.isEnabled() is False
    assert "dangerous-permissions" in window.options_page.remove_button.toolTip()


def test_options_add_activates_app_before_file_dialog(qtbot, monkeypatch, fake_state, tmp_path):
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(fake_state)

    calls: list[str] = []
    monkeypatch.setattr(
        app_module, "activate_app_for_window", lambda: calls.append("activate_app")
    )
    fake_dir = str(tmp_path / "new-option")

    def fake_get_existing_directory(*_args, **_kwargs):
        calls.append("dialog")
        return fake_dir

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake_get_existing_directory)

    qtbot.mouseClick(window.options_page.add_button, Qt.MouseButton.LeftButton)

    assert calls == ["activate_app", "dialog"]


def test_options_compatibility_column_hides_internal_status_words(qtbot, tmp_path):
    # Same contract as the Patches page: "unconstrained"/"constrained" are
    # internal jargon and must never render verbatim in the Compatibility
    # column.
    state = _state(
        tmp_path,
        option_items=(
            OptionMenuItem("o1", "Local proxy", True, True, "unconstrained", "low"),
            OptionMenuItem("o2", "Constrained thing", True, True, "constrained", "low"),
        ),
    )
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    table = window.options_page.table
    compat_col = 4
    assert table.item(0, compat_col).text() == ""
    for row in range(table.rowCount()):
        assert table.item(row, compat_col).text() not in {"unconstrained", "constrained"}


def test_options_notes_column_shows_status_warning(qtbot, tmp_path):
    state = _state(
        tmp_path,
        option_items=(
            OptionMenuItem("o1", "Local proxy", True, True, "unconstrained", "low"),
            OptionMenuItem(
                "dangerous-permissions",
                "Dangerous permissions",
                True,
                True,
                "unconstrained",
                "high",
                True,
                (),
                "Dangerous permissions enabled",
            ),
        ),
    )
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    table = window.options_page.table
    notes_col = 3
    assert table.item(0, notes_col).text() == ""
    assert table.item(1, notes_col).text() == "Dangerous permissions enabled"


def test_options_pending_rebuild_banner_hidden_when_not_required(qtbot, tmp_path):
    state = _state(tmp_path, rebuild_required=False)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    assert window.options_page.pending_rebuild_banner.isVisible() is False


def test_options_pending_rebuild_banner_shown_when_required(qtbot, tmp_path):
    state = _state(tmp_path, rebuild_required=True)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()
    window.stack.setCurrentWidget(window.options_page)  # non-current pages report isVisible=False

    window.render(state)

    banner = window.options_page.pending_rebuild_banner
    assert banner.isVisible() is True
    assert "rebuild" in banner.label.text().lower()


def test_options_pending_rebuild_banner_button_emits_rebuild(qtbot, tmp_path):
    state = _state(tmp_path, rebuild_required=True)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(
            window.options_page.pending_rebuild_banner.rebuild_button, Qt.MouseButton.LeftButton
        )

    assert blocker.args == ["rebuild", {}]


def test_options_pending_rebuild_banner_button_disabled_while_busy(qtbot, tmp_path):
    state = _state(tmp_path, rebuild_required=True)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state, busy_command="toggle_option")

    assert window.options_page.pending_rebuild_banner.rebuild_button.isEnabled() is False


# --- Install page (Task 18) ---------------------------------------------


def test_install_page_shim_installed_disables_install_enables_uninstall(qtbot, tmp_path):
    state = _state(tmp_path, shim_installed=True)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    assert window.install_page.install_button.isEnabled() is False
    assert window.install_page.uninstall_button.isEnabled() is True


def test_install_page_shim_not_installed_enables_install_disables_uninstall(qtbot, tmp_path):
    state = _state(tmp_path, shim_installed=False)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    assert window.install_page.install_button.isEnabled() is True
    assert window.install_page.uninstall_button.isEnabled() is False


def test_install_button_emits_install_shim_action(qtbot, tmp_path):
    state = _state(tmp_path, shim_installed=False)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.install_page.install_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["install_shim", {}]


def test_uninstall_button_emits_uninstall_shim_action(qtbot, tmp_path):
    state = _state(tmp_path, shim_installed=True)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        qtbot.mouseClick(window.install_page.uninstall_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["uninstall_shim", {}]


def test_install_target_combo_selection_emits_set_install_target(qtbot, tmp_path):
    # `detected_claude_command_path` is the default selection (shim_target_path
    # is unset), so picking a *different* combo row -- the managed user
    # target, always listed first -- is what actually changes the selection.
    detected = tmp_path / "detected" / "claude"
    state = _state(tmp_path, detected_claude_command_path=detected)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    combo = window.install_page.target_combo
    managed_target = combo.itemData(0)
    assert managed_target != detected

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        combo.setCurrentIndex(0)

    assert blocker.args == ["set_install_target", {"path": str(managed_target)}]


def test_install_page_protected_target_shows_protected_in_status_label(qtbot, tmp_path):
    protected = Path("/usr/local/bin/claude")
    state = _state(tmp_path, shim_target_path=protected)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    assert "protected" in window.install_page.status_label.text()


def test_install_page_user_writable_target_status_label(qtbot, tmp_path):
    writable = tmp_path / ".harnessmonkey" / "bin" / "claude"
    state = _state(tmp_path, shim_target_path=writable)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    assert "protected" not in window.install_page.status_label.text()


def test_install_page_shim_status_line_reflects_shim_target_path(qtbot, tmp_path):
    installed_path = tmp_path / ".harnessmonkey" / "bin" / "claude"
    state = _state(tmp_path, shim_target_path=installed_path)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)
    assert f"Installed at {installed_path}" in window.install_page.shim_status_label.text()

    state_not_installed = _state(tmp_path, shim_target_path=None)
    window.render(state_not_installed)
    assert "Not installed" in window.install_page.shim_status_label.text()


def test_install_page_shim_status_line_abbreviates_home(qtbot, monkeypatch, tmp_path):
    # Fix: paths shown to the user should be home-abbreviated (~/...) --
    # extends the courtesy `repair_confirm_text`/the update notice now use.
    monkeypatch.setenv("HOME", str(tmp_path))
    installed_path = tmp_path / ".local" / "bin" / "claude"
    state = _state(tmp_path, shim_target_path=installed_path)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    assert window.install_page.shim_status_label.text() == "Installed at ~/.local/bin/claude"


def test_install_target_combo_marks_standard_location_guesses(qtbot, tmp_path):
    # Fix: today's combo mixed genuinely-detected entries with hardcoded
    # standard-location guesses indistinguishably -- guesses must now carry
    # a short "standard location" suffix so the user can tell them apart.
    state = _state(tmp_path, shim_target_path=None, detected_claude_command_path=None)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state)

    combo = window.install_page.target_combo
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert any("standard location" in text for text in texts)
    # The managed-user-target entry (index 0, a real detected/owned path)
    # must never carry the guess suffix.
    assert "standard location" not in texts[0]


def test_install_target_browse_picks_path_and_emits_action(qtbot, monkeypatch, tmp_path):
    state = _state(tmp_path)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    browsed = str(tmp_path / "browsed" / "claude")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (browsed, ""))

    combo = window.install_page.target_combo
    browse_index = combo.count() - 1
    assert combo.itemText(browse_index) == "Browse…"

    with qtbot.waitSignal(window.action, timeout=1000) as blocker:
        combo.setCurrentIndex(browse_index)

    assert blocker.args == ["set_install_target", {"path": browsed}]


def test_install_target_browse_activates_app_before_file_dialog(qtbot, monkeypatch, tmp_path):
    state = _state(tmp_path)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    calls: list[str] = []
    monkeypatch.setattr(
        app_module, "activate_app_for_window", lambda: calls.append("activate_app")
    )
    browsed = str(tmp_path / "browsed" / "claude")

    def fake_get_save_file_name(*_args, **_kwargs):
        calls.append("dialog")
        return (browsed, "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_get_save_file_name)

    combo = window.install_page.target_combo
    browse_index = combo.count() - 1
    combo.setCurrentIndex(browse_index)

    assert calls == ["activate_app", "dialog"]


def test_install_target_browse_cancelled_emits_nothing(qtbot, monkeypatch, tmp_path):
    state = _state(tmp_path)
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))

    seen: list[tuple[str, dict]] = []
    window.action.connect(lambda action_id, payload: seen.append((action_id, payload)))

    combo = window.install_page.target_combo
    browse_index = combo.count() - 1
    combo.setCurrentIndex(browse_index)
    qtbot.wait(50)

    assert seen == []


# ---------------------------------------------------------------------------
# Busy-state gating (window mirrors tray's TrayModel.mutating_enabled)
# ---------------------------------------------------------------------------
#
# `Controller.refresh` passes its `_busy_command` into `window.render(state,
# busy_command)` the same way it already feeds `build_tray_model` for the
# tray -- every mutating control across the window's pages must disable
# while a command is in flight, and re-enable once it isn't. Non-mutating
# controls (sidebar navigation, log-viewing/open buttons) must stay live
# regardless.


def test_window_render_while_busy_disables_mutating_controls(qtbot, fake_state):
    # desired_patch_ids=()/active_option_ids=() so the patch/option are
    # otherwise removable -- if they weren't, `remove_enabled`'s own
    # refusal would mask whether busy-gating is actually applied on top of
    # it.
    state = MenuState(
        **{**fake_state.__dict__, "desired_patch_ids": (), "active_option_ids": ()}
    )
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.render(state)
    window.patches_page.table.setCurrentCell(0, 0)
    window.options_page.table.setCurrentCell(0, 0)

    window.render(state, "toggle_patch")

    patch_checkbox = window.patches_page.table.item(0, 0)
    assert not (patch_checkbox.flags() & Qt.ItemFlag.ItemIsEnabled)
    option_checkbox = window.options_page.table.item(0, 0)
    assert not (option_checkbox.flags() & Qt.ItemFlag.ItemIsEnabled)

    assert window.patches_page.add_button.isEnabled() is False
    assert window.options_page.add_button.isEnabled() is False
    assert window.prompts_page.add_button.isEnabled() is False
    assert window.patches_page.remove_button.isEnabled() is False
    assert window.options_page.remove_button.isEnabled() is False

    # Prompt-set control (the list a user clicks to activate a prompt).
    assert window.prompts_page.list.isEnabled() is False

    assert window.overview_page.rebuild_button.isEnabled() is False

    # Both install/uninstall must be disabled while busy, regardless of
    # shim_installed (fake_state has shim_installed=True).
    assert window.install_page.install_button.isEnabled() is False
    assert window.install_page.uninstall_button.isEnabled() is False


def test_window_render_not_busy_reenables_mutating_controls(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(fake_state, "toggle_patch")
    window.render(fake_state, None)

    patch_checkbox = window.patches_page.table.item(0, 0)
    assert bool(patch_checkbox.flags() & Qt.ItemFlag.ItemIsEnabled)
    option_checkbox = window.options_page.table.item(0, 0)
    assert bool(option_checkbox.flags() & Qt.ItemFlag.ItemIsEnabled)

    assert window.patches_page.add_button.isEnabled() is True
    assert window.options_page.add_button.isEnabled() is True
    assert window.prompts_page.add_button.isEnabled() is True
    assert window.prompts_page.list.isEnabled() is True

    assert window.overview_page.rebuild_button.isEnabled() is True

    # fake_state has shim_installed=True: install stays disabled for that
    # reason, uninstall re-enables now that nothing is busy.
    assert window.install_page.install_button.isEnabled() is False
    assert window.install_page.uninstall_button.isEnabled() is True


def test_navigation_and_logs_controls_stay_enabled_while_busy(qtbot, fake_state):
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(fake_state, "rebuild")

    assert window.sidebar.isEnabled() is True
    assert window.logs_page.open_report_button.isEnabled() is True
    assert window.logs_page.open_logs_folder_button.isEnabled() is True
    assert window.logs_page.open_state_folder_button.isEnabled() is True


def test_install_page_combo_change_while_busy_keeps_install_disabled(qtbot, tmp_path):
    # Regression (reviewer re-review finding 1): `InstallPage` never cached
    # `mutating_enabled` and its internal self-render call sites
    # (`_on_combo_index_changed`/`_on_browse`) called `self.render(self._state)`
    # with no argument, silently defaulting to `mutating_enabled=True` --
    # changing the target combo mid-flight re-enabled the Install button,
    # defeating the busy gating shipped in 082d601.
    detected = tmp_path / "detected" / "claude"
    state = _state(tmp_path, shim_installed=False, detected_claude_command_path=detected)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state, "install_shim")
    assert window.install_page.install_button.isEnabled() is False

    combo = window.install_page.target_combo
    managed_target = combo.itemData(0)
    assert managed_target != detected  # index 0 is a real, different selection

    combo.setCurrentIndex(0)  # simulate a combo change mid-flight

    assert window.install_page.install_button.isEnabled() is False


def test_install_page_combo_change_after_busy_clears_reenables(qtbot, tmp_path):
    detected = tmp_path / "detected" / "claude"
    state = _state(tmp_path, shim_installed=False, detected_claude_command_path=detected)
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(state, "install_shim")
    window.render(state, None)  # busy command cleared
    assert window.install_page.install_button.isEnabled() is True

    combo = window.install_page.target_combo
    managed_target = combo.itemData(0)
    assert managed_target != detected

    combo.setCurrentIndex(0)

    assert window.install_page.install_button.isEnabled() is True


def test_render_busy_command_defaults_to_not_busy(qtbot, fake_state):
    # Every pre-existing `window.render(state)` call (no `busy_command` arg)
    # must keep behaving exactly as before this fix -- fully enabled.
    window = SettingsWindow()
    qtbot.addWidget(window)

    window.render(fake_state)

    assert window.overview_page.rebuild_button.isEnabled() is True
    patch_checkbox = window.patches_page.table.item(0, 0)
    assert bool(patch_checkbox.flags() & Qt.ItemFlag.ItemIsEnabled)


def test_notice_repair_button_disables_while_busy_and_reenables_after(qtbot):
    # `repair_shim` is a mutating command (`Controller._action_repair_shim`
    # itself no-ops while busy) -- the notice's "Repair shim..." button must
    # disable/re-enable the same way the rebuild button does, while
    # "Dismiss" (pure Controller state, no CLI call) stays live regardless.
    window = SettingsWindow()
    qtbot.addWidget(window)
    notice = NoticeModel(message="repair needed", digest="abcd1234", actions=("repair",))

    window.render_notice(notice, "repair_shim")
    assert window.overview_page.notice_repair_button.isEnabled() is False
    assert window.overview_page.notice_dismiss_button.isEnabled() is True

    window.render_notice(notice, None)
    assert window.overview_page.notice_repair_button.isEnabled() is True
    assert window.overview_page.notice_dismiss_button.isEnabled() is True
