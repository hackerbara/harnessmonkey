# Three.js Sidebar Sidecar

Experimental HarnessMonkey package that reserves an 80-column left gutter and renders live WebGPU-rendered ANSI frames from a package-local three.js sidecar process. The current spike default is a richer `orbit-lab` scene rendered through native Node WebGPU readback and encoded as high-definition braille ANSI.

This is a spike. It is intentionally cursed and manually smoked.

## Runtime contract

The patched Claude Code app never lets the sidecar write to the terminal directly. The sidecar emits newline-delimited JSON frames on stdout. The parent validates complete SGR-only ANSI frames and renders the latest valid frame through `ink-raw-ansi`.

The public package carries the renderer in `sidecar/` so a normal HarnessMonkey install can place it at:

```text
~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/run-sidecar.js
```

Enable the companion option package `threejs-sidebar-sidecar-local` to inject the required runtime environment:

```bash
uv run harnessmonkey enable-patch threejs-sidebar-sidecar
uv run harnessmonkey enable-option threejs-sidebar-sidecar-local
uv run harnessmonkey build
```

The option sets:

- `CLAUDEMONKEY_THREE_SIDECAR_ENABLE=1`
- `CLAUDEMONKEY_THREE_SIDECAR=~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/run-sidecar.js`
- `CLAUDEMONKEY_THREE_SIDECAR_RENDERER=webgpu`
- `CLAUDEMONKEY_THREE_SIDECAR_SCENE=orbit-lab`
- `CLAUDEMONKEY_THREE_SIDECAR_ANSI=braille`
- `CLAUDEMONKEY_THREE_SIDECAR_FPS=8`

Without those variables, the gutter renders a static disabled fallback. The patch helper expands `~/` against `HOME` before spawning the sidecar, so the option can stay portable across user accounts.

## Sidecar dependencies

`sidecar/` contains its own `package.json` and `package-lock.json`; `node_modules/` is intentionally not committed. After installing or updating the package, install native renderer dependencies in the home copy:

```bash
cd ~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar
npm install
npm run smoke
```

`webgpu` is a native dependency; install it on the same platform/architecture used for the smoke run. The current package target is macOS arm64 / Claude Code `2.1.201`.

## Target

- Claude Code `2.1.201`, Darwin arm64.
- Module: `/$bunfs/root/src/entrypoints/cli.js`.
- Same physical side-gutter seam family as `capybara-onsen`; mutually exclusive with other full-frame cosmetic side-gutter packages.
- The manifest declares manual smoke as required because validation cannot prove terminal rendering, resize behavior, prompt input while animating, sidecar crash recovery, or process cleanup.

## Validation

Run package validation before treating the package as build-ready:

```bash
uv run harnessmonkey validate-package \
  --source /Users/MAC/.local/share/claude/versions/2.1.201 \
  --package packages/threejs-sidebar-sidecar \
  --source-version 2.1.201 \
  --source-version-output '2.1.201 (Claude Code)' \
  --platform darwin \
  --arch arm64
```

Expected validation output is `ok=true`. A green validation only proves manifest/source/package consistency; it does not replace the manual smoke checklist below.

## Manual smoke

1. Install/sync the repo packages and options into `~/.harnessmonkey`.
2. Run `npm install` from `~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar` and confirm `node_modules/` stays untracked.
3. Enable `threejs-sidebar-sidecar` and `threejs-sidebar-sidecar-local`; leave conflicting side-gutter packages such as `capybara-onsen` disabled.
4. Rebuild/install the patched Claude binary.
5. Run Claude through the HarnessMonkey-managed launch path and confirm a live WebGPU-rendered `orbit-lab` scene appears in the left gutter.
6. Type in the prompt while it animates.
7. Resize the terminal.
8. Kill the sidecar and confirm the fallback appears without corrupting terminal state.
9. Exit Claude and confirm no orphan sidecar process remains.
