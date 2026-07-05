# Drawer Dock Framework

Shared footer toolbar framework for HarnessMonkey drawer packages.


Target: Claude Code 2.1.201, darwin/arm64.

Ship set:

- `drawer-dock`
- `hidden-context-drawer`
- `thinking-drawer`
- `reminders-drawer`

Manual smoke is required. Verify down lands on the drawer toolbar once, left/right moves Hidden Context -> Thinking -> Reminders, enter/space opens, `x` closes, Escape does not close framework drawers, and only one drawer is open at a time.

## Real-target footer contract

This package owns shared real-target footer seams. It does not provide a runtime registry and must not create a synthetic drawers target.
