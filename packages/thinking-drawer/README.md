# Thinking Drawer

Projects raw and structured thinking text that Claude Code already has or receives into an integrated footer drawer.

This is a HarnessMonkey V3 patch package targeting `/$bunfs/root/src/entrypoints/cli.js` with the graph-aware Bun repack engine. The package uses the V3 package envelope while preserving the builder-compatible target/operation payload shape. It does not patch request assembly, does not mutate transcript JSONL, does not change model-visible context, and does not change the main chat renderer. It is only a pop-up layer the user can open whenever.

The drawer shows only captured thinking text:

- structured `thinking` blocks that Ctrl-O transcript mode can already show;
- live `thinking_delta.thinking` chunks when the stream exposes raw text;
- virtual/salvaged thinking blocks created during interruption.

Progress-only, signature-only, redacted-only, and estimated-token-only events are ignored for drawer rows because they are not thinking text.

The Thinking footer target is always available while the interactive footer is active. If no thinking has been captured, the drawer opens to `No thinking captured yet`. Captured entries affect unread/flash state, not whether the drawer can be opened.

This package is a standalone direct footer/overlay seam owner for Claude Code 2.1.201. It is expected to conflict with other direct footer drawer packages targeting the same source until structured splices or a reviewed footer-drawer framework exists.

Manual smoke is required: select Thinking from the footer, open it, verify entries or the empty state, scroll, and close with x. Ctrl-O transcript mode must continue to work, and normal chat must remain unchanged.

Manual smoke must also include a before/after transcript JSONL check and any available request/model-visible context preview check. Drawer-only strings such as `__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__`, `No thinking captured yet`, `thinking-available`, and `x closes` must not appear in transcript persistence, request assembly, or model-visible context.
This package is now a thin registrant for `packages/drawer-dock`. It keeps the thinking collectors and panel renderer, but the footer target, key routing, toolbar label, and bottom-overlay mount are owned by `drawer-dock`. Build it with `--package packages/drawer-dock --package packages/thinking-drawer`.

## Real-target footer contract

Thinking is a real footer target extension copied from the Hidden Context open/scroll shape. It does not register a descriptor.
