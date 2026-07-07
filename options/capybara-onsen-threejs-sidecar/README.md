# Capybara Onsen Three.js Sidecar Profile

HarnessMonkey option profile for the capybara onsen three.js sidecar scene. This option is intentionally separate from `packages/threejs-sidebar-sidecar`: the base package owns the Claude sidecar patch and renderers; this profile owns the capybara scene selection and tuned geometry.

## Contract

- Requires package: `threejs-sidebar-sidecar`
- Conflicts with renderer-only sidecar options:
  - `threejs-sidebar-sidecar-local`
  - `threejs-sidebar-sidecar-browser-webgl-chafa`
- Selects the Deno WebGPU + Chafa Eidoverse sidecar runner.
- Selects `CLAUDEMONKEY_THREE_SIDECAR_LAYOUT=two-side`.
- Uses fixed-source rendering so terminal zoom changes layout size, not the three.js camera/frustum.
- Renders the authored capybara scene at `1280x720`, crops 80 source columns per side after a 20-column outside crop, and downsamples each side to 50 visible terminal columns.

## Enable

```bash
uv run harnessmonkey enable-patch threejs-sidebar-sidecar
uv run harnessmonkey enable-option capybara-onsen-threejs-sidecar
uv run harnessmonkey build
```

## Environment owned by this profile

- `CLAUDEMONKEY_THREE_SIDECAR_ENABLE=1`
- `CLAUDEMONKEY_THREE_SIDECAR=~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/eidoverse-webgpu/run-eidoverse-scene-sidecar.sh`
- `CLAUDEMONKEY_THREE_SIDECAR_RENDERER=eidoverse-deno-webgpu`
- `CLAUDEMONKEY_THREE_SIDECAR_SCENE=eidoverse-capybara-onsen-wide`
- `CLAUDEMONKEY_THREE_SIDECAR_ANSI=chafa-vhalf`
- `CLAUDEMONKEY_THREE_SIDECAR_FPS=24`
- `CLAUDEMONKEY_THREE_SIDECAR_LAYOUT=two-side`
- `CLAUDEMONKEY_THREE_SIDECAR_SIDE_WIDTH=50`
- `CLAUDEMONKEY_THREE_SIDECAR_RIGHT_BREAKPOINT=140`
- `CLAUDEMONKEY_THREE_SIDECAR_OUTER_CROP_COLUMNS=20`
- `CLAUDEMONKEY_THREE_SIDECAR_SOURCE_SIDE_COLUMNS=80`
- `CLAUDEMONKEY_THREE_SIDECAR_RENDER_COLUMNS=400`
- `CLAUDEMONKEY_THREE_SIDECAR_SOURCE_WIDTH=1280`
- `CLAUDEMONKEY_THREE_SIDECAR_SOURCE_HEIGHT=720`
- `THREE_SIDECAR_CHAFA_BIN=/opt/homebrew/bin/chafa`
- `THREE_SIDECAR_EIDOVERSE_ROOT=/Users/MAC/Documents/eidoverse-video`
- `THREE_SIDECAR_EIDOVERSE_CONFIG=/Users/MAC/Documents/eidoverse-video/work/capybara-onsen-v2/wide-gap-scene.json`

Override the Eidoverse paths if the scene checkout lives somewhere else.
