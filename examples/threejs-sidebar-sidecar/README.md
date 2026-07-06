# Three.js Sidebar Sidecar

Experimental renderer process for `packages/threejs-sidebar-sidecar`.

It primarily uses native Node `webgpu`/Dawn plus `three/webgpu` to render a modern three.js scene into an offscreen render target, reads RGBA pixels back, converts them to truecolor ANSI, defaulting to braille-cell high-definition output, and emits newline-delimited JSON frames for the patched Claude Code sidebar to consume. It keeps the old software and custom wireframe paths as fallbacks. It never writes terminal cursor movement or screen-control commands.

```bash
cd examples/threejs-sidebar-sidecar
npm install
node ./run-sidecar.js --width 80 --height 36 --fps 2 --frames 3 --scene orbit-lab --renderer webgpu --ansi braille
```

Install/runtime caveats:

- `webgpu` is a native dependency; install it on the same platform/architecture used for the smoke run. The current package target is macOS arm64 / Claude Code `2.1.201`.
- Keep `node_modules/` local and untracked. Commit `package-lock.json` when dependency versions intentionally change.
- If native WebGPU fails, use `--renderer wireframe` or `--renderer software` only as a sidecar/protocol sanity check; package readiness still requires a WebGPU manual smoke for the default path.

For HarnessMonkey manual smoke, set:

```bash
export CLAUDEMONKEY_THREE_SIDECAR_ENABLE=1
export CLAUDEMONKEY_THREE_SIDECAR=/absolute/path/to/examples/threejs-sidebar-sidecar/run-sidecar.js
export CLAUDEMONKEY_THREE_SIDECAR_RENDERER=webgpu
export CLAUDEMONKEY_THREE_SIDECAR_SCENE=orbit-lab
export CLAUDEMONKEY_THREE_SIDECAR_ANSI=braille
export CLAUDEMONKEY_THREE_SIDECAR_FPS=6
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
