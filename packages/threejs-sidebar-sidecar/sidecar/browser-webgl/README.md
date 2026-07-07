# Browser WebGL Sidecar Spike

Experimental Deno Desktop CEF sidecar for `threejs-sidebar-sidecar`.

This path keeps Claude Code's Ink bridge unchanged. The sidecar is a separate Deno Desktop app:

```text
Claude patched sidebar
  -> child_process.spawn(run-sidecar-browser-webgl.sh)
  -> Deno Desktop CEF app
  -> browser three.js WebGLRenderer
  -> WebGLRenderTarget pixel readback
  -> fetch POST /frame to the Deno backend
  -> existing base64-ANSI NDJSON frame protocol
```

## What worked

The reliable path is **not** `win.bind()` and not inline browser scripts.

Observed working shape:

- For development, launch Deno Desktop with `--backend cef --no-config` and an absolute `main.ts` path.
- For live use, build the `.app` and launch `dist/ThreeJsBrowserWebglSidecar.app/Contents/MacOS/laufey` through `run-sidecar-browser-webgl.sh`.
- Launch from a neutral cwd, not from inside this package directory.
- Serve HTML from `Deno.serve()`.
- Load browser code as an external `/app.js` script.
- Serve three.js build files from package-local `../node_modules/three/build/*` under `/vendor/*`.
- Browser imports `/vendor/three.module.js`, which also requests `/vendor/three.core.js`.
- Browser renders into `THREE.WebGLRenderTarget` and calls `renderer.readRenderTargetPixels(...)`.
- Browser sends raw RGBA bytes to `POST /frame` with `fetch()`.
- Deno converts RGBA to braille/half-block ANSI and emits the same NDJSON protocol as the Node sidecar.

Observed non-working / fragile shape:

- `win.bind()` registered without throwing, but renderer calls rejected with `No callback bound for: <name>`.
- Inline scripts did not execute in this local Deno Desktop CEF setup, while external `/app.js` did.
- Running `deno desktop` from inside this package directory or through discovered `deno.json` hit `Operation not permitted (os error 1)` before user code ran.
- The HMR/dev path can also hit `Operation not permitted` on local file reads; the packaged app path is the verified path.

## Build and run

Requires Deno `>= 2.9` with `deno desktop`.

```bash
cd ~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar
npm install

cd browser-webgl
./build-browser-webgl.sh
./run-sidecar-browser-webgl.sh --width 80 --height 30 --fps 30 --frames 3 --scene browser-orbit-lab --ansi chafa-vhalf
```

ANSI modes:

- `--ansi braille` renders at 2x4 pixels per terminal cell and packs lit samples into Braille dots. It has the highest spatial density, but one foreground color has to represent every lit dot in the cell.
- `--ansi half` renders at one pixel per half-block and emits truecolor `▀` cells. It is color-stable but chunkier.
- `--ansi halftone` renders/readbacks at the same 2x4 source density as Braille, then downsamples into foreground-only density glyphs (`░▒▓█`) with ordered luminance dithering and averaged chroma. It deliberately avoids `▀` + background-color encoding because that path can scanline badly if the live raw-ANSI renderer drops or underpaints cell backgrounds. Try it with:
- `--ansi cellfit` renders/readbacks at 8x8 pixels per terminal cell, summarizes each 4x4 quadrant with a trimmed-color estimator, then emits the closest 2x2 quadrant/block glyph (`▘▝▖▗▛█`, etc.) with foreground/background colors. This is the high-fidelity experiment for glossy 3D scenes: sparse specular highlights should stay local instead of expanding into whole-cell white chunks. Try it with:

```bash
./run-sidecar-browser-webgl.sh --width 80 --height 30 --fps 4 --frames 1 --scene browser-orbit-lab --ansi cellfit
```

```bash
./run-sidecar-browser-webgl.sh --width 80 --height 30 --fps 4 --frames 1 --scene browser-orbit-lab --ansi halftone
```

If the patched Claude Code helper only passes environment through, the sidecar also accepts:

```bash
CLAUDEMONKEY_THREE_SIDECAR_ANSI=halftone ./run-sidecar-browser-webgl.sh --width 80 --height 30 --fps 4 --frames 1 --scene browser-orbit-lab
```

For an uncompiled dev/HMR smoke, this exists but is currently fragile on macOS and may hit `Operation not permitted` on package-local file reads. Prefer the packaged app path above for live Claude testing.

```bash
./run-browser-webgl-dev.sh --width 80 --height 30 --fps 4 --frames 3 --scene browser-orbit-lab --ansi braille
```

The scripts set:

```bash
THREE_SIDECAR_BROWSER_WEBGL_ROOT=<browser-webgl directory>
THREE_SIDECAR_BROWSER_WEBGL_ASSET_ROOT=<parent sidecar directory>
```

That is necessary because Deno Desktop's compiled runtime sees `import.meta.url` as an embedded/cache location, not the source package directory.

## Window/headless behavior

Deno Desktop creates/adopts a browser window for the CEF renderer. This spike supports a practical no-pop-up mode:

```bash
THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE=offscreen ./run-sidecar-browser-webgl.sh --width 80 --height 30 --fps 30 --frames 3 --scene browser-orbit-lab --ansi chafa-vhalf
```

Modes:

- `visible`: normal reference window.
- `offscreen`: non-activating frameless window positioned far offscreen. This is what the HarnessMonkey Chafa option uses.
- `hidden`: calls `BrowserWindow.hide()` after startup; useful to test, but may throttle rendering.

This is not true CEF windowless rendering. It avoids the visible pop-up while still letting browser WebGL exist.

## Manual smoke evidence

A successful packaged-app smoke emits:

```json
{"type":"hello","renderer":"browser-webgl-cef","threeRevision":"185","webglRenderer":"webgl2"}
{"type":"frame","seq":1,"renderer":"browser-webgl-cef","encoding":"base64-ansi"}
```

CEF may print noisy macOS/Chromium messages such as signature validation warnings or GCM endpoint warnings. Treat the NDJSON protocol messages as the sidecar readiness signal.

## Caveats

- This is deliberately a spike. It opens a CEF desktop window because the renderer is genuinely browser-backed.
- The WebGL pixel path renders into a `THREE.WebGLRenderTarget`, avoiding canvas screenshot / `preserveDrawingBuffer` traps.
- Runtime stdout must remain NDJSON protocol frames; diagnostic browser errors are sent as protocol `error` messages.
- Keep `dist/` and Deno caches local/untracked. Commit source and scripts, not the generated `.app` bundle.
