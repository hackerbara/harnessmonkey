# Reminders Drawer

A runtime toggle drawer for recurring reminder/accounting attachment families and blank hook-success noise — a second footer drawer alongside Hidden Context. All families are **blocked by default** (same as the static suppression package); you open the drawer mid-session and turn individual families back on or off while Claude Code runs. State is session-only.

This is a HarnessMonkey V1.5 schema-v2 package targeting `/$bunfs/root/src/entrypoints/cli.js` on Claude Code `2.1.199`.

## What it manages

Eight rows, each a checkbox row (plus a master row):

- todo reminders (`todo_reminder`)
- task reminders (`task_reminder`)
- tool search usage (`tool_search_usage_reminder`)
- token usage (`token_usage`)
- total tokens (`total_tokens_reminder`)
- budget (USD) (`budget_usd`)
- output token usage (`output_token_usage`)
- hook success (`hook_success` rows whose content is blank)

`[x]` = the reminder runs; `[ ]` = blocked (default). The master row shows `[~]` when mixed, and Enter/Space on it flips all-on/all-off. `todo_reminder` and `task_reminder` share one generator label (`todo_reminders`), so the generator is skipped only when both are blocked; otherwise it runs and the per-type filter drops just the blocked type.

The hook-success row is object/message-filter only: it blocks rows that project as just `Hook success`, while preserving contentful `hook_success` messages.

## Using it

- Arrow down in the footer past Hidden Context to reach **Reminders**.
- Enter or Space opens the drawer; then ↑/↓ move the row cursor, Enter/Space toggles the row, `x` closes.
- Toggles take effect on the next attachment cycle. Restart returns to all-blocked.

## How it composes

Deny half: two seams (`ug` label gate, `Hze` object filter) made runtime-lookups against `globalThis.__CODEX_REMINDERS_MANAGER_V1__.deny`. UI half: six seams anchored on stock text verified disjoint from `hidden-context-drawer` (v0.1.12) — a footer target, an actions-map wrapper (`__codexRMWrapActions`) for key routing, a Footer space binding, an availability-bar segment, and a panel rendered at both overlay caller sites.

- **Composes with `hidden-context-drawer`**: install either alone or both; a single build stacks them (tested).
- **Composes with `hidden-context-inline`** (disjoint `Jur` seam; tested).
- **Conflicts with `mute-reminders`**: both own the suppression seams, so a build enables one or the other, never both. Mute Reminders remains maintained as the static all-off option; this package is the runtime-toggle alternative.

## Build

Enable the package (and its `drawer-dock` dependency) and rebuild:

```bash
uv run harnessmonkey enable-patch drawer-dock
uv run harnessmonkey enable-patch reminders-drawer
uv run harnessmonkey build --activate
```

The build reaches `manual_smoke_pending` — interactive TUI smoke is required before activation.
## How it composes

Deny half: two retained seams (`_g` label wrapper gate, `XYe` object filter) made runtime-lookups against `globalThis.__CODEX_REMINDERS_MANAGER_V1__.deny`.

UI half: registered with `packages/drawer-dock`. The framework owns the footer target, left/right toolbar navigation, x close, status-bar label, and bottom overlay mount.

- Requires `drawer-dock`.
- Conflicts with `mute-reminders`; both own the reminder attachment deny/filter seam family.
- Can ship with `hidden-context-drawer` and `thinking-drawer` through the framework.

## Real-target footer contract

Reminders uses the spike-shaped __codexRMWrapActions(actions, selectedTarget) path and activates only when selectedTarget is reminders.
