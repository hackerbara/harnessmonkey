# Hidden context inline projection

Projects selected model-visible hidden attachment context into Claude Code's ordinary transcript renderer as warning-level system rows.

This is a HarnessMonkey V1.5 package targeting `/$bunfs/root/src/entrypoints/cli.js` with the graph-aware Bun repack engine. It does not patch request assembly and does not mutate transcript JSONL; it inserts synthetic display-only `system/codex_hidden_context` rows before Claude Code's normal hidden-attachment filter removes the original attachment records.

Initial coverage mirrors the copied-binary spike: `hook_additional_context`, `critical_system_reminder`, todo/task reminders, tool-search usage reminders, token/budget reminders, output token usage, and date changes. Rows are rendered with `level: "warning"`, which uses Claude Code's existing warning color path in the normal system renderer.

Current targets:

- Claude Code `2.1.198` (`Jlr` hidden-attachment filter seam)
- Claude Code `2.1.199` (`Jur` hidden-attachment filter seam)
