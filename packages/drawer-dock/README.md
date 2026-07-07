# Drawer Dock Framework

Shared footer toolbar framework for HarnessMonkey drawer packages.


Target: Claude Code 2.1.201, darwin/arm64.

Ship set:

- `drawer-dock`
- `hidden-context-drawer`
- `thinking-drawer`
- `codex-work-drawer`
- `reminders-drawer`
- `markdown-preview-drawer`

Manual smoke is required. Verify down lands on the drawer toolbar once, left/right moves Hidden Context -> Thinking -> Codex Work -> Reminders, enter/space opens, `x` closes, Escape does not close framework drawers, only one toolbar drawer is open at a time, and Markdown Preview can overlay as a click-opened flat-content panel without a nested inner box.

## Real-target footer contract

This package owns shared real-target footer seams. It does not provide a runtime registry and must not create a synthetic drawers target.
