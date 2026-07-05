# Hidden Context Drawer

Projects hidden/otherwise-suppressed model-visible attachment context into an integrated Claude Code footer drawer.

This is a HarnessMonkey V1.5 package targeting `/$bunfs/root/src/entrypoints/cli.js` with the graph-aware Bun repack engine. It does not patch request assembly, does not mutate transcript JSONL, and does not depend on the normal transcript renderer.

The drawer uses the projection-list seam before Claude Code filters hidden attachment rows, adds a non-preemptive `hiddenContext` footer target, and renders the opened drawer through the existing bottom overlay sibling above the composer/footer (`qnc` in Claude Code 2.1.199; this was `UXl` in the prior target).

Each drawer entry now includes:

- a compact event timestamp when the attachment row has one;
- a source label such as `attachment:hook_additional_context · hook:SessionStart`;
- a title/type label and approximate token count;
- the projected hidden/model-visible text.

This is intentionally **not** a full request viewer. It does not duplicate ordinary visible transcript/user/tool content; it audits hidden or abbreviated attachment families that are candidates for model-visible context.

Manual smoke is required: arrow down to select Hidden Context, arrow down again to open it, verify the header appears, arrow keys scroll, and x closes the drawer without using the prompt cancellation key.

## Compatibility

This package is V1.5 merge-domain compatible with non-overlapping packages such as `fable-fallback`.

It intentionally conflicts with `hidden-context-inline`: both packages own the same projection seam before Claude Code's hidden-attachment filter. Use this drawer package instead of the inline projection package when you want the integrated footer drawer UI.

## Build

Enable the package (and its `drawer-dock` dependency) and rebuild:

```bash
uv run harnessmonkey enable-patch drawer-dock
uv run harnessmonkey enable-patch hidden-context-drawer
uv run harnessmonkey build --activate
```

Then run manual smoke against the activated shim/build with
`--dangerously-skip-permissions`.

## Drawer Dock framework migration

This package is now a thin registrant for `packages/drawer-dock` targeting Claude Code 2.1.201. It keeps the Hidden Context projection/frame content seams, but the footer target, key routing, toolbar label, and bottom-overlay mount are owned by `drawer-dock`.

Build it with `--package packages/drawer-dock --package packages/hidden-context-drawer`. Build reports remain `manual_smoke_pending` until interactive footer smoke confirms x-only close and full projection-list content.

## Real-target footer contract

Hidden Context is selected through the real footer target hiddenContext. Escape is not a close affordance; x closes.
