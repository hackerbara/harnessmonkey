# Three.js Sidebar Sidecar Runtime

Renderer processes for `packages/threejs-sidebar-sidecar`.

The parent patch expects newline-delimited JSON on stdout. Frame messages carry complete, validated ANSI frames as base64; sidecars must not write terminal cursor movement or screen-control commands. In two-sided layout, a renderer may emit synchronized `frame-pair` messages for independent left/right ANSI gutters.

## Renderer 1: native Node WebGPU

`run-sidecar.js` uses native Node `webgpu`/Dawn plus `three/webgpu` to render an offscreen WebGPU render target, read RGBA pixels back, convert them to ANSI, and emit NDJSON frames.

```bash
cd ~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar
npm install
node ./run-sidecar.js --width 80 --height 36 --fps 8 --frames 3 --scene orbit-lab --renderer webgpu --ansi braille
```

Renderer modes:

- `webgpu`: native Dawn-backed three.js `WebGPURenderer` render-target readback.
- `software`: old `three-software-renderer` proof path.
- `wireframe`: custom ANSI wireframe fallback.

ANSI modes:

- `braille`: high-definition 2x4 subpixel braille cells.
- `half`: truecolor upper-half-block cells.

Scene modes:

- `orbit-lab`: richer WebGPU scene with a torus-knot core, wire halo, orbital rings, satellites, trails, and star field.
- `webgl-camera-left`: ports the left/main view from the official three.js `webgl_camera` example into the Node WebGPU render-target path.
- `cube`: simple WebGPU cube sanity scene.
- `sphere` / `knot`: simple geometry variants.

## Renderer 2: browser WebGL + Chafa

`browser-webgl/run-sidecar-browser-webgl.sh` launches a packaged Deno Desktop CEF app. The browser side uses real `THREE.WebGLRenderer`, reads a `WebGLRenderTarget`, sends RGBA bytes to the Deno backend, and the backend calls Chafa for ANSI conversion.

```bash
cd ~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/browser-webgl
./build-browser-webgl.sh
THREE_SIDECAR_CHAFA_BIN=/opt/homebrew/bin/chafa \
THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE=offscreen \
./run-sidecar-browser-webgl.sh --width 80 --height 54 --fps 30 --frames 3 --scene browser-orbit-lab --ansi chafa-vhalf
```

Two-sided profiles render one full terminal-width frame and ask the backend to emit `frame-pair` messages with independently cropped left/right ANSI gutters. The parent Claude patch spawns one sidecar process for both gutters, so the two sides stay frame-synchronized. Scene-specific asset paths and final crop geometry belong in profile options, not in this base runtime README.

Browser ANSI modes:

- `chafa-vhalf`: preferred high-fidelity Chafa mode for the current terminal bridge.
- `chafa-quad` / `chafa-block`: alternate Chafa symbol sets.
- `braille`, `half`, `halftone`, `cellfit`: built-in experimental encoders retained for comparison/debugging.

Browser scene modes:

- `browser-orbit-lab`: default WebGL scene with torus-knot core, rings, satellites, and star field.
- Profile-specific wide/video scenes are selected by separate option packages that require `threejs-sidebar-sidecar`.

Window modes:

- `visible`: normal browser reference window.
- `offscreen`: non-activating frameless window positioned far offscreen. This is the default option-profile setting.
- `hidden`: calls `BrowserWindow.hide()` shortly after startup. It may throttle rendering depending on backend/OS behavior.

True CEF windowless/offscreen rendering is not exposed by this Deno Desktop spike. `offscreen` is the practical no-pop-up path for now.


## Renderer 3: Deno WebGPU Eidoverse + Chafa

`eidoverse-webgpu/run-eidoverse-scene-sidecar.sh` runs a Deno WebGPU renderer derived from the Eidoverse render pipeline. It renders a fixed source image, crops source panels, and sends Chafa-encoded ANSI `frame-pair` messages for two-sided profiles. This renderer is the path used by `capybara-onsen-threejs-sidecar`.

```bash
cd ~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/eidoverse-webgpu
THREE_SIDECAR_CHAFA_BIN=/opt/homebrew/bin/chafa \
THREE_SIDECAR_EIDOVERSE_ROOT=/Users/MAC/Documents/eidoverse-video \
THREE_SIDECAR_EIDOVERSE_CONFIG=/Users/MAC/Documents/eidoverse-video/work/capybara-onsen-v2/wide-gap-scene.json \
./run-eidoverse-scene-sidecar.sh --width 180 --height 20 --fps 1 --frames 1 \
  --layout two-side --left-width 50 --right-width 50 --ansi chafa-vhalf
```

Important geometry knobs:

- `THREE_SIDECAR_RENDER_COLUMNS`: virtual source-column grid used for crop math.
- `THREE_SIDECAR_OUTER_CROP_COLUMNS`: columns skipped from the outside edges before cropping each side.
- `THREE_SIDECAR_SOURCE_SIDE_COLUMNS`: source columns sampled per side before Chafa downsamples to visible gutter width.
- `THREE_SIDECAR_SOURCE_WIDTH` / `THREE_SIDECAR_SOURCE_HEIGHT`: fixed pixel render size; keeping this stable prevents terminal zoom from changing the three.js camera aspect.

## HarnessMonkey option profiles

Use one compatible runtime/profile option:

```bash
uv run harnessmonkey enable-option threejs-sidebar-sidecar-local
# or
uv run harnessmonkey enable-option threejs-sidebar-sidecar-browser-webgl-chafa
# or a scene/profile option that requires threejs-sidebar-sidecar
uv run harnessmonkey enable-option capybara-onsen-threejs-sidecar
```

All listed profiles require `threejs-sidebar-sidecar`; the profiles conflict with each other.
