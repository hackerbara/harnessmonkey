"""Qt application shell for the HarnessMonkey v3 GUI.

This module owns process-level concerns that have to exist before any
window/tray is built: refusing to run as root, enforcing a single running
instance, applying the macOS "accessory" (LSUIElement-equivalent) activation
policy, and bridging worker-thread progress events into the Qt event loop
via `CommandBridge`. It also owns `Controller`, the single `on_action`
handler that wires every tray/window intent to `CommandRunner` and the
`ProgressDialog`, and `main()`, which assembles all of the above into a
running application (see `Controller`'s docstring for the wiring contract).

Because the app runs under the accessory activation policy, every
window/dialog presentation must also call `activate_app_for_window` first
(see its docstring) -- otherwise newly-shown windows can silently open
behind whatever app currently has focus.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from harnessmonkey.gui.commands import (
    command_for_add_package,
    command_for_add_prompt_file,
    command_for_install_shim,
    command_for_option_toggle,
    command_for_patch_toggle,
    command_for_prompt,
    command_for_rebuild_apply,
    command_for_remove_package,
    command_for_repair_shim,
    command_for_uninstall_shim,
)
from harnessmonkey.gui.progress_dialog import ProgressDialog
from harnessmonkey.gui.settings_window import SettingsWindow
from harnessmonkey.gui.tray import Tray
from harnessmonkey.gui.window_model import (
    InstallTargetSelection,
    NoticeModel,
    build_notice_model,
    build_tray_model,
    high_risk_confirm_text,
    patch_toggle_cascade_message,
    repair_confirm_text,
    repair_refusal_display,
    repair_success_display,
)
from harnessmonkey.menubar_commands import CommandRunner
from harnessmonkey.menubar_state import MenuState, parse_menu_state

PUMP_INTERVAL_MS = 250

# `add_package`/`remove_package` payloads carry a "kind" ("patch"/"option"/
# "prompt"); this maps each to the settings-window sidebar page key that
# should show a failure banner for that kind.
PAGE_BY_KIND = {"patch": "patches", "option": "options", "prompt": "prompts"}


class CommandBridge(QObject):
    """Delivers `CommandRunner` progress/result events into the Qt event loop.

    `progress_event` is emitted directly by worker-thread `on_event`
    callbacks passed to `CommandRunner.run_streaming`; Qt's queued
    connection semantics (signal emitted from a non-GUI thread, received by
    a QObject that lives on the GUI thread) make that delivery thread-safe
    without any extra locking here.

    `command_finished` is emitted from `pump()`, which polls
    `runner.drain_results()` on a QTimer running on the GUI thread.
    """

    progress_event = Signal(str, dict)
    command_finished = Signal(str, dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer: QTimer | None = None

    def pump(self, runner: CommandRunner) -> QTimer:
        """Start a QTimer that drains `runner`'s finished-command queue.

        Returns the QTimer so the caller can keep a reference (parenting it
        to this QObject already keeps it alive, but callers may want to
        stop() it explicitly, e.g. in tests).
        """
        timer = QTimer(self)
        timer.setInterval(PUMP_INTERVAL_MS)
        timer.timeout.connect(lambda: self._drain(runner))
        timer.start()
        self._timer = timer
        return timer

    def _drain(self, runner: CommandRunner) -> None:
        for name, payload in runner.drain_results():
            self.command_finished.emit(name, payload)


def apply_macos_accessory_policy() -> None:
    """Hide the app from the Dock/Cmd-Tab by setting an "accessory" policy.

    Verbatim port of `HarnessMonkeyMenuBar._ensure_modal_activation_policy`
    from `menubar.py`, with an added `sys.platform` guard since this GUI
    (unlike rumps) also runs in CI/offscreen contexts on non-macOS platforms
    where the AppKit import would simply fail every time anyway.
    """
    if sys.platform != "darwin":
        return
    try:
        from AppKit import (  # type: ignore[import-not-found]
            NSApplication,
            NSApplicationActivationPolicyAccessory,
        )
    except Exception:
        return
    try:
        app = NSApplication.sharedApplication()
        if app is not None and app.activationPolicy() != NSApplicationActivationPolicyAccessory:
            app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass


def activate_app_for_window() -> None:
    """Force this process to the foreground before presenting a window.

    Companion to `apply_macos_accessory_policy`: an accessory-policy app has
    no Dock icon and, critically, is not "active" by default, so Qt's own
    `show()`/`raise_()`/`activateWindow()` on a window are not enough --
    they only reorder windows *within* an already-inactive app and the new
    window can still open behind whatever app currently has focus. Calling
    `NSApplication.activateIgnoringOtherApps_(True)` immediately before any
    such Qt call is what actually brings the process (and thus its window)
    in front of every other app. Same darwin-guard/try-except shape as
    `apply_macos_accessory_policy` for the same reasons.
    """
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication  # type: ignore[import-not-found]
    except Exception:
        return
    try:
        app = NSApplication.sharedApplication()
        if app is not None:
            app.activateIgnoringOtherApps_(True)
    except Exception:
        pass


class SingleInstance(QObject):
    """Ensures only one GUI process is active for a given `key`.

    The first instance to call `QLocalServer.listen(key)` becomes the
    `is_primary` instance and listens for connections from later launches;
    each later launch connects as a client, sends `b"raise"`, and is not
    primary (the caller is expected to exit rather than start a second GUI).

    The primary emits `activated` whenever any client connects, so the
    caller can bring its window/tray to the foreground.
    """

    activated = Signal()

    def __init__(self, key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._server: QLocalServer | None = None
        self._socket: QLocalSocket | None = None
        self.is_primary = self._claim()

    def _claim(self) -> bool:
        # Residual TOCTOU (deliberately left unfixed): the probe below
        # (connectToServer + waitForConnected) and the claim further down
        # (removeServer + listen) are not atomic across processes. Two GUI
        # launches racing in the same tiny window could both observe "no
        # live primary" during their probes, then both proceed to
        # removeServer()+listen(). Normal OS socket semantics mean at most
        # one listen() call actually succeeds -- see the "Listen failed for
        # some other reason" comment below, which already handles that loser
        # gracefully -- but the race itself is real, just practically
        # unreachable outside a near-simultaneous double-launch. No lock
        # file / atomic cross-process claim primitive is added for it: the
        # cost isn't justified for a single-user desktop app.
        #
        # Probe for a live primary first: if one is listening, connect,
        # announce ourselves, and give up primary status. We must not call
        # QLocalServer.removeServer() before this probe, since on Unix that
        # unlinks the socket path out from under an already-listening
        # primary, which would let us (wrongly) also succeed at listen().
        socket = QLocalSocket(self)
        socket.connectToServer(self._key)
        if socket.waitForConnected(1000):
            socket.write(b"raise")
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            self._socket = socket
            return False

        # No live primary answered. Clear a stale socket left behind by a
        # process that didn't shut down cleanly (e.g. killed rather than
        # quit) so listen() below doesn't fail spuriously, then claim
        # primary status.
        QLocalServer.removeServer(self._key)
        server = QLocalServer(self)
        if server.listen(self._key):
            server.newConnection.connect(self._on_new_connection)
            self._server = server
            return True

        # Listen failed for some other reason (e.g. a race against another
        # process claiming primary between our probe and our listen call).
        # Treat this instance as secondary rather than crashing.
        return False

    def _on_new_connection(self) -> None:
        server = self._server
        if server is None:
            return
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.readyRead.connect(connection.deleteLater)
            connection.disconnected.connect(connection.deleteLater)
        self.activated.emit()


def refuse_root() -> bool:
    """Port of `menubar.refuse_root_menu_process`: True if running as root."""
    return getattr(os, "geteuid", lambda: 1)() == 0


class Controller:
    """The single `on_action(action_id, payload)` handler for the whole GUI.

    Both `Tray` and `SettingsWindow` (plus its pages) funnel every user
    intent through this one entry point, using the same action-id
    vocabulary documented on those classes. `Controller` is the only piece
    of the GUI that decides *what a click means* -- it is the sole owner of
    `CommandRunner`/`CommandBridge`, the current `MenuState`, and whichever
    `ProgressDialog` (if any) is open.

    Dispatch:
      - `refresh`: fetch `status`/`list-patches`/`list-prompts`/
        `list-options` via `run_json` (non-mutating), parse into a
        `MenuState`, and push it into both `tray.render()` and
        `window.render()`. A fetch failure renders a `None` state (tray's
        error line, window's disconnected banner) rather than raising.
      - Quick ops (`toggle_patch`, `toggle_option`, `set_prompt`,
        `add_package`, `add_prompt_file`, `remove_package`): build argv via
        `gui/commands.py`, fire `runner.run_background`; the eventual
        `command_finished` triggers a `refresh()`, and an `ok: false`
        result shows an inline banner on the originating settings page.
      - Long ops (`rebuild`, `install_shim`, `uninstall_shim`): open exactly
        one `ProgressDialog` at a time regardless of trigger source (tray or
        window) -- a second long-op request while one is already open/running
        is a no-op. `install_shim`/`uninstall_shim` first run a non-mutating
        `run_json` dry-run fetch to get the real `authorizationRequired`
        flag (which gates `cancel_allowed_during_run`) and a confirm
        summary; `rebuild` has no CLI-side dry-run variant to fetch (see
        `commands.command_for_rebuild_apply`), so its confirm text is built
        from the already-known `MenuState` instead of an extra subprocess
        round trip. Once confirmed, `runner.run_streaming` is started and
        its `progress_event`/`command_finished` bridge signals drive
        `dialog.apply_event`/`dialog.finish`. `dialog.finish` is called for
        *every* terminal `command_finished` for the active long op, even a
        malformed/missing-field payload (both `ProgressModel.apply_result`
        and `ProgressDialog.finish` already tolerate that defensively), so a
        dialog is never stranded mid-RUNNING.
      - `toggle_option`'s high-risk confirm is unified across both
        emitters (Item 1 fix -- this used to diverge: the window's Options
        page ran its own confirm `QMessageBox`, built from `f"{label}\n\n
        {warning}"`, with no way for the tray to show the same dialog,
        since the tray has no confirm-dialog UI of its own). Both the tray
        and the window's Options page now emit the exact same shape --
        `requires_confirmation` is always a static flag, never a
        page-owned `QMessageBox` result -- so `_action_toggle_option`'s
        single `"requires_confirmation" in payload` branch handles both
        surfaces identically: when turning a `requires_confirmation`
        option ON, `Controller` is the sole place that ever shows the
        confirm prompt (`confirm_high_risk`, text built by
        `window_model.high_risk_confirm_text` from `MenuState.
        high_risk_options`, so the same label+warning text renders
        regardless of trigger). The payload's `confirmed` key is a
        still-supported legacy translation path (kept for the
        injected-confirm-callable test shape / any external caller that
        already ran its own confirm), but no real emitter sends it
        anymore. A declined confirm now also calls `self.refresh()` before
        returning -- since neither surface reverts its own checkbox/
        checkmark widget state anymore, this is what corrects whatever Qt
        already flipped on click, by re-rendering both tray and window
        from the true (unchanged) `MenuState`.
      - `open_path` -> `runner.open_path`. `quit` cancels any live
        streaming handle and calls `quit_callback` (defaults to
        `QApplication.quit`).
      - `repair_shim` (shim-update-resilience notice, spec sec4/sec5):
        neither a quick op nor a long op in the existing sense --
        `repair-shim` (see `commands.command_for_repair_shim`) has no
        `--dry-run`/`--progress` flags in `cli.py`, so there is no dry-run
        payload to fetch and no progress stream to bridge into a
        `ProgressDialog`. Instead: `confirm_repair` (same
        injectable-callable shape as `confirm_high_risk`) gates the
        mutation with text from `window_model.repair_confirm_text`, then
        the real command runs through the ordinary quick-op path
        (`run_background`, page `"overview"`). A refusal is mapped through
        `window_model.repair_refusal_display` before it ever reaches
        `window.show_banner` -- raw `RepairRefused` codes (`target_changed`,
        `already_installed`, `authorization_required`, ...) must never
        reach the UI. `dismiss_notice` is pure Controller state (R5: an
        in-memory, per-digest dismissed set) -- no CLI call, just a
        `_render_notice()` re-push to tray/window.

    Every window/dialog `Controller` presents (`show_window`,
    `_show_dialog_foreground`'s `ProgressDialog`, `_default_confirm_high_risk`'s
    `QMessageBox`) calls `activate_app_for_window()` immediately beforehand,
    then still does the Qt-side `show()`/`raise_()`/`activateWindow()` (or,
    for a `QMessageBox`/`QFileDialog` static call, relies on Qt's own modal
    foregrounding) -- the AppKit activation is what makes those Qt calls
    actually land in front of other apps rather than behind them, and
    `ProgressDialog`'s modality is `WindowModal` when parented to `window`,
    `ApplicationModal` otherwise.
    """

    def __init__(
        self,
        *,
        runner: CommandRunner,
        bridge: CommandBridge,
        tray: Any,
        window: Any,
        confirm_high_risk: Callable[[str, str], bool] | None = None,
        confirm_repair: Callable[[str], bool] | None = None,
        quit_callback: Callable[[], None] | None = None,
    ) -> None:
        self.runner = runner
        self.bridge = bridge
        self.tray = tray
        self.window = window
        self._confirm_high_risk = confirm_high_risk or self._default_confirm_high_risk
        self._confirm_repair = confirm_repair or self._default_confirm_repair
        self._quit_callback = quit_callback or self._default_quit

        self._state: MenuState | None = None
        self._busy_command: str | None = None
        self._install_selection = InstallTargetSelection()
        # R5: dismissable-but-recurring notice state. In-memory/per-process
        # is a deliberate v1 choice (see GUI report) -- a digest dismissed in
        # one GUI session simply re-raises after a restart, which is
        # preferable to a persisted dismissal silently hiding a *future*,
        # different official update forever if the persistence keying ever
        # drifted.
        self._dismissed_digests: set[str] = set()

        self._dialog: ProgressDialog | None = None
        self._handle: Any | None = None
        self._long_op: str | None = None
        self._pending_quick_pages: dict[str, str] = {}

        bridge.command_finished.connect(self._on_command_finished)
        bridge.progress_event.connect(self._on_progress_event)

    # -- action dispatch -----------------------------------------------------

    def on_action(self, action_id: str, payload: dict[str, Any]) -> None:
        handler = getattr(self, f"_action_{action_id}", None)
        if handler is None:
            return
        handler(payload)

    def _action_refresh(self, payload: dict[str, Any]) -> None:
        self.refresh()

    def _action_open_window(self, payload: dict[str, Any]) -> None:
        self.show_window()

    def _action_quit(self, payload: dict[str, Any]) -> None:
        if self._handle is not None:
            self._handle.cancel()
        self._quit_callback()

    def _action_open_path(self, payload: dict[str, Any]) -> None:
        path = payload.get("path")
        if path:
            self.runner.open_path(Path(path))

    def _action_set_install_target(self, payload: dict[str, Any]) -> None:
        path = payload.get("path")
        if path:
            self._install_selection.select(Path(path))

    def _action_toggle_patch(self, payload: dict[str, Any]) -> None:
        patch_id = payload["patch_id"]
        enabled = bool(payload.get("enabled", False))
        argv = command_for_patch_toggle(patch_id, enabled=enabled)
        self._run_quick("toggle_patch", argv, page="patches")

    def _action_set_prompt(self, payload: dict[str, Any]) -> None:
        argv = command_for_prompt(payload.get("prompt_id"))
        self._run_quick("set_prompt", argv, page="prompts")

    def _action_toggle_option(self, payload: dict[str, Any]) -> None:
        option_id = payload["option_id"]
        enabled = bool(payload.get("enabled", False))

        if "requires_confirmation" in payload:
            # Unified shape (Item 1): both the tray and the window's Options
            # page emit this now -- `requires_confirmation` is a static
            # flag, neither surface has (or shows) a confirm dialog of its
            # own, so if the user is turning a high-risk option ON
            # (currently disabled), Controller is the sole place that runs
            # the confirm prompt.
            requires_confirmation = bool(payload["requires_confirmation"])
            confirm = False
            if requires_confirmation and not enabled:
                text = high_risk_confirm_text(self._state, option_id)
                if not self._confirm_high_risk(option_id, text):
                    # Neither emitter reverts its own checkbox/checkmark on
                    # decline anymore -- re-render both surfaces from the
                    # true (unchanged) MenuState to correct whatever Qt
                    # already flipped on click.
                    self.refresh()
                    return
                confirm = True
        else:
            # Legacy translation path: an already-confirmed payload from a
            # caller that ran its own confirm flow before emitting (no real
            # emitter does this anymore -- kept so the shape stays
            # supported).
            confirm = bool(payload.get("confirmed", False))

        argv = command_for_option_toggle(option_id, enabled=enabled, confirm=confirm)
        self._run_quick("toggle_option", argv, page="options")

    def _action_add_package(self, payload: dict[str, Any]) -> None:
        kind = payload["kind"]
        argv = command_for_add_package(payload["path"], kind)
        self._run_quick("add_package", argv, page=PAGE_BY_KIND[kind])

    def _action_add_prompt_file(self, payload: dict[str, Any]) -> None:
        argv = command_for_add_prompt_file(
            payload["path"], payload["package_id"], payload.get("name")
        )
        self._run_quick("add_prompt_file", argv, page="prompts")

    def _action_remove_package(self, payload: dict[str, Any]) -> None:
        kind = payload["kind"]
        argv = command_for_remove_package(payload["package_id"], kind)
        self._run_quick("remove_package", argv, page=PAGE_BY_KIND[kind])

    def _action_rebuild(self, payload: dict[str, Any]) -> None:
        self._start_long_op(
            name="rebuild",
            title="Rebuild / Apply",
            confirm_button="Rebuild",
            real_argv=command_for_rebuild_apply(),
            dry_run_argv=None,
            confirm_text=self._rebuild_confirm_text(),
            page="overview",
        )

    def _action_install_shim(self, payload: dict[str, Any]) -> None:
        target = self._install_selection.target(self._state)
        self._start_long_op(
            name="install_shim",
            title="Install shim",
            confirm_button="Install",
            real_argv=command_for_install_shim(target, dry_run=False),
            dry_run_argv=command_for_install_shim(target, dry_run=True),
            page="install",
        )

    def _action_repair_shim(self, payload: dict[str, Any]) -> None:
        # R2: repair is user-triggered only -- an explicit confirm dialog
        # always gates the mutation, regardless of whether the trigger came
        # from the tray's "Repair shim..." item or the window's notice
        # banner (both funnel into this one handler). Unlike
        # `_action_install_shim`/`_action_uninstall_shim`, there is no
        # dry-run round trip to build this text from: `repair-shim` has no
        # `--dry-run` flag (see `commands.command_for_repair_shim`'s
        # docstring), so the confirm text is built straight from the
        # already-known `MenuState`, the same way `_rebuild_confirm_text`
        # does for `rebuild`.
        if self._busy_command is not None:
            return
        message = repair_confirm_text(self._state)
        if not self._confirm_repair(message):
            return
        argv = command_for_repair_shim()
        self._run_quick("repair_shim", argv, page="overview")

    def _action_dismiss_notice(self, payload: dict[str, Any]) -> None:
        # R5: dismissal is keyed per-digest and recurring -- it only
        # suppresses the notice for the exact `detectedOfficialSha256` it
        # was raised for; a later, different digest re-raises it. No CLI
        # call: dismissal is pure Controller-held UI state.
        digest = payload.get("digest")
        if digest:
            self._dismissed_digests.add(digest)
        self._render_notice()

    def _action_uninstall_shim(self, payload: dict[str, Any]) -> None:
        # Prefer the recorded install target over the (forward-looking)
        # install-target selection: uninstall should act on what's actually
        # installed. If neither is known, omit --target/--record entirely so
        # the CLI falls back to its own default install-record.json.
        target = self._state.shim_target_path if self._state is not None else None
        kwargs: dict[str, Any] = {"target": target} if target is not None else {}
        self._start_long_op(
            name="uninstall_shim",
            title="Uninstall shim",
            confirm_button="Uninstall",
            real_argv=command_for_uninstall_shim(dry_run=False, **kwargs),
            dry_run_argv=command_for_uninstall_shim(dry_run=True, **kwargs),
            page="install",
        )

    # -- refresh ---------------------------------------------------------

    def refresh(self) -> None:
        try:
            status_raw = self.runner.run_json(["status", "--json"], mutating=False)
            patches_raw = self.runner.run_json(["list-patches", "--json"], mutating=False)
            prompts_raw = self.runner.run_json(["list-prompts", "--json"], mutating=False)
            options_raw = self.runner.run_json(["list-options", "--json"], mutating=False)
            state = parse_menu_state(status_raw, patches_raw, prompts_raw, options_raw)
        except Exception:
            self._state = None
            self.window.render(None, self._busy_command)
            self._render_notice()
            return

        self._state = state
        self.window.render(state, self._busy_command)
        self._render_notice()

    def _render_notice(self) -> NoticeModel | None:
        """Recompute the shim-update-resilience notice and push it to both
        the tray (as part of a fresh `TrayModel`) and the window (via
        `render_notice`), from `self._state` and the current dismissed-digest
        set. Shared by `refresh()` and `_action_dismiss_notice` so dismissing
        a notice re-renders both surfaces without an extra CLI round trip.
        """
        notice = (
            build_notice_model(self._state, frozenset(self._dismissed_digests))
            if self._state is not None
            else None
        )
        self.tray.render(build_tray_model(self._state, self._busy_command, notice=notice))
        self.window.render_notice(notice, self._busy_command)
        return notice

    def show_window(self) -> None:
        activate_app_for_window()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _dialog_parent(self) -> QWidget | None:
        if isinstance(self.window, QWidget):
            return self.window
        active_window = QApplication.activeWindow()
        return active_window if isinstance(active_window, QWidget) else None

    def _show_dialog_foreground(self, dialog: QWidget) -> None:
        activate_app_for_window()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    # -- quick ops ---------------------------------------------------------

    def _run_quick(self, name: str, argv: list[str], *, page: str) -> None:
        if self._busy_command is not None:
            return
        self._busy_command = name
        self._pending_quick_pages[name] = page
        # Push a synchronous busy re-render to window/tray *before* the
        # background command is fired -- this is the actual click-race the
        # busy gating exists to protect (click a quick-op button, then
        # immediately click something else before it finishes). Reuse the
        # already-cached `self._state` from the last `refresh()` rather than
        # firing a fresh CLI status fetch; if nothing has been fetched yet
        # (e.g. the very first action before any refresh ever ran), there is
        # no state to protect a render with, so skip the push rather than
        # rendering a bogus `None` state as busy.
        if self._state is not None:
            self.window.render(self._state, self._busy_command)
            self._render_notice()
        self.runner.run_background(name, argv, mutating=True)

    # -- long ops ---------------------------------------------------------

    def _rebuild_confirm_text(self) -> str:
        state = self._state
        if state is None:
            return "Rebuild and activate Claude Code with the current selection."
        return (
            "Rebuild and activate Claude Code.\n"
            f"Patches: {len(state.desired_patch_ids)} enabled\n"
            f"Prompt: {state.active_prompt or 'none'}\n"
            f"Options: {len(state.active_option_ids)} active"
        )

    def _confirm_text_from_payload(self, payload: dict[str, Any]) -> str:
        summary = payload.get("summary") or ""
        actions = payload.get("plannedActions") or []
        if actions:
            bullets = "\n".join(f"- {action}" for action in actions)
            return f"{summary}\n\n{bullets}" if summary else bullets
        return summary or "Continue?"

    def _start_long_op(
        self,
        *,
        name: str,
        title: str,
        confirm_button: str,
        real_argv: list[str],
        dry_run_argv: list[str] | None,
        page: str,
        confirm_text: str = "",
    ) -> None:
        # Exactly one open ProgressDialog at a time, regardless of trigger
        # source (tray vs window) -- a busy Controller (quick or long op)
        # simply ignores a second long-op request.
        if self._busy_command is not None or self._dialog is not None:
            return

        cancel_allowed_during_run = True
        if dry_run_argv is not None:
            try:
                payload = self.runner.run_json(dry_run_argv, mutating=False)
            except Exception as exc:
                self.window.show_banner(page, str(exc))
                return
            if not payload.get("ok", False):
                self.window.show_banner(page, payload.get("summary") or "command failed")
                return
            cancel_allowed_during_run = not bool(payload.get("authorizationRequired", False))
            confirm_text = self._confirm_text_from_payload(payload)

        parent = self._dialog_parent()
        dialog = ProgressDialog(
            title=title,
            confirm_text=confirm_text,
            confirm_button=confirm_button,
            cancel_allowed_during_run=cancel_allowed_during_run,
            parent=parent,
        )
        dialog.setWindowModality(
            Qt.WindowModality.WindowModal
            if parent is not None
            else Qt.WindowModality.ApplicationModal
        )
        dialog.confirmed.connect(lambda: self._on_long_op_confirmed(name, real_argv))
        dialog.cancel_requested.connect(self._on_long_op_cancel)
        dialog.open_path_requested.connect(lambda path: self.runner.open_path(Path(path)))

        self._dialog = dialog
        self._long_op = name
        self._busy_command = name
        self._show_dialog_foreground(dialog)

    def _on_long_op_confirmed(self, name: str, argv: list[str]) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        dialog.start_running()
        try:
            handle = self.runner.run_streaming(
                name, argv, on_event=lambda event: self.bridge.progress_event.emit(name, event)
            )
        except Exception as exc:
            error_payload = {"schemaVersion": 1, "ok": False, "summary": str(exc)}
            dialog.finish(error_payload, report_path=None, logs_dir=str(self.runner.logs_dir))
            self._dialog = None
            self._handle = None
            self._long_op = None
            self._busy_command = None
            self.refresh()
            return
        self._handle = handle

    def _on_long_op_cancel(self) -> None:
        if self._handle is not None:
            # RUNNING phase: terminate the subprocess; the eventual
            # `command_finished` still drives `dialog.finish` so the dialog
            # is never left stranded mid-RUNNING.
            self._handle.cancel()
            return
        # CONFIRM phase: nothing has been started yet, so just tear the
        # dialog down.
        if self._dialog is not None:
            self._dialog.close()
        self._dialog = None
        self._long_op = None
        self._busy_command = None

    # -- bridge signal handlers --------------------------------------------

    def _on_command_finished(self, name: str, payload: dict[str, Any]) -> None:
        if self._long_op is not None and name == self._long_op:
            self._finish_long_op(payload)
            return

        self._busy_command = None
        page = self._pending_quick_pages.pop(name, None)
        if not payload.get("ok", True) and page is not None:
            self.window.show_banner(page, self._quick_op_failure_message(name, payload))
        elif name == "repair_shim" and page is not None:
            # Fix 2: `ok: true` with `revertedImmediately: true` is still a
            # success (the swap DID succeed) -- but the field-observed
            # fast-revert loop means it's already stale by the time this
            # very callback runs, so tell the user now rather than letting
            # the next routine refresh silently re-show the ordinary
            # "Repair shim" notice with no explanation of what just happened.
            message = repair_success_display(payload)
            if message is not None:
                self.window.show_banner(page, message)
        elif name == "toggle_patch" and page is not None:
            # Dogfood fix: enabling a patch that `requiresPackages` another
            # one (drawer-dock) must give visible feedback that the
            # dependency was auto-enabled too -- the checked row alone
            # (after `refresh()` below) isn't enough; see
            # `patch_toggle_cascade_message`'s docstring.
            message = patch_toggle_cascade_message(payload)
            if message is not None:
                self.window.show_banner(page, message)
        self.refresh()

    def _quick_op_failure_message(self, name: str, payload: dict[str, Any]) -> str:
        summary = payload.get("summary") or "command failed"
        if name != "repair_shim":
            return summary
        # Refusal codes must never appear raw in the UI (plan Global
        # Constraints) -- repair-shim's own `RepairRefused.code` is mapped
        # through `repair_refusal_display` the same way `compatibility_display`
        # maps compatibility status words. `target_changed` in particular
        # reads as "Claude changed again -- re-checking" per spec R3 (an
        # abort here is a fresh detection round, not an error) -- the
        # unconditional `self.refresh()` call below already re-runs
        # detection every time, satisfying "trigger a refresh".
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        return repair_refusal_display(code, summary)

    def _finish_long_op(self, payload: dict[str, Any]) -> None:
        dialog = self._dialog
        if dialog is not None:
            report_path = payload.get("reportPath") if isinstance(payload, dict) else None
            dialog.finish(payload, report_path=report_path, logs_dir=str(self.runner.logs_dir))
        self._dialog = None
        self._handle = None
        self._long_op = None
        self._busy_command = None
        self.refresh()

    def _on_progress_event(self, name: str, event: dict[str, Any]) -> None:
        if self._dialog is not None and name == self._long_op:
            self._dialog.apply_event(event)

    # -- high-risk option confirm ------------------------------------------

    def _default_confirm_high_risk(self, option_id: str, text: str) -> bool:
        # `text` is already the fully-built confirm-dialog body
        # (`window_model.high_risk_confirm_text`, label + warning, with its
        # own generic fallback) -- this never re-derives or falls back on
        # its own. `option_id` is accepted only to keep the injectable
        # `Callable[[str, str], bool]` shape (same as before this change).
        parent = self._dialog_parent()
        activate_app_for_window()
        answer = QMessageBox.question(
            parent,
            "Confirm high-risk option",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _default_confirm_repair(self, message: str) -> bool:
        parent = self._dialog_parent()
        activate_app_for_window()
        answer = QMessageBox.question(
            parent,
            "Repair shim",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    @staticmethod
    def _default_quit() -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()


def build_runner() -> CommandRunner:
    # Always drive the CLI via this process's own interpreter (`python -m
    # harnessmonkey`) rather than a bare `harnessmonkey` PATH lookup: the
    # GUI must stay version-locked to its own venv/code and must not depend
    # on `harnessmonkey` being installed on the user's PATH.
    return CommandRunner(
        cli_argv=[sys.executable, "-m", "harnessmonkey"],
        logs_dir=Path.home() / ".harnessmonkey" / "logs",
    )


def main() -> int:
    if refuse_root():
        print(
            "refusing to run harnessmonkey GUI as root; start it as your user",
            file=sys.stderr,
        )
        return 1

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    apply_macos_accessory_policy()

    instance = SingleInstance(f"harnessmonkey-gui-{os.getuid()}")
    if not instance.is_primary:
        print("harnessmonkey GUI is already running")
        return 0

    runner = build_runner()
    bridge = CommandBridge()

    window = SettingsWindow()

    controller_holder: dict[str, Controller] = {}

    def _dispatch(action_id: str, payload: dict[str, Any]) -> None:
        controller_holder["controller"].on_action(action_id, payload)

    tray = Tray(on_action=_dispatch)
    controller = Controller(runner=runner, bridge=bridge, tray=tray, window=window)
    controller_holder["controller"] = controller

    window.action.connect(controller.on_action)
    window.refresh_requested.connect(controller.refresh)
    instance.activated.connect(controller.show_window)

    # Stash everything on `app` so it isn't garbage collected once `main`'s
    # local scope would otherwise go away, and so it's inspectable (e.g. in
    # a future test or a debugger) the same way `runner`/`bridge` already
    # were before this task.
    app.runner = runner  # type: ignore[attr-defined]
    app.bridge = bridge  # type: ignore[attr-defined]
    app.single_instance = instance  # type: ignore[attr-defined]
    app.tray = tray  # type: ignore[attr-defined]
    app.window = window  # type: ignore[attr-defined]
    app.controller = controller  # type: ignore[attr-defined]

    tray.icon.show()
    bridge.pump(runner)
    controller.refresh()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
