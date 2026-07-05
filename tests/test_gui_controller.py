"""Tests for `Controller` (Task 19): the single `on_action` handler wiring
every tray/window intent to `CommandRunner`/`ProgressDialog`.

`Controller` is exercised against a stub runner (records every
`run_json`/`run_background`/`run_streaming` call, returns injectable
results) plus lightweight fake `Tray`/`SettingsWindow` doubles -- real
`ProgressDialog`s are used since they're cheap, already-tested Qt widgets
and the point of these tests is the wiring around them, not re-testing
`ProgressDialog`/`ProgressModel` themselves (see
`tests/test_gui_progress_dialog.py`/`tests/test_gui_progress_model.py`).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from harnessmonkey.gui import commands  # noqa: E402
from harnessmonkey.gui.app import CommandBridge, Controller  # noqa: E402

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeHandle:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self, grace_seconds: float = 5.0) -> None:
        self.cancel_calls += 1


class StubRunner:
    """Records every call; `run_json` results are injectable by argv."""

    def __init__(self) -> None:
        self.logs_dir = Path("/tmp/fake-harnessmonkey-logs")
        self.run_json_calls: list[tuple[list[str], bool]] = []
        self.run_json_results: dict[tuple[str, ...], dict | Exception] = {}
        self.background_calls: list[tuple[str, list[str], bool]] = []
        self.streaming_calls: list[tuple[str, list[str]]] = []
        self.open_path_calls: list[Path] = []
        self.handles: dict[str, FakeHandle] = {}

    # -- injected defaults for refresh()'s four non-mutating calls --------

    def _default(self, args: list[str]) -> dict:
        key = args[0]
        if key == "status":
            return _status_raw()
        if key == "list-patches":
            return {"schemaVersion": 1, "patches": []}
        if key == "list-prompts":
            return {"schemaVersion": 1, "prompts": []}
        if key == "list-options":
            return {"schemaVersion": 1, "options": []}
        raise AssertionError(f"unexpected run_json call: {args}")

    def run_json(self, args: list[str], *, mutating: bool) -> dict:
        self.run_json_calls.append((list(args), mutating))
        key = tuple(args)
        if key in self.run_json_results:
            result = self.run_json_results[key]
            if isinstance(result, Exception):
                raise result
            return result
        return self._default(args)

    def run_background(self, name: str, args: list[str], *, mutating: bool) -> None:
        self.background_calls.append((name, list(args), mutating))

    def run_streaming(self, name: str, args: list[str], *, on_event) -> FakeHandle:
        self.streaming_calls.append((name, list(args)))
        handle = FakeHandle()
        self.handles[name] = handle
        return handle

    def open_path(self, path: Path) -> None:
        self.open_path_calls.append(path)


class FakeTray:
    def __init__(self) -> None:
        self.rendered: list = []

    def render(self, model) -> None:
        self.rendered.append(model)


class FakeWindow:
    def __init__(self) -> None:
        self.rendered: list = []
        self.banners: list[tuple[str, str]] = []
        self.notices: list = []
        self.busy_commands: list[str | None] = []

    def render(self, state, busy_command: str | None = None) -> None:
        self.rendered.append(state)
        self.busy_commands.append(busy_command)

    def render_notice(self, notice, busy_command: str | None = None) -> None:
        self.notices.append(notice)

    def show_banner(self, page: str, message: str) -> None:
        self.banners.append((page, message))

    def show(self) -> None:
        pass

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass


def _status_raw(**overrides) -> dict:
    base = {
        "schemaVersion": 1,
        "status": "ok",
        "rebuildRequired": False,
        "stateDir": "/tmp/state",
        "logsDir": "/tmp/state/logs",
        "desiredPatchIds": [],
        "activePatchIds": [],
        "activeOptionIds": [],
        "highRiskOptions": [],
    }
    base.update(overrides)
    return base


def _envelope(*, ok: bool = True, authorization_required: bool = False, **overrides) -> dict:
    base = {
        "schemaVersion": 1,
        "ok": ok,
        "status": "ok" if ok else "error",
        "summary": "ok" if ok else "failed",
        "reportPath": None,
        "targetPath": None,
        "authorizationRequired": authorization_required,
        "authorizationMethod": None,
        "dryRun": False,
        "plannedActions": [],
        "error": None if ok else {"message": "failed", "code": "command_failed"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def confirm_repair_calls():
    return []


@pytest.fixture
def controller_parts(confirm_repair_calls):
    runner = StubRunner()
    bridge = CommandBridge()
    tray = FakeTray()
    window = FakeWindow()
    confirm_calls: list[tuple[str, str]] = []
    controller = Controller(
        runner=runner,
        bridge=bridge,
        tray=tray,
        window=window,
        confirm_high_risk=lambda option_id, warning: confirm_calls.append(
            (option_id, warning)
        )
        or True,
        confirm_repair=lambda message: confirm_repair_calls.append(message) or True,
        quit_callback=lambda: None,
    )
    return controller, runner, bridge, tray, window, confirm_calls


# ---------------------------------------------------------------------------
# Mandated Step-1 scenarios
# ---------------------------------------------------------------------------


def test_rebuild_opens_dialog_and_streams_on_confirm(qtbot, controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("rebuild", {})

    assert controller._dialog is not None
    qtbot.addWidget(controller._dialog)

    controller._dialog.confirmed.emit()

    assert runner.streaming_calls == [
        ("rebuild", ["build", "--json", "--activate", "--progress"])
    ]


def test_toggle_patch_runs_background_and_banner_on_failure(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("toggle_patch", {"patch_id": "p1", "enabled": False})

    assert runner.background_calls == [
        ("toggle_patch", ["enable-patch", "p1", "--json"], True)
    ]

    bridge.command_finished.emit("toggle_patch", _envelope(ok=False, summary="boom"))

    assert window.banners == [("patches", "boom")]
    assert controller._busy_command is None


def test_toggle_patch_cascade_success_shows_banner(controller_parts):
    # Dogfood fix: enabling a patch that requires another one (e.g.
    # thinking-drawer requires drawer-dock) auto-enables the
    # dependency CLI-side (cli.py's handle_enable_patch); the GUI must
    # surface that cascade as a transient banner, not just a silently
    # re-checked row after refresh().
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("toggle_patch", {"patch_id": "thinking-drawer", "enabled": False})
    assert runner.background_calls == [
        ("toggle_patch", ["enable-patch", "thinking-drawer", "--json"], True)
    ]

    bridge.command_finished.emit(
        "toggle_patch",
        _envelope(
            ok=True,
            summary=(
                "enabled thinking-drawer (+ drawer-dock, required); "
                "rebuild required"
            ),
        ),
    )

    assert window.banners == [
        (
            "patches",
            "enabled thinking-drawer (+ drawer-dock, required); rebuild required",
        )
    ]


def test_toggle_patch_disable_blocked_by_dependents_shows_clear_banner(controller_parts):
    # Dogfood fix, disable side: cli.py's handle_disable_patch refuses (exit
    # 1, ok: False) to disable a package still required by an enabled
    # dependent -- the existing generic failure-banner path (see
    # test_toggle_patch_runs_background_and_banner_on_failure) already
    # surfaces whatever `summary` the CLI sends, so this pins the exact,
    # dependent-naming message for the disable-blocked case specifically.
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("toggle_patch", {"patch_id": "drawer-dock", "enabled": True})
    assert runner.background_calls == [
        ("toggle_patch", ["disable-patch", "drawer-dock", "--json"], True)
    ]

    bridge.command_finished.emit(
        "toggle_patch",
        _envelope(
            ok=False,
            summary="cannot disable drawer-dock: required by thinking-drawer",
        ),
    )

    assert window.banners == [
        ("patches", "cannot disable drawer-dock: required by thinking-drawer")
    ]


def test_toggle_patch_ordinary_success_shows_no_banner(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("toggle_patch", {"patch_id": "drawer-dock", "enabled": False})
    bridge.command_finished.emit(
        "toggle_patch", _envelope(ok=True, summary="enabled drawer-dock; rebuild required")
    )

    assert window.banners == []


def test_install_shim_authorization_required_disables_cancel(qtbot, controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    target = Path("/usr/local/bin/claude")
    controller.on_action("set_install_target", {"path": str(target)})

    dry_key = tuple(commands.command_for_install_shim(target, dry_run=True))
    runner.run_json_results[dry_key] = _envelope(
        authorization_required=True,
        summary="would install managed claude shim",
        planned_actions=["install managed claude shim"],
    )

    controller.on_action("install_shim", {})

    assert controller._dialog is not None
    qtbot.addWidget(controller._dialog)
    assert controller._dialog._cancel_allowed_during_run is False


# ---------------------------------------------------------------------------
# install_shim / uninstall_shim (long ops) -- additional coverage
# ---------------------------------------------------------------------------


def test_install_shim_authorization_not_required_allows_cancel(qtbot, controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    target = Path("/tmp/managed/claude")
    controller.on_action("set_install_target", {"path": str(target)})

    dry_key = tuple(commands.command_for_install_shim(target, dry_run=True))
    runner.run_json_results[dry_key] = _envelope(authorization_required=False)

    controller.on_action("install_shim", {})

    assert controller._dialog is not None
    qtbot.addWidget(controller._dialog)
    assert controller._dialog._cancel_allowed_during_run is True

    controller._dialog.confirmed.emit()
    real_key = ("install_shim", commands.command_for_install_shim(target, dry_run=False))
    assert runner.streaming_calls == [real_key]


def test_install_shim_dry_run_failure_shows_banner_and_no_dialog(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    target = Path("/tmp/managed/claude")
    controller.on_action("set_install_target", {"path": str(target)})

    dry_key = tuple(commands.command_for_install_shim(target, dry_run=True))
    runner.run_json_results[dry_key] = _envelope(
        ok=False, summary="refusing to overwrite protected target"
    )

    controller.on_action("install_shim", {})

    assert controller._dialog is None
    assert window.banners == [("install", "refusing to overwrite protected target")]
    assert controller._busy_command is None


def test_uninstall_shim_uses_recorded_shim_target(qtbot, controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    recorded = "/opt/homebrew/bin/claude"
    runner.run_json_results[("status", "--json")] = _status_raw(shimTargetPath=recorded)
    controller.refresh()

    dry_key = tuple(
        commands.command_for_uninstall_shim(target=Path(recorded), dry_run=True)
    )
    runner.run_json_results[dry_key] = _envelope(authorization_required=False)

    controller.on_action("uninstall_shim", {})

    assert controller._dialog is not None
    qtbot.addWidget(controller._dialog)
    real_key = (
        "uninstall_shim",
        commands.command_for_uninstall_shim(target=Path(recorded), dry_run=False),
    )
    controller._dialog.confirmed.emit()
    assert runner.streaming_calls == [real_key]


def test_second_long_op_ignored_while_one_is_open(qtbot, controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("rebuild", {})
    first_dialog = controller._dialog
    qtbot.addWidget(first_dialog)

    controller.on_action("install_shim", {})

    assert controller._dialog is first_dialog
    assert runner.run_json_calls == [] or all(
        call[0][0] != "install-shim" for call in runner.run_json_calls
    )


def test_cancel_during_running_calls_handle_cancel_not_dialog_finish(qtbot, controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("rebuild", {})
    dialog = controller._dialog
    qtbot.addWidget(dialog)
    dialog.confirmed.emit()

    dialog.cancel_requested.emit()

    handle = runner.handles["rebuild"]
    assert handle.cancel_calls == 1
    # Dialog is still open/RUNNING -- cancelling doesn't fabricate a result.
    assert controller._dialog is dialog
    assert dialog._phase == "RUNNING"


def test_cancel_during_confirm_tears_down_dialog(qtbot, controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("rebuild", {})
    dialog = controller._dialog
    qtbot.addWidget(dialog)

    dialog.cancel_requested.emit()

    assert controller._dialog is None
    assert controller._busy_command is None
    assert runner.streaming_calls == []


def test_command_finished_always_finishes_dialog_even_on_malformed_payload(
    qtbot, controller_parts
):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("rebuild", {})
    dialog = controller._dialog
    qtbot.addWidget(dialog)
    dialog.confirmed.emit()

    # Malformed/missing-field result: no "ok", no "summary", nothing.
    bridge.command_finished.emit("rebuild", {})

    assert dialog._phase == "RESULT"
    assert controller._dialog is None
    assert controller._handle is None
    assert controller._busy_command is None


# ---------------------------------------------------------------------------
# toggle_option per-emitter translation (hazard #1)
# ---------------------------------------------------------------------------


def test_toggle_option_window_confirmed_maps_to_confirm_true(controller_parts):
    controller, runner, bridge, tray, window, confirm_calls = controller_parts

    controller.on_action(
        "toggle_option", {"option_id": "danger", "enabled": False, "confirmed": True}
    )

    assert runner.background_calls == [
        ("toggle_option", ["enable-option", "danger", "--confirm", "--json"], True)
    ]
    assert confirm_calls == []  # window already ran its own confirm flow


def test_toggle_option_window_unconfirmed_maps_to_confirm_false(controller_parts):
    controller, runner, bridge, tray, window, confirm_calls = controller_parts

    controller.on_action("toggle_option", {"option_id": "safe", "enabled": True})

    assert runner.background_calls == [
        ("toggle_option", ["disable-option", "safe", "--json"], True)
    ]
    assert confirm_calls == []


def test_toggle_option_tray_high_risk_runs_confirm_and_proceeds(controller_parts):
    controller, runner, bridge, tray, window, confirm_calls = controller_parts
    controller._state = None  # no state fetched yet -- text lookup must not crash

    controller.on_action(
        "toggle_option",
        {"option_id": "danger", "enabled": False, "requires_confirmation": True},
    )

    # Item 1 (unified high-risk confirm): the second arg is now the full
    # Controller-built confirm text (window_model.high_risk_confirm_text),
    # not the raw warning -- with no state fetched yet, that's its generic
    # fallback, same text `_default_confirm_high_risk` always fell back to.
    assert confirm_calls == [("danger", "This option is high-risk.")]
    assert runner.background_calls == [
        ("toggle_option", ["enable-option", "danger", "--confirm", "--json"], True)
    ]


def test_toggle_option_tray_high_risk_declined_does_not_run_command(controller_parts):
    runner = StubRunner()
    bridge = CommandBridge()
    tray = FakeTray()
    window = FakeWindow()
    controller = Controller(
        runner=runner,
        bridge=bridge,
        tray=tray,
        window=window,
        confirm_high_risk=lambda option_id, warning: False,
        quit_callback=lambda: None,
    )

    controller.on_action(
        "toggle_option",
        {"option_id": "danger", "enabled": False, "requires_confirmation": True},
    )

    assert runner.background_calls == []
    # Item 1: a declined high-risk confirm now triggers a refresh() so both
    # tray and window re-render from the true MenuState -- this is what
    # corrects a checkbox/checkmark Qt already flipped on click, since
    # neither surface reverts its own widget state anymore.
    assert len(window.rendered) == 1
    assert window.rendered[0] is not None


def test_toggle_option_tray_not_high_risk_skips_confirm(controller_parts):
    controller, runner, bridge, tray, window, confirm_calls = controller_parts

    controller.on_action(
        "toggle_option",
        {"option_id": "safe", "enabled": False, "requires_confirmation": False},
    )

    assert confirm_calls == []
    assert runner.background_calls == [
        ("toggle_option", ["enable-option", "safe", "--json"], True)
    ]


def test_toggle_option_tray_disabling_high_risk_skips_confirm(controller_parts):
    # requires_confirmation only matters when turning an option ON
    # (enabled=False means currently off); turning a high-risk option OFF
    # (enabled=True) must never trigger the confirm prompt.
    controller, runner, bridge, tray, window, confirm_calls = controller_parts

    controller.on_action(
        "toggle_option",
        {"option_id": "danger", "enabled": True, "requires_confirmation": True},
    )

    assert confirm_calls == []
    assert runner.background_calls == [
        ("toggle_option", ["disable-option", "danger", "--json"], True)
    ]


def test_toggle_option_window_declined_reverts_checkbox_via_refresh(qtbot):
    # Item 1 (unified high-risk confirm dialog): the window's Options page
    # no longer owns its own QMessageBox/checkbox-revert logic -- it emits
    # the same requires_confirmation shape the tray already does, and a
    # decline is corrected purely by Controller.refresh() re-rendering from
    # the true (unchanged) MenuState. This needs a REAL SettingsWindow (not
    # the lightweight FakeWindow double used elsewhere in this file) wired
    # to a real Controller, since the regression under test is specifically
    # about the Qt checkbox widget's on-screen state after a decline.
    from harnessmonkey.gui.settings_window import SettingsWindow

    runner = StubRunner()
    runner.run_json_results[("list-options", "--json")] = {
        "schemaVersion": 1,
        "options": [
            {
                "id": "danger",
                "label": "Danger",
                "enabled": False,
                "valid": True,
                "riskLevel": "high",
                "requiresConfirmation": True,
            }
        ],
    }
    runner.run_json_results[("status", "--json")] = _status_raw(
        highRiskOptions=[{"id": "danger", "label": "Danger", "warning": "This is risky."}]
    )

    bridge = CommandBridge()
    tray = FakeTray()
    window = SettingsWindow()
    qtbot.addWidget(window)
    controller = Controller(
        runner=runner,
        bridge=bridge,
        tray=tray,
        window=window,
        confirm_high_risk=lambda option_id, text: False,
        quit_callback=lambda: None,
    )
    window.action.connect(controller.on_action)

    controller.refresh()
    checkbox_item = window.options_page.table.item(0, 0)
    assert checkbox_item.checkState() == Qt.CheckState.Unchecked

    checkbox_item.setCheckState(Qt.CheckState.Checked)
    qtbot.wait(50)

    assert runner.background_calls == []
    reverted_item = window.options_page.table.item(0, 0)
    assert reverted_item.checkState() == Qt.CheckState.Unchecked


# ---------------------------------------------------------------------------
# Quick-op busy-render push (reviewer re-review finding 2)
# ---------------------------------------------------------------------------
#
# `_run_quick` used to set `self._busy_command` and fire `run_background`
# without ever re-rendering -- window/tray were never told "we're busy" for
# the actual duration of a quick op, so the busy gating from 082d601 was
# only ever exercised if the user manually clicked Refresh mid-flight. The
# real click-race (click a quick-op button, then immediately click
# something else before it finishes) was completely unprotected.


def test_quick_op_pushes_busy_render_before_command_finishes(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    controller.refresh()  # populate self._state so `_run_quick` has something to render
    window.rendered.clear()
    window.busy_commands.clear()
    tray.rendered.clear()

    controller.on_action("toggle_patch", {"patch_id": "p1", "enabled": False})

    # Busy render pushed synchronously, before the background command
    # completes -- to BOTH window and tray.
    assert window.busy_commands == ["toggle_patch"]
    assert len(tray.rendered) == 1
    assert tray.rendered[0].mutating_enabled is False

    bridge.command_finished.emit("toggle_patch", _envelope(ok=True))

    # And the next render, once the command completes, is non-busy again.
    assert window.busy_commands == ["toggle_patch", None]
    assert tray.rendered[-1].mutating_enabled is True


def test_quick_op_skips_busy_render_when_no_state_cached_yet(controller_parts):
    # Before any `refresh()` has ever run, there's no cached `MenuState` to
    # render busy with -- `_run_quick` must skip the push entirely rather
    # than rendering a bogus `None` state as busy.
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("toggle_patch", {"patch_id": "p1", "enabled": False})

    assert window.rendered == []
    assert tray.rendered == []


# ---------------------------------------------------------------------------
# refresh / quit / open_path / add & remove package routing
# ---------------------------------------------------------------------------


def test_refresh_success_renders_tray_and_window(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.refresh()

    assert len(tray.rendered) == 1
    assert len(window.rendered) == 1
    assert window.rendered[0] is not None


def test_refresh_failure_renders_none_state(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    runner.run_json_results[("status", "--json")] = RuntimeError("boom")

    controller.refresh()

    assert window.rendered == [None]


def test_quit_cancels_active_handle_and_calls_quit_callback(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    quit_calls = []
    controller._quit_callback = lambda: quit_calls.append(True)

    controller.on_action("rebuild", {})
    controller._dialog.confirmed.emit()
    handle = runner.handles["rebuild"]

    controller.on_action("quit", {})

    assert handle.cancel_calls == 1
    assert quit_calls == [True]


def test_open_path_action_calls_runner_open_path(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("open_path", {"path": "/tmp/report.json"})

    assert runner.open_path_calls == [Path("/tmp/report.json")]


def test_add_package_routes_banner_by_kind(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("add_package", {"kind": "option", "path": "/tmp/opt"})
    assert runner.background_calls == [
        ("add_package", ["add-option", "/tmp/opt", "--json"], True)
    ]
    bridge.command_finished.emit("add_package", _envelope(ok=False, summary="bad package"))
    assert window.banners == [("options", "bad package")]


def test_remove_package_routes_banner_by_kind(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("remove_package", {"kind": "prompt", "package_id": "p1"})
    assert runner.background_calls == [
        ("remove_package", ["remove-prompt", "p1", "--json"], True)
    ]
    bridge.command_finished.emit("remove_package", _envelope(ok=False, summary="in use"))
    assert window.banners == [("prompts", "in use")]


# ---------------------------------------------------------------------------
# repair_shim (shim-update-resilience GUI notice, spec sec4/sec5, R2/R3/R8)
# ---------------------------------------------------------------------------


def _replaced_status_raw(**overrides) -> dict:
    base = _status_raw(
        shimInstalled=False,
        shimPreviouslyManaged=True,
        targetReplacedByOfficial=True,
        detectedOfficialSha256="a0852d76afc47b30f5cb0b7625ec9a7714cb189f2eeef6c28c77e2be954fb7fd",
        detectedOfficialVersion="2.1.201",
        shimRepairAvailable=True,
        rolloutRequired=True,
    )
    base.update(overrides)
    return base


def test_repair_shim_confirmed_runs_background_with_no_target(
    controller_parts, confirm_repair_calls
):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("repair_shim", {})

    assert runner.background_calls == [("repair_shim", ["repair-shim", "--json"], True)]
    assert len(confirm_repair_calls) == 1  # explicit user confirmation happened (R2)


def test_repair_shim_declined_does_not_run_command(confirm_repair_calls):
    runner = StubRunner()
    bridge = CommandBridge()
    tray = FakeTray()
    window = FakeWindow()
    controller = Controller(
        runner=runner,
        bridge=bridge,
        tray=tray,
        window=window,
        confirm_repair=lambda message: False,
        quit_callback=lambda: None,
    )

    controller.on_action("repair_shim", {})

    assert runner.background_calls == []


def test_repair_shim_confirm_text_reflects_detected_version(controller_parts, confirm_repair_calls):
    controller, runner, bridge, tray, window, _ = controller_parts
    runner.run_json_results[("status", "--json")] = _replaced_status_raw()
    controller.refresh()

    controller.on_action("repair_shim", {})

    assert "2.1.201" in confirm_repair_calls[0]


def test_repair_shim_busy_ignores_second_trigger(controller_parts, confirm_repair_calls):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("repair_shim", {})
    controller.on_action("repair_shim", {})

    assert len(runner.background_calls) == 1
    assert len(confirm_repair_calls) == 1


def test_repair_shim_refusal_shows_dejargoned_banner(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("repair_shim", {})
    bridge.command_finished.emit(
        "repair_shim",
        _envelope(ok=False, summary="target changed since it was classified/cached")
        | {"error": {"message": "target changed", "code": "target_changed"}},
    )

    assert window.banners == [("overview", "Claude changed again — re-checking.")]
    assert controller._busy_command is None


def test_repair_shim_refusal_unknown_code_falls_back_without_raw_code(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("repair_shim", {})
    bridge.command_finished.emit(
        "repair_shim",
        _envelope(ok=False, summary="boom")
        | {"error": {"message": "boom", "code": "some_new_code"}},
    )

    message = window.banners[0][1]
    assert message != "some_new_code"
    assert "some_new_code" not in message


def test_repair_shim_success_triggers_refresh(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("repair_shim", {})
    calls_before = len(runner.run_json_calls)
    bridge.command_finished.emit("repair_shim", _envelope(ok=True))

    # refresh() re-fetches status/patches/prompts/options.
    assert len(runner.run_json_calls) > calls_before
    # Ordinary successful-and-stable outcome: no banner needed.
    assert window.banners == []


def test_repair_shim_success_with_revert_shows_banner(controller_parts):
    # Fix 2: field-observed fast-revert loop (the official Claude installer's
    # own self-heal re-clobbers a just-repaired target within seconds) -- a
    # successful swap (`ok: true`) that already reverted must still surface a
    # banner explaining what happened, distinct from the refusal-message path.
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.on_action("repair_shim", {})
    bridge.command_finished.emit(
        "repair_shim", _envelope(ok=True) | {"revertedImmediately": True}
    )

    assert len(window.banners) == 1
    page, message = window.banners[0]
    assert page == "overview"
    assert message != ""
    assert "revertedImmediately" not in message


# ---------------------------------------------------------------------------
# notice model wiring: refresh() / dismiss_notice
# ---------------------------------------------------------------------------


def test_refresh_pushes_notice_to_tray_and_window(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    runner.run_json_results[("status", "--json")] = _replaced_status_raw()

    controller.refresh()

    assert window.notices[-1] is not None
    assert window.notices[-1].actions == ("repair",)
    assert tray.rendered[-1].notice is window.notices[-1]


def test_refresh_no_replacement_pushes_none_notice(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts

    controller.refresh()

    assert window.notices[-1] is None
    assert tray.rendered[-1].notice is None


def test_refresh_failure_pushes_none_notice(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    runner.run_json_results[("status", "--json")] = RuntimeError("boom")

    controller.refresh()

    assert window.notices == [None]


def test_dismiss_notice_hides_it_until_refresh_recomputes(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    runner.run_json_results[("status", "--json")] = _replaced_status_raw()
    controller.refresh()
    digest = window.notices[-1].digest

    controller.on_action("dismiss_notice", {"digest": digest})

    assert window.notices[-1] is None
    assert tray.rendered[-1].notice is None

    # A NEW digest (a later official update) re-raises even though the old
    # one is dismissed (R5).
    runner.run_json_results[("status", "--json")] = _replaced_status_raw(
        detectedOfficialSha256="b" * 64, detectedOfficialVersion="2.1.202"
    )
    controller.refresh()

    assert window.notices[-1] is not None
    assert window.notices[-1].digest == "b" * 64


def test_dismiss_notice_same_digest_stays_hidden_across_refresh(controller_parts):
    controller, runner, bridge, tray, window, _ = controller_parts
    runner.run_json_results[("status", "--json")] = _replaced_status_raw()
    controller.refresh()
    digest = window.notices[-1].digest

    controller.on_action("dismiss_notice", {"digest": digest})
    controller.refresh()

    assert window.notices[-1] is None
