"""Pure view-models deciding everything the tray and window render.

This module is the single source of truth for what the HarnessMonkey v3 GUI
displays and which controls are enabled. It must never import a GUI toolkit
and must never perform I/O -- the Qt-based files (later tasks) are thin
renderers over these dataclasses/functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harnessmonkey.menubar_install import managed_user_target
from harnessmonkey.menubar_state import MenuState, OptionMenuItem, PatchMenuItem, PromptMenuItem

COMMON_INSTALL_TARGETS = (
    Path("/usr/local/bin/claude"),
    Path("/opt/homebrew/bin/claude"),
    Path("~/.local/bin/claude"),
)


@dataclass(frozen=True)
class NoticeModel:
    """Pure description of the shim-update-resilience notice (spec sec4).

    `message` is already de-jargoned, ready to render verbatim. `digest` is
    the `detectedOfficialSha256` this notice is *about* -- the key the
    Controller's dismissed-digest set (R5) tracks; it may be `None` (no
    digest was available when the notice was built -- today only reachable
    if the "targetReplacedByOfficial always sets a digest" invariant were to
    drift, or independently for the rollout-informational branch, which
    reads the same field). A `None` digest is still dismissable: use
    `notice_dismiss_key(notice)`, never `notice.digest` directly, to get the
    key to dismiss by or check against a dismissed set -- it substitutes a
    shared sentinel key for `None` so a digest-less notice can be dismissed
    at all (tradeoff: since the sentinel is shared, dismissing one
    digest-less notice also suppresses any *other* digest-less notice until
    a fresh GUI session -- R5's usual "per-digest, recurring" guarantee
    degrades to "per-sentinel" in this one fallback case). `actions` is a
    subset of `("repair", "rollout")`, in the order they should render; an
    empty tuple means informational-only -- no button.
    """

    message: str
    digest: str | None
    actions: tuple[str, ...]


@dataclass(frozen=True)
class TrayModel:
    status_lines: tuple[str, ...]
    running_label: str | None
    mutating_enabled: bool
    show_install_shim: bool
    prompt_items: tuple[PromptMenuItem, ...]
    patch_items: tuple[PatchMenuItem, ...]
    option_items: tuple[OptionMenuItem, ...]
    notice: NoticeModel | None = None
    # Pending-rebuild feedback (spec: "no feedback that we need to rebuild
    # to apply"): `rebuild_required` shows an extra, directly-clickable
    # "Rebuild to apply changes" menu item (`Tray._add_action`'s existing
    # "rebuild" action id); `icon_variant` picks which tray `QIcon` to show
    # (see `tray_icon_variant`/`gui/icons.py`).
    rebuild_required: bool = False
    icon_variant: str = "normal"


def _status_lines(state: MenuState) -> tuple[str, ...]:
    option_label = f"Options: {len(state.active_option_ids)} active"
    if state.high_risk_warnings:
        option_label += " ⚠"
    return (
        f"HarnessMonkey: {state.status_label}",
        f"Claude Code: {state.source_claude_version or 'unknown'}",
        f"Prompt: {state.active_prompt or 'none'}",
        option_label,
        f"Patches: {len(state.desired_patch_ids)} enabled",
    )


def mutating_controls_enabled(busy_command: str | None) -> bool:
    """Whether every mutating control should be enabled right now.

    A command is "in flight" exactly when `busy_command` (`Controller.
    _busy_command`) is not `None`. This is the single source of truth for
    that rule -- `build_tray_model` (via `TrayModel.mutating_enabled`) and
    the window/pages (via `SettingsWindow.render`'s `busy_command` param)
    both read it, so the tray and every window page (Patches/Options/
    Prompts/Install checkboxes, add/remove buttons, the rebuild button)
    always agree on which controls are safe to click. Non-mutating controls
    (page navigation, log viewing, quit) never consult this at all.
    """
    return busy_command is None


def build_tray_model(
    state: MenuState | None,
    busy_command: str | None,
    notice: NoticeModel | None = None,
) -> TrayModel:
    if state is None:
        return TrayModel(
            status_lines=("HarnessMonkey: Error",),
            running_label=None,
            mutating_enabled=False,
            show_install_shim=True,
            prompt_items=(),
            patch_items=(),
            option_items=(),
        )
    return TrayModel(
        status_lines=_status_lines(state),
        running_label=f"Running: {busy_command}" if busy_command else None,
        mutating_enabled=mutating_controls_enabled(busy_command),
        show_install_shim=not state.shim_installed,
        prompt_items=state.prompt_items,
        patch_items=state.patch_items,
        option_items=state.option_items,
        notice=notice,
        rebuild_required=state.rebuild_required,
        icon_variant=tray_icon_variant(state),
    )


# ---------------------------------------------------------------------------
# shim-update-resilience notice (spec 2026-07-04 sec4/sec5, R2/R5/R7/R8)
# ---------------------------------------------------------------------------


def _short_digest(digest: str | None) -> str | None:
    return digest[:8] if digest else None


# Sentinel dismiss-key for a notice with no `digest` (see `NoticeModel.
# digest`'s docstring for the tradeoff this shared key implies). Never
# compared against a real digest directly -- always go through `_dismiss_key`/
# `notice_dismiss_key`.
_NO_DIGEST_DISMISS_KEY = "__no_digest__"


def _dismiss_key(digest: str | None) -> str:
    return digest if digest is not None else _NO_DIGEST_DISMISS_KEY


def notice_dismiss_key(notice: NoticeModel) -> str:
    """The key to dismiss `notice` by (R5), tolerating a `None` digest.

    `settings_window.py` uses this instead of reading `notice.digest` raw
    when emitting `dismiss_notice`, so a digest-less notice is dismissable
    like any other (see `NoticeModel.digest`'s docstring).
    """
    return _dismiss_key(notice.digest)


def abbreviate_home(path: Path) -> str:
    """Render `path` home-relative (`~/...`) when it's under `Path.home()`.

    Plain-language display helper (per the de-jargon discipline this module
    already follows for status/compatibility text): every GUI surface that
    shows a filesystem path to the user routes it through here instead of
    printing the raw absolute path. Falls back to the path unchanged when it
    isn't under the home directory (e.g. `/usr/local/bin/claude`).
    """
    expanded = path.expanduser()
    home = Path.home()
    try:
        rel = expanded.relative_to(home)
    except ValueError:
        return str(expanded)
    return f"~/{rel}" if str(rel) != "." else "~"


def repair_target_path(state: MenuState | None) -> Path | None:
    """Best-available path for "what will repair-shim act on", display-only.

    Prefers the opportunistic `lastManagedTargetPath` status field
    (`MenuState.last_managed_target_path` -- a CLI-side addition landing in
    a parallel worktree; parsed if present, tolerating absence). Falls back
    to `shim_target_path` (populated only while the shim is currently
    installed, per `status.py`).

    Deliberately does NOT fall back to `detected_claude_command_path`: that
    field is a `shutil.which("claude")` PATH lookup -- a coincidental,
    possibly *different* entry point (see the GUI report's repair-target
    investigation), not the install record's actual target. Guessing with
    it would repeat the exact "guessed wrong about what had happened"
    complaint this fix exists to close.

    Today's real `status --json` (before the parallel worktree's CLI change
    lands) emits neither field in the `targetReplacedByOfficial` scenario --
    a real, reported gap -- so this returns `None` there and callers render
    generic, path-free text rather than inventing a path.
    """
    if state is None:
        return None
    return state.last_managed_target_path or state.shim_target_path


def _target_clause(state: MenuState) -> str:
    target = repair_target_path(state)
    return f" (target: {abbreviate_home(target)})" if target is not None else ""


def _repair_needed_message(state: MenuState) -> str:
    clause = _target_clause(state)
    if state.detected_official_version:
        return f"Claude {state.detected_official_version} available — shim repair needed{clause}"
    short = _short_digest(state.detected_official_sha256)
    if short:
        return f"New Claude build available ({short}…) — shim repair needed{clause}"
    return f"New Claude build available — shim repair needed{clause}"


def _rollout_message(state: MenuState) -> str:
    clause = _target_clause(state)
    if state.detected_official_version:
        return f"Claude {state.detected_official_version} available — rebuild to roll out{clause}"
    short = _short_digest(state.detected_official_sha256)
    if short:
        return f"New Claude build available ({short}…) — rebuild to roll out{clause}"
    return f"New Claude build available — rebuild to roll out{clause}"


def build_notice_model(
    state: MenuState, dismissed_digests: frozenset[str] | set[str]
) -> NoticeModel | None:
    """The single choke point deciding the shim-update-resilience notice.

    Pure function of `MenuState` (already-parsed status fields) plus the
    Controller-held set of dismissed digests (R5: in-memory, per-process --
    see the GUI report for why that's acceptable for v1). Mirrors
    `compatibility_display`'s discipline: every label here is already
    plain-language, per spec sec4 + R7's fallback rule (first 8 hex of the
    digest when the version couldn't be extracted).

    Two distinct states can produce a notice:
      - `targetReplacedByOfficial`: an official update clobbered the
        managed shim. Offers `("repair",)` when `shimRepairAvailable` is
        also true (it always should be whenever the target was replaced,
        but this never assumes that without checking -- a notice must
        never offer a button with no working action behind it).
      - Post-repair rollout required (`rolloutRequired` true while the shim
        is installed again): informational only (`actions=()`) -- there is
        no CLI-safe way to wire a rollout action today (`rebuild` does not
        consume the repair's newly cached source; see the GUI report's
        rollout investigation). Not reachable via the current, merged
        `status.py` (an installed shim always forces `rolloutRequired`
        false there today) -- modeled here anyway so the label/actions
        contract is pinned for when that gap closes.

    Returns `None` when neither state applies, or when the replacement's
    digest has already been dismissed (R5: dismissal is per-digest and
    recurring -- a new digest always re-raises the notice).
    """
    if state.target_replaced_by_official:
        digest = state.detected_official_sha256
        if _dismiss_key(digest) in dismissed_digests:
            return None
        actions = ("repair",) if state.shim_repair_available else ()
        return NoticeModel(message=_repair_needed_message(state), digest=digest, actions=actions)

    if state.rollout_required and state.shim_installed:
        digest = state.detected_official_sha256
        if _dismiss_key(digest) in dismissed_digests:
            return None
        return NoticeModel(message=_rollout_message(state), digest=digest, actions=())

    return None


_HIGH_RISK_CONFIRM_FALLBACK = "This option is high-risk."


def high_risk_confirm_text(state: MenuState | None, option_id: str) -> str:
    """Confirm-dialog body for enabling a high-risk option.

    Mirrors `repair_confirm_text`'s pattern: a pure function of `MenuState`
    (looking up `option_id` in `state.high_risk_options`, see
    `HighRiskOptionSummary`) so the exact same label+warning text renders
    regardless of which surface (tray or the window's Options page)
    triggered the confirm -- previously the window built this text itself
    (`f"{option.label}\n\n{warning}"`) while the tray's Controller-owned
    confirm only ever showed the raw warning, with no label. Falls back to
    a generic message when `state` is `None` or the option isn't found in
    `state.high_risk_options` (matches the prior `_default_confirm_high_risk`
    fallback text).
    """
    if state is not None:
        summary = next(
            (o for o in state.high_risk_options if o.option_id == option_id), None
        )
        if summary is not None:
            return f"{summary.label}\n\n{summary.warning}" if summary.warning else summary.label
    return _HIGH_RISK_CONFIRM_FALLBACK


def repair_confirm_text(state: MenuState | None) -> str:
    """Confirm-dialog body for the repair-shim action (R2: user-triggered).

    `repair-shim` has no `--dry-run`/`--progress` flags (see
    `src/harnessmonkey/cli.py`'s `repair_shim_parser`), so unlike
    `install_shim`/`uninstall_shim` there is no CLI round-trip to build this
    text from a live payload -- it is built entirely from the already-known
    `MenuState`, the same way `Controller._rebuild_confirm_text` builds
    `rebuild`'s confirm text from state instead of an extra subprocess call.
    """
    if state is None or not (state.detected_official_version or state.detected_official_sha256):
        return (
            "Repair the HarnessMonkey shim?\n\n"
            "This restores launches through PATH to go through HarnessMonkey."
        )
    if state.detected_official_version:
        detail = f"Claude {state.detected_official_version}"
    else:
        detail = f"Claude build {_short_digest(state.detected_official_sha256)}…"
    target = repair_target_path(state)
    target_sentence = (
        f" The target is {abbreviate_home(target)}." if target is not None else ""
    )
    return (
        f"Repair the HarnessMonkey shim for {detail}?\n\n"
        "This restores launches through PATH to go through HarnessMonkey."
        f"{target_sentence} "
        "The newly detected official build is cached first so it can still "
        "be rolled out later."
    )


# Refusal codes raised by `repair.py`'s `RepairRefused` (surfaced via
# `cli.py`'s `handle_repair_shim` error envelope `error.code`), plus the
# CLI-layer `missing_target` code from `cli._resolve_cache_or_repair_target`.
# Every code must map to plain language here -- see `compatibility_display`
# for the precedent this follows: internal codes must never reach the UI.
_REPAIR_REFUSAL_MESSAGES = {
    "already_installed": "The shim is already installed correctly — nothing to repair.",
    "not_managed": "HarnessMonkey has no record of managing this Claude target — repair refused.",
    "target_changed": "Claude changed again — re-checking.",
    "target_unavailable": "The Claude target is not available right now — re-checking.",
    "managed_path_refused": (
        "That target is one of HarnessMonkey's own managed paths — repair refused."
    ),
    "authorization_required": (
        "This target needs elevated permission — use Install shim instead."
    ),
    "cache_failed": "Could not cache the current Claude build — repair refused.",
    "swap_failed": "Could not install the repaired shim — repair refused.",
    "no_install_record": "HarnessMonkey has no install record for this target — repair refused.",
    "invalid_record": "HarnessMonkey's install record is unreadable — repair refused.",
    "missing_target": "No Claude target is known to repair.",
}
_REPAIR_REFUSAL_FALLBACK = "Shim repair failed."


def repair_refusal_display(code: str | None, fallback: str = _REPAIR_REFUSAL_FALLBACK) -> str:
    """Map a `repair-shim` refusal `error.code` to plain UI text.

    Every raw code from `repair.py`/`cli.py` is covered by
    `_REPAIR_REFUSAL_MESSAGES`; an unrecognized or missing code falls back
    to `fallback` rather than ever rendering the code (or a raw CLI
    exception string) verbatim -- refusal codes must never appear raw in
    the UI (plan Global Constraints).
    """
    if code is None:
        return fallback
    return _REPAIR_REFUSAL_MESSAGES.get(code, fallback)


def repair_success_display(payload: dict[str, Any]) -> str | None:
    """Banner text for a *successfully completed* repair-shim payload, or
    `None` when no banner is needed.

    A `repair-shim` completion with `ok: true` and `revertedImmediately:
    true` is the field-observed fast-revert loop: the swap genuinely
    succeeded (see `repair.py`'s docstring for `revertedImmediately`), but
    something -- observed twice on a real machine to be the official Claude
    installer's own self-heal -- already replaced the target again within
    seconds, before this very GUI round-trip finished. Without this banner,
    the app's next routine refresh would simply re-show the ordinary
    "Repair shim" notice, and the user would reasonably (but wrongly) read
    that as "the repair didn't work" -- so this must be told explicitly,
    once, right when it's known, rather than left to go silently stale.

    Every other shape (still `ok: false` -- handled separately by
    `repair_refusal_display` -- or `ok: true` with `revertedImmediately`
    false/absent, the ordinary successful-and-stable outcome) returns
    `None`: nothing new to tell the user beyond the routine refresh.
    """
    if not payload.get("ok", False):
        return None
    if not payload.get("revertedImmediately", False):
        return None
    return (
        "The shim was reinstalled, but something replaced it again within seconds"
        " — most likely the official Claude updater's own self-heal. It will keep"
        " happening until that updater is dealt with."
    )


# `handle_enable_patch` (cli.py) encodes a cascade into this exact substring
# when it auto-enables a patch's `requiresPackages` closure; nothing else in
# the CLI's patch-toggle envelopes ever emits it. Kept as a named constant
# (rather than an inline literal in both this module and its docstring) so
# the two stay in sync if the phrasing ever changes.
PATCH_CASCADE_MARKER = " (+ "


def patch_toggle_cascade_message(payload: dict[str, Any]) -> str | None:
    """Transient banner text for a `toggle_patch` success that auto-enabled
    extra packages via `requiresPackages` (the user's "when you click any of
    the things that require the thinking or the bar, that also gets
    selected" ask).

    Mirrors `repair_success_display`'s precedent: a pure function of the
    already-known JSON payload, no I/O, returning `None` whenever no extra
    banner is warranted. `cli.py`'s `handle_enable_patch` bakes the cascade
    directly into the envelope's plain-language `summary` (e.g. "enabled
    thinking-drawer (+ drawer-dock, required); rebuild required")
    -- detected here via `PATCH_CASCADE_MARKER`, a substring only that
    cascade path ever emits. An ordinary (non-cascading) enable, any
    `disable-patch` call, and any failure payload (handled instead by the
    ordinary `_quick_op_failure_message` banner path in `gui/app.py`) all
    return `None` here.
    """
    if not payload.get("ok", False):
        return None
    summary = payload.get("summary")
    if not summary or PATCH_CASCADE_MARKER not in summary:
        return None
    return summary


HEALTHY_COMPATIBILITY_STATUSES = frozenset(
    {"compatible", "unknown", "unconstrained", "constrained"}
)
_COMPATIBILITY_FALLBACK_TEXT = "Not compatible with this Claude version"


def compatibility_display(status: str, message: str | None = None) -> str:
    """Map an internal compatibility status word to UI-safe text.

    The CLI's internal status vocabulary (``compatible``, ``unknown``,
    ``unconstrained``, ``version_mismatch``, ``sha_mismatch``,
    ``constrained``, ...) must never render verbatim in the UI -- it only
    makes sense to someone who understands HarnessMonkey's internals.

    Healthy/neutral statuses render as an empty string: the row already
    shows the package name, and that's enough. ``constrained`` belongs in
    this bucket -- it only means the manifest *declares* a compatibility
    constraint, not that a check failed (actual failures surface as
    ``version_mismatch``/``sha_mismatch``). Anything else is a problem
    status, so it renders the CLI-supplied, already human-phrased
    ``message`` when one is available, or a short generic fallback when it
    isn't. This is the single place every GUI surface routes compatibility
    text through -- no caller should format ``status`` itself.
    """
    if status in HEALTHY_COMPATIBILITY_STATUSES:
        return ""
    return message or _COMPATIBILITY_FALLBACK_TEXT


def patch_notes(patch: PatchMenuItem) -> str:
    """Text for the Patches table's Notes column.

    `list-patches --json` emits an `errors` list per patch (currently always
    empty in real usage, but a real, already-parsed field -- see
    `PatchMenuItem.errors` / `menubar_state.parse_menu_state`). There is no
    description/notes/summary field in the CLI's patch payload today (see
    the GUI report's investigation); this renders exactly what exists
    (validation errors, if any) rather than inventing copy. Blank when
    there are none.
    """
    return "; ".join(patch.errors)


def option_notes(option: OptionMenuItem) -> str:
    """Text for the Options table's Notes column.

    Prefers the CLI-supplied `statusWarning` (`OptionMenuItem.status_warning`,
    parsed from `list-options --json`'s per-option `statusWarning` field --
    e.g. "Dangerous permissions enabled" for the high-risk option in real
    usage). Falls back to any validation `errors` when there's no status
    warning. Blank when neither is present -- never invents copy.
    """
    if option.status_warning:
        return option.status_warning
    return "; ".join(option.errors)


def patch_menu_label(patch: PatchMenuItem) -> str:
    if not patch.available:
        return f"{patch.label} — unavailable"
    detail = compatibility_display(patch.compatibility_status, patch.compatibility_message)
    if detail:
        return f"{patch.label} — {detail}"
    return patch.label


def patch_item_enabled(patch: PatchMenuItem, *, mutating_enabled: bool) -> bool:
    if not mutating_enabled:
        return False
    if patch.checked:
        return True
    if not patch.available:
        return False
    return patch.compatibility_status in HEALTHY_COMPATIBILITY_STATUSES


def option_item_enabled(option: OptionMenuItem, *, mutating_enabled: bool) -> bool:
    # Enabling a requires_confirmation option is allowed here; the confirm
    # dialog (owned by a later task) handles the actual high-risk gate.
    return mutating_enabled and option.valid


REBUILD_PENDING_MESSAGE = "Changes not active yet — rebuild to apply."


def rebuild_pending_banner_visible(state: MenuState | None) -> bool:
    """Whether the Patches/Options pages' pending-rebuild banner should show.

    Purely `state.rebuild_required` -- the same flag `build_tray_model`
    reads for `TrayModel.rebuild_required` and `tray_icon_variant` reads for
    the pending tray-icon variant, so the tray and every window page always
    agree about pending-rebuild state (the user's "no feedback that we need
    to rebuild to apply" complaint).
    """
    return state is not None and state.rebuild_required


def tray_icon_variant(state: MenuState | None) -> str:
    """Which tray icon `QIcon` variant to render: "normal" or "pending".

    "pending" whenever `state.rebuild_required` -- gives the pending-rebuild
    state a menu-bar-visible cue beyond the menu text, per the user's ask to
    "flash a color or invert the icon". macOS template icons are monochrome
    (see `gui/icons.py`), so a badge/dot variant is the robust choice here
    rather than a color change or inversion.
    """
    return "pending" if state is not None and state.rebuild_required else "normal"


def patch_set_label_text(state: MenuState) -> str:
    """Overview page's "Patch set: ..." label text.

    Moved out of `settings_window.py`'s `OverviewPage.render` per this
    module's everything-in-view-model rule -- the Qt side only calls
    `.setText(...)` on the already-computed string, it never formats it
    itself.
    """
    return f"Patch set: {state.active_patch_set or 'none'}"


def build_summary_label_text(state: MenuState) -> str:
    """Overview page's "Last build: ..." label text.

    Same discipline as `patch_set_label_text` -- computed here, not
    Qt-side.
    """
    modules_changed = len(state.changed_modules)
    return f"Last build: {state.last_build_strategy} ({modules_changed} module(s) changed)"


def rebuild_button_enabled(state: MenuState | None, *, mutating_enabled: bool) -> bool:
    """Whether the Overview page's "Rebuild / Apply" button should be enabled.

    Mirrors `patch_item_enabled`/`option_item_enabled`'s discipline: the page
    consumes this, it never re-derives "disconnected or busy" itself.
    """
    return state is not None and mutating_enabled


def install_button_enabled(state: MenuState | None, *, mutating_enabled: bool) -> bool:
    """Whether the Install page's "Install" button should be enabled."""
    return state is not None and mutating_enabled and not state.shim_installed


def uninstall_button_enabled(state: MenuState | None, *, mutating_enabled: bool) -> bool:
    """Whether the Install page's "Uninstall" button should be enabled."""
    return state is not None and mutating_enabled and state.shim_installed


def default_install_target(state: MenuState | None = None) -> Path:
    if state and state.shim_target_path:
        return state.shim_target_path
    if state and state.detected_claude_command_path:
        return state.detected_claude_command_path
    state_dir = state.state_dir if state else Path.home() / ".harnessmonkey"
    return managed_user_target(state_dir)


@dataclass(frozen=True)
class InstallTargetChoice:
    """One Install-page combo-box entry.

    `detected` is True for entries backed by a real signal from `status`
    (the managed user target HarnessMonkey itself owns, a recorded install,
    or a detected `claude` command) and False for a hardcoded
    `COMMON_INSTALL_TARGETS` standard-location guess. The combo previously
    rendered both the same way, which is exactly what the user couldn't
    tell apart -- see `install_target_choice_label`, which turns this flag
    (plus an on-disk existence check the Qt layer performs, since this
    module never does I/O) into the actual label text.
    """

    label: str
    target: Path
    detected: bool


def install_target_choices(state: MenuState | None) -> tuple[InstallTargetChoice, ...]:
    state_dir = state.state_dir if state else Path.home() / ".harnessmonkey"
    choices: list[InstallTargetChoice] = [
        InstallTargetChoice("Use managed user target", managed_user_target(state_dir), True),
    ]
    if state and state.shim_target_path:
        choices.append(InstallTargetChoice("Use recorded target", state.shim_target_path, True))
    if state and state.detected_claude_command_path:
        choices.append(
            InstallTargetChoice(
                "Use detected claude command", state.detected_claude_command_path, True
            )
        )
    for target in COMMON_INSTALL_TARGETS:
        choices.append(InstallTargetChoice(f"Use {target}", target, False))

    deduped: list[InstallTargetChoice] = []
    seen: set[str] = set()
    for choice in choices:
        key = str(choice.target.expanduser())
        if key not in seen:
            deduped.append(
                InstallTargetChoice(choice.label, choice.target.expanduser(), choice.detected)
            )
            seen.add(key)
    return tuple(deduped)


def install_target_choice_label(choice: InstallTargetChoice, *, exists: bool | None = None) -> str:
    """Combo-box label text for one install-target choice.

    Detected entries (`choice.detected`) render plain -- `status` already
    told us this path is real. Guesses get a short, plain-language suffix;
    an `exists=True` on-disk hit (checked by the Qt layer, since this module
    never performs I/O -- see `InstallPage._render_status`) is called out
    too, since a guess that happens to exist is meaningfully more
    trustworthy than one that doesn't.
    """
    if choice.detected:
        return choice.label
    if exists:
        return f"{choice.label} (standard location, found on disk)"
    return f"{choice.label} (standard location, not checked)"


class InstallTargetSelection:
    """Shared tray/window install-target state.

    Tracks the user's explicit choice (if any); falls back to
    `default_install_target(state)` until the user selects a path.
    """

    def __init__(self) -> None:
        self._selected: Path | None = None
        self.user_selected: bool = False

    def target(self, state: MenuState | None) -> Path:
        if self.user_selected and self._selected is not None:
            return self._selected
        return default_install_target(state)

    def select(self, path: Path) -> None:
        self._selected = Path(path).expanduser()
        self.user_selected = True


def remove_enabled(item_kind: str, package_id: str, state: MenuState) -> tuple[bool, str]:
    """Decide whether a package may be removed from the GUI.

    Mirrors the CLI/core rule (Task 6): removal is refused only when the
    active profile still references the package -- a patch in the desired
    set, the active prompt, or an enabled option. Whether the package is
    baked into the currently built/active binary does NOT block removal.

    `item_kind` is a closed set of `{"patch", "prompt", "option"}` -- the
    only kinds the real callers (options_page.py/patches_page.py/
    prompts_page.py) ever pass. An unrecognized kind raises rather than
    silently leaving `referenced` False (which would have ALLOWED removal
    for a typo'd/new kind -- the wrong failure direction for a guard).
    """
    if item_kind == "patch":
        referenced = package_id in state.desired_patch_ids
    elif item_kind == "prompt":
        referenced = package_id == state.active_prompt
    elif item_kind == "option":
        referenced = package_id in state.active_option_ids
    else:
        raise ValueError(f"unknown item kind: {item_kind!r}")

    if referenced:
        return False, f"{package_id} is referenced by the active profile; disable it first."
    return True, ""
