# Live Three.js BrowserWebGL Sidecar Design

## Purpose

Build a HarnessMonkey profile that gives Claude Code a live three.js visualization sidebar backed by the existing Deno BrowserWebGL + Chafa sidecar. The scene must be a writable JavaScript file under `~/.claude`, not JSON state and not an intermediate scene description. A coding agent can replace or edit that file, and the running sidecar reloads it in-place on a short poll interval.

The default scene must be the current full Capybara Onsen three.js scene ported to WebGL with as little scene rewriting as possible. The port should preserve the authored actors, camera, timing, names, and animation structure from `/Users/MAC/Documents/eidoverse-video/work/capybara-onsen-v2/wide-gap-scene.js`. The work is to adapt the renderer/helper substrate from WebGPU/TSL/Eidoverse to BrowserWebGL, not to rebuild an approximate scene.

The feature also needs a general runtime bridge for hidden system reminders. The startup reminder should tell the Claude agent that it is running inside an experimental live three.js visualization harness and can update the live scene file. The bridge must support arbitrary sidecar-originated reminders later, even though automatic “scene updated” reminders are out of scope for the first implementation.

## Current Evidence

The existing `threejs-sidebar-sidecar` package already owns the terminal layout and NDJSON frame bridge. Its README describes the base package as owning sidecar lifecycle, frame validation, center-column sizing, and optional two-sided `frame-pair` layout. It also explicitly includes a Deno Desktop BrowserWebGL + Chafa renderer using real `THREE.WebGLRenderer`, RGBA readback, and Chafa truecolor ANSI conversion.

The current BrowserWebGL sidecar has the right render/readback loop: browser code imports `/vendor/three.module.js`, creates `THREE.WebGLRenderer`, renders a `THREE.WebGLRenderTarget`, calls `renderer.readRenderTargetPixels(...)`, and POSTs the raw pixels to `/frame`. The Deno backend converts those pixels to ANSI and emits the existing frame protocol.

The current Capybara three.js option is pointed at the Deno WebGPU/Eidoverse sidecar, not BrowserWebGL. The current BrowserWebGL Capybara path is only a video-texture workaround: `createScene()` routes `eidoverse-capybara-onsen-wide` to a function that maps `/eidoverse/capybara-wide.mp4` onto a plane. This must be replaced by a live JavaScript scene load.

The existing Capybara TUI package already demonstrates the desired model-message bridge. It registers `__coCapyNoteSink` beside Claude Code's session-name bridge and appends `ki({type:"critical_system_reminder",content:ft})`. Tests document that `critical_system_reminder` is hidden in the stock UI, surfaced by hidden-context packages, forwarded to model context as `<system-reminder>`, and preserved across `/resume`. The new sidecar must generalize that exact bridge seam rather than use launch prompt packages.

The current rich Capybara scene is not a rewrite candidate. Most of it is ordinary three.js: capybara actors, bamboo, yuzu, lantern, stones, lights, camera drift, breathing, ear flicks, water drops, and floating props. The bounded WebGPU/TSL surfaces are renderer construction/rendering, browser-incompatible addon imports, NodeMaterial constructors, node opacity uniforms, `scene.environmentNode`, WebGPU `water_compute.js`, and TSL `makeParticles`.

## Non-goals

- Do not introduce JSON scene state.
- Do not keep the video-texture Capybara path as the real Capybara implementation.
- Do not use launch prompt packages or profile prompt files for runtime messages.
- Do not rebuild an inspired Capybara facsimile from scratch.
- Do not auto-send “scene updated” reminders on file reload in the first cut.
- Do not expose a browser HTTP endpoint that lets arbitrary scene code append hidden system reminders.
- Do not let arbitrary terminal control output reach Claude; sidecar stdout remains validated NDJSON only.

## Target User Surface

A first-run profile creates or reuses:

```text
~/.claude/harnessmonkey/threejs/scene.js
~/.claude/harnessmonkey/threejs/assets/
```

The `capybara-onsen-threejs-sidecar` option should be updated in place to use BrowserWebGL live JS, not the rejected Deno WebGPU sidecar. Its env should select the existing BrowserWebGL runner and a live scene mode:

```text
CLAUDEMONKEY_THREE_SIDECAR_ENABLE=1
CLAUDEMONKEY_THREE_SIDECAR=~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/browser-webgl/run-sidecar-browser-webgl.sh
CLAUDEMONKEY_THREE_SIDECAR_RENDERER=browser-webgl
CLAUDEMONKEY_THREE_SIDECAR_SCENE=live-js
CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE=~/.claude/harnessmonkey/threejs/scene.js
CLAUDEMONKEY_THREE_SIDECAR_LIVE_ROOT=~/.claude/harnessmonkey/threejs
CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS=2000
CLAUDEMONKEY_THREE_SIDECAR_ANSI=chafa-vhalf
CLAUDEMONKEY_THREE_SIDECAR_LAYOUT=two-side
THREE_SIDECAR_CHAFA_BIN=/opt/homebrew/bin/chafa
THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE=offscreen
THREE_SIDECAR_EIDOVERSE_ROOT=/Users/MAC/Documents/eidoverse-video
```

It should preserve the existing two-side crop/tuning vars from the WebGPU profile and may retain `THREE_SIDECAR_EIDOVERSE_ROOT` only as an allowlisted asset root for the default Capybara scene; it must drop `THREE_SIDECAR_EIDOVERSE_CONFIG` because the live JS module replaces that config-driven path. BrowserWebGL-specific crop adjustments require manual smoke evidence. The real `capybara-onsen-threejs-sidecar` profile must not route to the BrowserWebGL video-texture Capybara branch; that branch should be removed or unreachable for this profile.

The live file is a browser ESM file. The recommended entrypoint is:

```js
export async function createScene(ctx) {
  const { THREE, renderer, cfg, helpers } = ctx;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(46, cfg.pixelWidth / cfg.pixelHeight, 0.1, 120);
  return {
    scene,
    camera,
    update(timeSeconds) {},
    dispose() {},
  };
}
```

This entrypoint is a loader contract, not an intermediate state format. The scene file can define arbitrary code, import local helper files, construct arbitrary three.js objects, and mutate global or module-local runtime state. The sidecar only asks it to return the scene instance needed for render/readback.

A default Capybara scene may export a JavaScript asset object so the loader can prefetch images/models before `createScene(ctx)`. That object is code-owned module metadata, not JSON scene state and not a scene schema. The renderer must not consume a JSON scene description.

## Architecture

### 1. Claude parent patch: frame bridge plus real reminder sink

The existing parent patch continues to own terminal layout, sidecar process lifecycle, ANSI validation, and `frame` / `frame-pair` handling.

Add a second `threejs-sidebar-sidecar` patch operation anchored at the same conversation-state seam that Capybara uses today:

```js
dWc(hn.useCallback((ft)=>kc((en)=>[...en,Dn({content:Hpr(ft),isMeta:!0})]),[kc]));
```

The replacement should preserve the original `dWc(...)` callback and register a global sink, for example:

```js
__tsSystemReminderSink = hn.useCallback(
  (ft) => kc((en) => [...en, ki({ type: "critical_system_reminder", content: ft })]),
  [kc]
);
```

Exact minified identifiers must be generated/pinned the same way the existing packages pin payloads. The sink cannot live only in the `function VKo(...)` helper payload, because that scope does not have `kc` conversation state.

Parent stdout handlers in both single-left and two-side modes should accept:

```json
{"type":"system-reminder","content":"..."}
```

and call the global sink if available. The handler must sanitize and cap content before append:

- coerce content to string;
- cap at 4000 UTF-16 code units for the first implementation;
- preserve normal newlines and tabs;
- replace other C0 controls and DEL with spaces;
- ignore empty/whitespace-only content;
- never throw into rendering if the sink is unavailable.

There should be no browser-facing `/system-reminder` HTTP endpoint in the first cut. The Deno sidecar backend can emit startup reminders internally over stdout. Future event producers can use the same NDJSON bridge, but not by making writable scene code a direct hidden-reminder authority.

### 2. Deno BrowserWebGL backend: private live scene server

The Deno backend keeps serving the browser app and vendor three.js files. It gains live-scene endpoints:

- `GET /live-scene-status?token=<nonce>` -> `{ ok, version, mtimeMs, path, error? }`
- `GET /live/scene.js?v=<version>&token=<nonce>` -> the current live scene file with `cache-control: no-store`
- `GET /live/<relative-path>?token=<nonce>` -> same-root helper/asset serving with traversal protection
- `GET /live-assets/<key>?token=<nonce>` -> allowlisted packaged/default Capybara assets only

Private serving requirements:

- bind `Deno.serve` to loopback only, preferably `127.0.0.1` and a sidecar-chosen port if Deno Desktop permits it;
- do not enable CORS;
- generate an unguessable per-process token and include it only in the served browser app URLs;
- reject requests missing the token for live-file and live-asset endpoints;
- no directory listings;
- no symlink escape from `LIVE_ROOT` after realpath resolution;
- reject absolute paths, encoded traversal, dotfiles, hidden directories, and NUL bytes;
- MIME allowlist: JavaScript modules, JSON-like metadata only when it is a static asset manifest generated by the packaged scene, images, HDR, glTF/GLB, and binary buffers needed by the default scene;
- do not serve arbitrary paths outside the live root except explicit packaged/default Capybara assets.

The backend should expand `~/` using `HOME`. It should create the live root if missing. If the live scene file is missing, it should copy a packaged default Capybara WebGL scene into `~/.claude/harnessmonkey/threejs/scene.js`. It must not overwrite an existing user/agent-edited scene file.

### 3. Browser app live loader

The browser app should keep one renderer and one render target for the lifetime of the sidecar. It should manage a mutable current scene instance:

1. Import the initial live scene module with a cache-busted URL.
2. Build a context object with `THREE`, `renderer`, `cfg`, and compatibility helpers.
3. If the module exports an asset object, ask the backend for allowlisted asset bytes and install `globalThis.ASSETS` before create.
4. Call `module.createScene(ctx)`.
5. Render/update that returned scene instance each frame.
6. Poll `/live-scene-status` every `reloadMs`.
7. If `version` changes, import the new module URL, construct a replacement scene instance, then dispose the old instance.

Reload must be failure-isolating. A syntax/runtime error in the new file should report a non-fatal diagnostic and keep rendering the last good scene. A bad edit should not blank the sidebar unless there has never been a valid scene.

Fatal sidecar errors and non-fatal scene reload diagnostics must be separate protocols. Keep current `type:"error"` semantics for fatal sidecar failure. Add a non-fatal message, for example:

```json
{"type":"scene-error","phase":"reload","message":"...","version":"..."}
```

The parent should not switch to fallback UI for `scene-error`. It can ignore it, log it to stderr, or display a small non-disruptive metric later. The browser loop must catch reload import/create failures without setting `running=false`.

Disposal should call `instance.dispose?.()` first. Automatic traversal disposal may be offered as a helper, but the default should prefer scene-owned disposal to avoid destroying shared renderer/vendor/default textures across reloads. Renderer and render target are shared and should not be recreated on every reload.

Dynamic import cache-busting will accumulate module instances over a long session. This is acceptable for the first implementation and should be documented in runtime caveats.

### 4. Browser/WebGL compatibility substrate for Capybara

The Capybara WebGL port should preserve the current scene file's authored structure. The compatibility substrate should make the old Eidoverse scene idioms work in a browser/WebGL context:

- provide a mutable `THREE` facade, not mutation of the imported module namespace;
- alias `MeshStandardNodeMaterial` -> `MeshStandardMaterial`, `MeshBasicNodeMaterial` -> `MeshBasicMaterial`, and `MeshPhysicalNodeMaterial` -> `MeshPhysicalMaterial` on that facade;
- provide `THREE.uniform(value)` as `{ value }` for code paths that only update `.value` from JavaScript;
- provide a `THREE.pmremTexture(texture)` compatibility helper backed by `PMREMGenerator` where practical, or a documented fallback to the raw equirectangular texture if PMREM fails;
- serve/import `GLTFLoader` and `HDRLoader` through an explicit allowlisted addon route or a bundled helper, because the current `/vendor/` route only serves direct files under `three/build`;
- install `globalThis.THREE`, `globalThis.GLTFLoader`, `globalThis.HDRLoader`, `globalThis.ASSETS`, `globalThis.b64toArrayBuffer`, `globalThis.loadImageTexture`, and placement helpers before the default Capybara scene initializes;
- port `placeOn` / related placement helpers from `scene_placement.js` where they are renderer-agnostic;
- replace the WebGPU water compute helper with a WebGL API-compatible helper returning exactly `{ mesh, step, disturb }`;
- replace TSL `makeParticles` with a WebGL API-compatible helper returning `{ mesh, material, update, uniforms }`.

Helper API compatibility is the line that protects the scene from becoming a rebuild.

### 5. Source-preserving default Capybara scene module

Create a packaged default scene file derived mechanically from `wide-gap-scene.js` and copied to the live scene path on first run. Acceptance criteria for the default scene port:

- keep actor construction functions intact unless a line is renderer-bound or browser-incompatible;
- preserve source actor names such as `left_soaking_capybara_brave_soaking_with_towel`, `right_sleepy_capybara_graceful_lounging`, `left_bamboo_spout_mossy_kakei`, `right_stone_lantern_warm_polyhaven_lantern_01`, and existing particle/emitter names;
- preserve animation timing formulas for breathing, ear flicks, water pulses, drops, yuzu drift, spirit drift, lantern glow, warm fill, and camera drift;
- convert `globalThis.setup` / `globalThis.renderFrame` to `export async function createScene(ctx)` / returned `update(t)` with a diff-minimizing transform;
- remove scene-owned renderer creation and `await globalThis._r.renderAsync(...)`; rendering is owned by the BrowserWebGL sidecar loop;
- replace browser-incompatible `npm:` imports with sidecar-served/bundled helpers;
- keep current two-sided crop/framing unless manual smoke proves adjustment is needed;
- include a source-retention review in implementation: compare the port against `wide-gap-scene.js` and justify every changed/deleted block.

The port should not compress the scene into a flat video, a pre-baked sprite wall, or a newly invented simplified scene.

## Data Flow

### Launch

1. HarnessMonkey option enables `threejs-sidebar-sidecar` and the updated `capybara-onsen-threejs-sidecar` BrowserWebGL live-scene env vars.
2. Claude Code parent patch reserves gutters and spawns `run-sidecar-browser-webgl.sh`.
3. Parent passes current terminal dimensions to sidecar args.
4. Sidecar starts Deno Desktop CEF and serves the browser app on a private loopback/tokenized route. If Deno Desktop cannot bind loopback explicitly, implementation must fail closed or document and prove the actual bound interface before acceptance.
5. Sidecar emits `hello` and a startup `system-reminder` once.

### Render

1. Browser app loads `/live/scene.js?v=<version>&token=<nonce>`.
2. Scene module returns `{ scene, camera, update, dispose }`.
3. Each frame: `update(t)`, render to `WebGLRenderTarget`, read pixels, POST `/frame`.
4. Backend encodes with Chafa and emits `frame` or `frame-pair` NDJSON.
5. Parent validates ANSI dimensions/control sequences and paints `ink-raw-ansi`.

### Reload

1. Browser polls `/live-scene-status?token=<nonce>` every two seconds.
2. If version changed, browser imports the cache-busted scene module.
3. If creation succeeds, browser atomically swaps current scene instance and disposes the old one.
4. If creation fails, browser emits `scene-error`, keeps the last valid scene, and continues rendering.

### Runtime system reminders

1. Sidecar emits `{type:"system-reminder", content}` over stdout.
2. Parent patch receives the message in the existing stdout line handler.
3. Parent sanitizes/caps content and calls the registered sink.
4. Sink appends `critical_system_reminder` through `ki(...)`.
5. Existing hidden-context machinery forwards it to the next model turn as a system reminder.

## Error Handling

- Missing live scene file: create parent directory and copy packaged default scene.
- Existing live scene file: never overwrite; load exactly what is there.
- Unreadable live scene file: render fallback only if there has never been a valid scene; otherwise keep last good scene and emit `scene-error`.
- Bad scene syntax/runtime during reload: keep the last good scene and emit `scene-error`, not fatal `error`.
- Scene returns invalid instance: reject reload unless `scene`, `camera`, and `update` satisfy the minimal contract.
- Asset load failure: reject only the new scene creation; keep last good scene.
- Sidecar crash or renderer setup failure: keep the existing fatal `error` / parent fallback behavior.
- System-reminder sink unavailable: ignore or log; frame rendering must continue.

## Testing Strategy

### Python/package tests

- Add manifest tests proving `capybara-onsen-threejs-sidecar` now points at BrowserWebGL live JS, not `eidoverse-deno-webgpu` or `wide-gap-scene.json`.
- Add patch payload tests for the new `dWc(...)`-anchored reminder sink operation.
- Add tests proving the sink uses `ki({type:"critical_system_reminder",content:...})`, not launch prompts and not an isMeta user row.
- Add tests proving both parent stdout handlers route `system-reminder` while `frame` / `frame-pair` validation still works.
- Add a negative test that no prompt-profile/package launch prompt mechanism is used for this startup message.

### Deno unit tests

- Extend BrowserWebGL `main_test.ts` for live-scene path resolution, `~/` expansion, traversal rejection, symlink escape rejection, dotfile rejection, MIME allowlist behavior, mtime/version calculation, and default path selection.
- Test that parseArgs reads live scene env vars and reload interval.
- Test that missing scene file bootstraps the default JS scene only when absent and never overwrites an existing file.
- Test scene-instance validation and scene-owned disposal helpers with fake scene objects.
- Test bad reload behavior: previous instance remains active and a non-fatal `scene-error` is emitted instead of fatal `error`.

### Capybara port review/tests

- Add a source-retention review artifact or test helper that compares the port against `wide-gap-scene.js` and lists intentional changed/deleted regions.
- Add targeted tests for compatibility helper shapes: `createWaterCompute(renderer, opts)`, `makeParticles(opts)`, `loadImageTexture`, `b64toArrayBuffer`, `GLTFLoader`, and `HDRLoader` availability.
- Add a smoke fixture that imports the default scene module with fake/minimal helpers to verify it exports `createScene` and does not construct `WebGPURenderer` or call `renderAsync`.

### Smoke tests

- BrowserWebGL sidecar emits `hello` and at least one `frame`/`frame-pair` for the live default scene.
- Editing/touching the live scene file changes the sidecar version and reloads without restarting Claude.
- A deliberately broken scene file keeps the last good frame and reports `scene-error`.
- The startup reminder appears as a hidden-context/system-reminder row in transcript behavior, using the same mechanism Capybara already proved.
- Manual visual smoke verifies Capybara actors, crop, motion, prompt typing, resize behavior, and sidecar cleanup.
- Manual/perf smoke records whether per-frame Chafa spawning remains acceptable at the selected Capybara FPS.

## Open Risks

- The reminder bridge gives the sidecar hidden-system-reminder authority. The first implementation should keep that authority in the Deno backend/parent protocol and not expose it directly to browser scene code.
- Browser module namespace objects are not safely mutable, so the compatibility `THREE` must be a facade object.
- WebGL equivalents for water and particles may not exactly match the WebGPU/TSL look on the first pass. The API boundary should preserve scene code while allowing visual tuning inside helper implementations.
- Asset prefetching for large HDR/model/texture files may slow first startup. This is acceptable for the default profile but should be observable via protocol metrics/errors.
- Deno Desktop packaged app behavior is already known to be fragile outside the verified packaged launch path. Implementation should preserve the current packaged-app assumptions.
- Dynamic import cache-busting is not memory-neutral over very long sessions.
- The hidden-context reminder bridge depends on minified Claude Code anchors, just like the existing Capybara note sink. Tests should pin the exact anchor and fail loudly on version bumps.

## Recommended Implementation Slice

Implement in this order:

1. Add live-scene option parsing, safe path/status endpoints, tokenized loopback serving, and browser reload loop using a tiny test scene.
2. Add the `dWc(...)`-anchored generic sidecar-to-`critical_system_reminder` bridge and startup reminder.
3. Update `capybara-onsen-threejs-sidecar` to select BrowserWebGL live JS and add first-run default scene copy into `~/.claude/harnessmonkey/threejs/scene.js`.
4. Add WebGL compatibility helpers for assets/addons/material aliases, placement, water, and particles.
5. Port the Capybara scene with a source-retention review against `wide-gap-scene.js`.
6. Tune two-sided crop geometry and run manual smoke.

This order proves live-code reload and runtime system reminders before spending effort on high-fidelity Capybara visual parity, but still treats the final Capybara scene as a source-preserving port rather than a rebuild.
