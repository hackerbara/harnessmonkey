# Three.js Sidebar Sidecar

Experimental HarnessMonkey infrastructure package that reserves terminal gutter space and renders live three.js frames through Claude Code's Ink raw-ANSI surface.

This base package owns the generic machinery:

1. **Claude sidecar patch** — sidecar lifecycle, ANSI frame validation, center-column sizing, and optional two-sided `frame-pair` layout support.
2. **Native WebGPU renderer** — package-local Node sidecar using `webgpu`/Dawn + `three/webgpu`, encoded directly to ANSI.
3. **Browser WebGL + Chafa renderer** — Deno Desktop CEF sidecar using real browser `THREE.WebGLRenderer`, readback to RGBA, and Chafa for high-fidelity truecolor ANSI.
4. **Deno WebGPU Eidoverse + Chafa renderer** — Deno WebGPU sidecar for Eidoverse scenes, fixed-source rendering, source-panel cropping, and Chafa `frame-pair` output.

Scene-specific profiles should live outside this base package. The capybara onsen three.js profile is the separate option package `capybara-onsen-threejs-sidecar`, which requires this package and owns its scene/profile environment.

This is still a spike. It is intentionally cursed and manually smoked.

## Runtime contract

The patched Claude Code app never lets the sidecar write to the terminal directly. The sidecar emits newline-delimited JSON frames on stdout. The parent validates complete SGR-only ANSI frames and renders the latest valid frame through `ink-raw-ansi`.

The public package carries both renderers in `sidecar/` so a normal HarnessMonkey install can place them at:

```text
~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/run-sidecar.js
~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/browser-webgl/run-sidecar-browser-webgl.sh
~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/eidoverse-webgpu/run-eidoverse-scene-sidecar.sh
```

The patch also adjusts Claude Code's terminal style pool for high-FPS truecolor animation: it doubles style capacity to 65,535 IDs by borrowing one bit from hyperlink IDs, and compacts the pool roughly every 333ms. That tradeoff caps live hyperlink IDs at 16,383. Good enough for this sidecar; not something to hide in a general-purpose patch.

## Option profiles

Enable exactly one runtime/profile option. Generic renderer profiles live beside this package; scene profiles can add their own option directory and `requiresPackages: ["threejs-sidebar-sidecar"]`.

### Native WebGPU profile

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

### Browser WebGL + Chafa profile

```bash
uv run harnessmonkey enable-patch threejs-sidebar-sidecar
uv run harnessmonkey enable-option threejs-sidebar-sidecar-browser-webgl-chafa
uv run harnessmonkey build
```

The option sets:

- `CLAUDEMONKEY_THREE_SIDECAR_ENABLE=1`
- `CLAUDEMONKEY_THREE_SIDECAR=~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/browser-webgl/run-sidecar-browser-webgl.sh`
- `CLAUDEMONKEY_THREE_SIDECAR_RENDERER=browser-webgl`
- `CLAUDEMONKEY_THREE_SIDECAR_SCENE=browser-orbit-lab`
- `CLAUDEMONKEY_THREE_SIDECAR_ANSI=chafa-vhalf`
- `CLAUDEMONKEY_THREE_SIDECAR_FPS=30`
- `THREE_SIDECAR_CHAFA_BIN=/opt/homebrew/bin/chafa`
- `THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE=offscreen`

`offscreen` is headless-ish, not true CEF offscreen rendering: it creates a non-activating frameless browser window far offscreen so WebGL can keep rendering without popping a normal window. Set `THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE=visible` if you want to see the browser reference window, or `hidden` if you want to try `BrowserWindow.hide()`.

### Scene/profile options

The base package should not own final scene choices, local asset paths, or tuned gutter/crop geometry. Put those in a separate option/profile directory that requires `threejs-sidebar-sidecar`; for the capybara onsen profile, see `options/capybara-onsen-threejs-sidecar/`.

Without a runtime option, the gutter renders a static disabled fallback. The patch helper expands `~/` against `HOME` before spawning the sidecar, so options can stay portable across user accounts.

## Sidecar dependencies

`sidecar/` contains its own `package.json` and `package-lock.json`; `node_modules/` is intentionally not committed. After installing or updating the package, install native renderer dependencies in the home copy:

```bash
cd ~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar
npm install
npm run smoke
```

Native WebGPU needs the npm `webgpu` package on the same platform/architecture used for the smoke run.

Browser WebGL + Chafa additionally needs Deno Desktop and Chafa:

```bash
brew install chafa
# install/update Deno separately, then confirm `deno desktop` is available
cd ~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/browser-webgl
./build-browser-webgl.sh
./run-sidecar-browser-webgl.sh --width 80 --height 30 --fps 30 --frames 3 --scene browser-orbit-lab --ansi chafa-vhalf
```

Deno WebGPU Eidoverse + Chafa uses the regular Deno CLI plus Chafa, and scene/profile options must provide `THREE_SIDECAR_EIDOVERSE_ROOT` and `THREE_SIDECAR_EIDOVERSE_CONFIG` for the scene checkout.

The current package target is macOS arm64 / Claude Code `2.1.201`.

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
3. For browser WebGL + Chafa, build the Deno Desktop app in `sidecar/browser-webgl` and confirm Chafa is installed.
4. Enable `threejs-sidebar-sidecar` and exactly one compatible runtime/profile option; leave conflicting side-gutter packages such as `capybara-onsen` disabled.
5. Rebuild/install the patched Claude binary.
6. Run Claude through the HarnessMonkey-managed launch path and confirm the selected scene appears live in the expected gutter layout.
7. Type in the prompt while it animates.
8. Resize the terminal.
9. Kill the sidecar and confirm the fallback appears without corrupting terminal state.
10. Exit Claude and confirm no orphan sidecar process remains.
