# Markdown Preview Drawer

Intercepts local `.md` chat hyperlinks in Claude Code and opens the linked file in the shared footer drawer overlay.

This is a HarnessMonkey patch package targeting Claude Code `2.1.201` on darwin/arm64. It requires `packages/drawer-dock`, which owns the bottom overlay mount, shared drawer chrome, scroll helpers, mouse wheel handling, `g` top, and `x` close behavior.

## Behavior

- Handles local markdown targets only: `file:///.../name.md`, absolute paths, and paths relative to the current Claude project cwd.
- Leaves web URLs and non-markdown links on the existing hyperlink opener path.
- Reads at most `262144` bytes (256 KiB) from the target file and marks the drawer as truncated when the file is larger.
- Uses the shared footer drawer renderer in `flatContent` mode: markdown file lines render directly inside the outer drawer panel, without a nested single-border entry box.
- Missing/unreadable local `.md` files open an error preview in the same drawer instead of falling through to the system file opener.

## Build

Build with the framework dependency first:

```bash
uv run harnessmonkey build \
  --package packages/drawer-dock \
  --package packages/markdown-preview-drawer \
  --source /Users/MAC/.local/share/claude/versions/2.1.201 \
  --source-version 2.1.201 \
  --source-version-output "2.1.201 (Claude Code)" \
  --platform darwin \
  --arch arm64
```

## Manual smoke

Manual smoke is required because the key behavior is the live terminal hyperlink click path:

1. Run the patched Claude binary in a real terminal.
2. Cause a local markdown link such as `[notes](./notes.md)` or a `file:///.../notes.md` link to render in chat.
3. Click the link.
4. Verify the Markdown Preview drawer opens above the composer/footer.
5. Verify the preview is flat-content inside the outer drawer: no nested inner bordered box, one scroll surface only.
6. Verify up/down and mouse wheel scroll the preview, `g` jumps to top, and `x` closes.
7. Verify an `https://...` link and a non-`.md` local link still use the stock opener behavior.

## Real-target footer contract

Markdown Preview is click-opened from a hyperlink rather than selected as a permanent footer toolbar target. It still uses the Footer context for drawer-local up/down, `g`, and `x` while open. It does not register a descriptor and does not add a toolbar segment.
