# Mute reminders

Suppresses selected recurring reminder/accounting attachment families, plus blank hook-success noise, before they become Claude Code transcript rows.

This is a HarnessMonkey V1.5 schema-v2 package. It targets `/$bunfs/root/src/entrypoints/cli.js` in Bun module coordinates and relies on the Bun graph repack engine for positive-growth module splices.

Package version: `1.0.0` (V1).

## Target

- Claude Code `2.1.199 (Claude Code)`
- macOS arm64
- Source SHA-256: `e3cb61abc8a2ec7b98976cee1ffdde5a3fa755c9990bc8d688cd89290e0dcec0`

## What it suppresses

The package denies these generator labels before their generators run:

- `todo_reminders`
- `tool_search_usage_reminder`
- `total_tokens_reminder`
- `token_usage`
- `budget_usd`
- `output_token_usage`

It also filters these attachment object types before `li(...)` can wrap them as transcript rows:

- `todo_reminder`
- `task_reminder`
- `tool_search_usage_reminder`
- `token_usage`
- `total_tokens_reminder`
- `budget_usd`
- `output_token_usage`
- blank `hook_success` rows whose content is empty/whitespace

## What it does not suppress

The package intentionally leaves safety, permission, contentful hook, file-state, plan/auto-mode, team, memory, diagnostics, queued command, and user-provided file reference families intact.

## Relationship to reminders-drawer

This package is the **static all-off** option: the reminder/accounting families and blank hook-success rows are blocked unconditionally at build time. `packages/reminders-drawer` is the **runtime-toggle** alternative — same policy surface, but managed through a footer drawer while Claude Code runs. The two own the same suppression seams and therefore **conflict**: a build enables one or the other, never both. This package stays maintained as the static option.

## Why this patches upstream

Supersedes an earlier 2.1.198-era approach.

This package patches upstream generation and row construction:

1. `ug(label, generator)` returns `[]` for denied labels before the generator runs and before `tengu_attachment_compute_duration` telemetry can record denied families.
2. `Hze(...)` filters denied attachment objects before `tengu_attachments` telemetry and before `li(c,o)` creates transcript rows.
3. The hook-message yield path filters blank `hook_success` messages before they become transcript attachment rows. Contentful `hook_success` messages are preserved.

Historical transcripts are not rewritten. Existing denied rows remain in old session JSONL unless a separate transcript sanitation tool is explicitly built and run.
