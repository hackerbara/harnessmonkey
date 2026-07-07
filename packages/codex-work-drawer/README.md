# Codex Work Drawer

Passive observer for Claude Code 2.1.201. It reads OpenAI Codex companion job state and Codex session JSONL from local disk, then renders recent Codex assistant messages in a footer drawer.

Behavior:

- Reads current-workspace Codex companion jobs from `~/.claude/plugins/data/codex-openai-codex/state/<workspace>/`.
- Resolves job `threadId` values to `~/.codex/sessions/**/rollout-*<threadId>.jsonl` when available.
- Shows assistant messages in reverse chronological order as discrete bordered cards.
- Keeps the card body in normal text color and colors card title text to match the border.
- Collapses long assistant messages behind clickable omitted-lines rows; clicking toggles expansion.
- Caps session reads, run count, and visible message count to keep the drawer responsive.
- Display only: does not modify Codex plugin output and does not feed observed Codex output back into Claude context.

Requires `drawer-dock` to expose the real footer target and overlay chrome.
