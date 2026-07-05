"""Tests for the Qt application shell in harnessmonkey.gui.app.

Covers the pieces that exist ahead of Task 19's wiring: root refusal,
single-instance detection via QLocalServer, and the CommandBridge signal
plumbing that lets a worker thread deliver progress events across to the Qt
event loop.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402

import harnessmonkey.gui.app as app_module  # noqa: E402
from harnessmonkey.gui.app import (  # noqa: E402
    CommandBridge,
    Controller,
    SingleInstance,
    build_runner,
    refuse_root,
)


def test_build_runner_invokes_cli_via_own_interpreter():
    runner = build_runner()
    assert runner.cli_argv == [sys.executable, "-m", "harnessmonkey"]
    assert runner.logs_dir == Path.home() / ".harnessmonkey" / "logs"



class _Runner:
    logs_dir = Path("/tmp/harnessmonkey-test-logs")


class _Tray:
    def render(self, _model):
        pass


def test_long_op_progress_dialog_is_parented_modal_and_foregrounded(qtbot, monkeypatch):
    window = QWidget()
    qtbot.addWidget(window)

    activate_calls: list[str] = []
    monkeypatch.setattr(
        app_module, "activate_app_for_window", lambda: activate_calls.append("activate_app")
    )

    class SpyProgressDialog(app_module.ProgressDialog):
        last = None

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            SpyProgressDialog.last = self
            self.foreground_calls = []

        def show(self):
            self.foreground_calls.append("show")
            super().show()

        def raise_(self):
            self.foreground_calls.append("raise")
            super().raise_()

        def activateWindow(self):
            self.foreground_calls.append("activate")
            super().activateWindow()

    monkeypatch.setattr(app_module, "ProgressDialog", SpyProgressDialog)

    controller = Controller(runner=_Runner(), bridge=CommandBridge(), tray=_Tray(), window=window)

    controller.on_action("rebuild", {})

    dialog = SpyProgressDialog.last
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.parent() is window
    # `window` is a real parent here, so `_start_long_op` must pick
    # WindowModal (not the parentless ApplicationModal fallback) -- pinned
    # to a single expected value per a prior review of this test.
    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    # The AppKit activation must happen before Qt's own show/raise/activate
    # sequence -- an accessory-policy app that isn't active yet won't bring
    # a newly-shown window in front of other apps otherwise.
    assert activate_calls == ["activate_app"]
    assert dialog.foreground_calls == ["show", "raise", "activate"]


def test_activate_app_for_window_is_noop_off_darwin(monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    app_module.activate_app_for_window()  # must not raise


def test_activate_app_for_window_swallows_missing_appkit_on_darwin(monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", None)  # forces ImportError on `from AppKit import`
    app_module.activate_app_for_window()  # must not raise


def test_activate_app_for_window_activates_nsapplication_on_darwin(monkeypatch):
    calls: list[bool] = []

    class _FakeNSApplication:
        @staticmethod
        def sharedApplication():
            return _FakeNSApplication()

        def activateIgnoringOtherApps_(self, flag):
            calls.append(flag)

    fake_appkit = type(sys)("AppKit")
    fake_appkit.NSApplication = _FakeNSApplication
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)

    app_module.activate_app_for_window()

    assert calls == [True]


def test_open_window_activates_app_before_showing_window(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        app_module, "activate_app_for_window", lambda: calls.append("activate_app")
    )

    class SpyWindow:
        def show(self):
            calls.append("show")

        def raise_(self):
            calls.append("raise")

        def activateWindow(self):
            calls.append("activate")

    controller = Controller(
        runner=_Runner(), bridge=CommandBridge(), tray=_Tray(), window=SpyWindow()
    )

    controller.on_action("open_window", {})

    assert calls == ["activate_app", "show", "raise", "activate"]


def test_default_confirm_high_risk_activates_app_before_message_box(qapp, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        app_module, "activate_app_for_window", lambda: calls.append("activate_app")
    )
    monkeypatch.setattr(
        app_module.QMessageBox,
        "question",
        lambda *a, **k: calls.append("question")
        or app_module.QMessageBox.StandardButton.Yes,
    )

    controller = Controller(runner=_Runner(), bridge=CommandBridge(), tray=_Tray(), window=None)

    result = controller._default_confirm_high_risk("danger", "This is risky.")

    assert result is True
    assert calls == ["activate_app", "question"]


def test_refuse_root(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert refuse_root() is True
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    assert refuse_root() is False


def test_single_instance_second_is_not_primary(qapp):
    a = SingleInstance("harnessmonkey-test-si")
    b = SingleInstance("harnessmonkey-test-si")
    assert a.is_primary is True and b.is_primary is False


def test_bridge_signals_deliver_across_threads(qtbot, qapp):
    bridge = CommandBridge()
    got: list = []
    bridge.progress_event.connect(lambda name, e: got.append((name, e)))
    import threading

    t = threading.Thread(
        target=lambda: bridge.progress_event.emit("build", {"event": "log", "line": "x"})
    )
    t.start()
    t.join()
    qtbot.waitUntil(lambda: len(got) == 1, timeout=2000)
    assert got[0][0] == "build"
