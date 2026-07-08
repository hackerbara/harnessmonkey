# Live Three.js BrowserWebGL Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a BrowserWebGL + Chafa live JavaScript scene profile under `~/.claude`, with a source-preserving WebGL port of the Capybara Onsen scene and a runtime hidden-system-reminder bridge.

**Architecture:** Keep the existing Claude terminal frame bridge and Deno Desktop BrowserWebGL readback path. Add a secure live-scene loader in the sidecar, a `dWc(...)`-anchored parent reminder sink, and WebGL compatibility helpers so the Capybara scene is ported mechanically rather than rebuilt. The `capybara-onsen-threejs-sidecar` option becomes the live BrowserWebGL profile.

**Tech Stack:** HarnessMonkey package manifests, Bun graph repack payloads for Claude Code 2.1.201, Deno Desktop CEF, three.js WebGLRenderer, Chafa, pytest, Deno tests.

---

## Spec

Design spec: `docs/superpowers/specs/2026-07-07-live-threejs-browserwebgl-sidecar-design.md`

## File Structure

- Modify `options/capybara-onsen-threejs-sidecar/option.json` to point at BrowserWebGL live JS.
- Modify `options/capybara-onsen-threejs-sidecar/README.md` to describe the live JS file under `~/.claude`.
- Modify `packages/threejs-sidebar-sidecar/patch.json` to add one `dWc(...)`-anchored operation and bump package version.
- Create `packages/threejs-sidebar-sidecar/payloads/16-threejs-sidebar-system-reminder-sink-after-dwc-2-1-201.js` for the reminder sink.
- Modify `packages/threejs-sidebar-sidecar/payloads/01-threejs-sidebar-helpers-before-vko-2-1-201.js` to route `system-reminder` stdout messages in both single-left and two-side handlers.
- Modify `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/main.ts` to parse live-scene config, serve secure endpoints, emit startup reminders, and run the browser live loader.
- Create `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene.ts` for path, status, bootstrap, MIME, and route helpers that can be unit-tested outside Deno Desktop.
- Create `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene_test.ts` for Deno tests.
- Create `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-onsen-webgl.scene.js` as the source-preserving default scene module.
- Create `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-webgl-helpers.js` for browser/WebGL Capybara helpers.
- Create `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-source-retention.md` documenting intentional divergences from `wide-gap-scene.js`.
- Create `tests/test_threejs_sidebar_live_scene.py` for Python package/payload/option contract tests.
- Modify `packages/threejs-sidebar-sidecar/README.md` and `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/README.md` for the live JS profile.

---

### Task 1: Add failing package and option contract tests

**Files:**
- Create: `tests/test_threejs_sidebar_live_scene.py`

- [ ] **Step 1: Write tests for option migration and reminder sink contract**

Create `tests/test_threejs_sidebar_live_scene.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THREE_PACKAGE = ROOT / "packages" / "threejs-sidebar-sidecar"
CAPY_OPTION = ROOT / "options" / "capybara-onsen-threejs-sidecar" / "option.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _payload_text(package_dir: Path, op_id: str) -> str:
    manifest = _json(package_dir / "patch.json")
    operations = manifest["patch"]["targets"][0]["modules"][0]["operations"]
    [op] = [item for item in operations if item["opId"] == op_id]
    return (package_dir / op["replacement"]["path"]).read_text(encoding="utf-8")


def test_capybara_threejs_option_uses_browser_webgl_live_scene() -> None:
    option = _json(CAPY_OPTION)["option"]
    env = {key: value["value"] for key, value in option["env"].items()}

    assert env["CLAUDEMONKEY_THREE_SIDECAR"].endswith(
        "/threejs-sidebar-sidecar/sidecar/browser-webgl/run-sidecar-browser-webgl.sh"
    )
    assert env["CLAUDEMONKEY_THREE_SIDECAR_RENDERER"] == "browser-webgl"
    assert env["CLAUDEMONKEY_THREE_SIDECAR_SCENE"] == "live-js"
    assert env["CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE"] == "~/.claude/harnessmonkey/threejs/scene.js"
    assert env["CLAUDEMONKEY_THREE_SIDECAR_LIVE_ROOT"] == "~/.claude/harnessmonkey/threejs"
    assert env["CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS"] == "2000"
    assert env["CLAUDEMONKEY_THREE_SIDECAR_ANSI"] == "chafa-vhalf"
    assert env["CLAUDEMONKEY_THREE_SIDECAR_LAYOUT"] == "two-side"
    assert env["THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE"] == "offscreen"
    assert env["THREE_SIDECAR_CHAFA_BIN"] == "/opt/homebrew/bin/chafa"
    assert "THREE_SIDECAR_EIDOVERSE_CONFIG" not in env
    assert "eidoverse-webgpu" not in env["CLAUDEMONKEY_THREE_SIDECAR"]


def test_threejs_package_declares_dwc_anchored_system_reminder_sink() -> None:
    manifest = _json(THREE_PACKAGE / "patch.json")
    operations = manifest["patch"]["targets"][0]["modules"][0]["operations"]
    op_ids = [op["opId"] for op in operations]
    assert "threejs-sidebar-system-reminder-sink-after-dwc-2-1-201" in op_ids

    payload = _payload_text(
        THREE_PACKAGE,
        "threejs-sidebar-system-reminder-sink-after-dwc-2-1-201",
    )
    assert "dWc(hn.useCallback" in payload
    assert "__tsSystemReminderSink" in payload
    assert 'ki({type:"critical_system_reminder",content:ft})' in payload
    assert "Dn({content:[{type:\"text\",text:ft}],isMeta:!0})" not in payload


def test_threejs_helper_routes_system_reminder_messages_without_prompt_packages() -> None:
    helper = (THREE_PACKAGE / "payloads" / "01-threejs-sidebar-helpers-before-vko-2-1-201.js").read_text(
        encoding="utf-8"
    )
    assert 'msg.type==="system-reminder"' in helper or "msg.type==='system-reminder'" in helper
    assert "__tsPostSystemReminder" in helper
    assert "__tsCleanSystemReminder" in helper
    assert "set-prompt" not in helper
    assert "launch profile" not in helper.lower()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run pytest tests/test_threejs_sidebar_live_scene.py -q
```

Expected: failures showing the option still uses `eidoverse-webgpu`, the new sink operation is missing, and helper routing is missing.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_threejs_sidebar_live_scene.py
git commit -m "test: specify live threejs sidebar contracts"
```

---

### Task 2: Migrate the Capybara three.js option to BrowserWebGL live JS

**Files:**
- Modify: `options/capybara-onsen-threejs-sidecar/option.json`
- Modify: `options/capybara-onsen-threejs-sidecar/README.md`

- [ ] **Step 1: Update `option.json`**

Replace the option description and env block so the effective env values are:

```json
{
  "CLAUDEMONKEY_THREE_SIDECAR_ENABLE": { "value": "1", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR": {
    "value": "~/.harnessmonkey/patches/threejs-sidebar-sidecar/sidecar/browser-webgl/run-sidecar-browser-webgl.sh",
    "allowOverrideProcessEnv": true
  },
  "CLAUDEMONKEY_THREE_SIDECAR_RENDERER": { "value": "browser-webgl", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_SCENE": { "value": "live-js", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE": {
    "value": "~/.claude/harnessmonkey/threejs/scene.js",
    "allowOverrideProcessEnv": true
  },
  "CLAUDEMONKEY_THREE_SIDECAR_LIVE_ROOT": {
    "value": "~/.claude/harnessmonkey/threejs",
    "allowOverrideProcessEnv": true
  },
  "CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS": { "value": "2000", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_ANSI": { "value": "chafa-vhalf", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_FPS": { "value": "24", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_LAYOUT": { "value": "two-side", "allowOverrideProcessEnv": true },
  "THREE_SIDECAR_CHAFA_BIN": { "value": "/opt/homebrew/bin/chafa", "allowOverrideProcessEnv": true },
  "THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE": { "value": "offscreen", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_SIDE_WIDTH": { "value": "50", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_RIGHT_BREAKPOINT": { "value": "140", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_OUTER_CROP_COLUMNS": { "value": "20", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_SOURCE_SIDE_COLUMNS": { "value": "80", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_RENDER_COLUMNS": { "value": "400", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_SOURCE_WIDTH": { "value": "1280", "allowOverrideProcessEnv": true },
  "CLAUDEMONKEY_THREE_SIDECAR_SOURCE_HEIGHT": { "value": "720", "allowOverrideProcessEnv": true },
  "THREE_SIDECAR_EIDOVERSE_ROOT": {
    "value": "/Users/MAC/Documents/eidoverse-video",
    "allowOverrideProcessEnv": true
  }
}
```

Keep conflicts with `threejs-sidebar-sidecar-local` and `threejs-sidebar-sidecar-browser-webgl-chafa`.

- [ ] **Step 2: Update README wording**

Change references from “Deno WebGPU + Chafa” / `wide-gap-scene.json` to BrowserWebGL live JS. Include this exact user-facing path:

```markdown
The live scene file is `~/.claude/harnessmonkey/threejs/scene.js`. HarnessMonkey bootstraps the default Capybara WebGL scene there on first run and never overwrites an existing file.
```

- [ ] **Step 3: Run the option contract test**

```bash
uv run pytest tests/test_threejs_sidebar_live_scene.py::test_capybara_threejs_option_uses_browser_webgl_live_scene -q
```

Expected: PASS.

- [ ] **Step 4: Commit option migration**

```bash
git add options/capybara-onsen-threejs-sidecar/option.json options/capybara-onsen-threejs-sidecar/README.md
git commit -m "feat: point capybara threejs profile at browser webgl live js"
```

---

### Task 3: Add the parent-side system-reminder sink

**Files:**
- Create: `packages/threejs-sidebar-sidecar/payloads/16-threejs-sidebar-system-reminder-sink-after-dwc-2-1-201.js`
- Modify: `packages/threejs-sidebar-sidecar/patch.json`
- Modify: `packages/threejs-sidebar-sidecar/payloads/01-threejs-sidebar-helpers-before-vko-2-1-201.js`

- [ ] **Step 1: Create the sink payload**

Create `packages/threejs-sidebar-sidecar/payloads/16-threejs-sidebar-system-reminder-sink-after-dwc-2-1-201.js` as a single line:

```js
dWc(hn.useCallback((ft)=>kc((en)=>[...en,Dn({content:Hpr(ft),isMeta:!0})]),[kc]));__tsSystemReminderSink=hn.useCallback((ft)=>kc((en)=>[...en,ki({type:"critical_system_reminder",content:ft})]),[kc]);
```

- [ ] **Step 2: Add helper functions to payload 01**

In `01-threejs-sidebar-helpers-before-vko-2-1-201.js`, add these helper functions near the other `__ts...` helpers:

```js
function __tsCleanSystemReminder(v){let s=String(v??"");s=s.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g," ").slice(0,4000).trim();return s||null}
function __tsPostSystemReminder(v){let s=__tsCleanSystemReminder(v);if(!s)return;try{if(typeof __tsSystemReminderSink==="function")__tsSystemReminderSink(s)}catch(e){}}
```

In both `handle(line)` functions, add this branch before the fatal `error` branch:

```js
else if(msg.type==="system-reminder")__tsPostSystemReminder(msg.content)
```

There are two handlers: one inside `__CodexThreeSidebarLiveWallV1` and one inside `__CodexThreeSidebarFrameV2`.

- [ ] **Step 3: Update patch manifest operation list**

In `packages/threejs-sidebar-sidecar/patch.json`:

1. Bump `packageVersion` from `0.6.0-browser-webgl-two-side` to `0.7.0-live-js-system-reminders`.
2. Add an operation after the existing layout/style operations:

```json
{
  "opId": "threejs-sidebar-system-reminder-sink-after-dwc-2-1-201",
  "label": "Register generic three.js sidecar system-reminder sink beside the session-name bridge",
  "type": "replace_exact",
  "exact": "dWc(hn.useCallback((ft)=>kc((en)=>[...en,Dn({content:Hpr(ft),isMeta:!0})]),[kc]));",
  "requireWithinRange": ["dWc(hn.useCallback"],
  "oldRangeSha256": "27dff047e88095819edb2169245519dfb3968df835cd47bd8223dd206c3c005a",
  "oldRangeLength": 82,
  "replacement": {
    "path": "payloads/16-threejs-sidebar-system-reminder-sink-after-dwc-2-1-201.js",
    "sha256": "REPLACE_WITH_SHA256"
  },
  "knownBehaviorChange": "Allows the three.js sidecar stdout protocol to append sanitized critical_system_reminder rows through Claude Code's existing hidden-context pipeline."
}
```

Compute the replacement SHA and replace `REPLACE_WITH_SHA256`:

```bash
python3 - <<'PY'
from pathlib import Path
import hashlib
p = Path('packages/threejs-sidebar-sidecar/payloads/16-threejs-sidebar-system-reminder-sink-after-dwc-2-1-201.js')
print(hashlib.sha256(p.read_bytes()).hexdigest())
PY
```

3. Add a precondition under the target preconditions:

```json
{
  "type": "module_must_contain",
  "modulePath": "/$bunfs/root/src/entrypoints/cli.js",
  "value": "dWc(hn.useCallback((ft)=>kc((en)=>[...en,Dn({content:Hpr(ft),isMeta:!0})]),[kc]));"
}
```

4. Add postconditions requiring `__tsSystemReminderSink`, `__tsPostSystemReminder`, and `critical_system_reminder`.

- [ ] **Step 4: Run reminder sink tests**

```bash
uv run pytest tests/test_threejs_sidebar_live_scene.py::test_threejs_package_declares_dwc_anchored_system_reminder_sink tests/test_threejs_sidebar_live_scene.py::test_threejs_helper_routes_system_reminder_messages_without_prompt_packages -q
```

Expected: PASS.

- [ ] **Step 5: Validate package manifest against Claude 2.1.201**

```bash
uv run harnessmonkey validate-package \
  --source /Users/MAC/.local/share/claude/versions/2.1.201 \
  --package packages/threejs-sidebar-sidecar \
  --source-version 2.1.201 \
  --source-version-output '2.1.201 (Claude Code)' \
  --platform darwin \
  --arch arm64
```

Expected: JSON or text output indicating `ok=true` / validation passed. If it fails on a hash for payload 01, compute the new payload 01 SHA and update its `replacement.sha256` in `patch.json`.

- [ ] **Step 6: Commit reminder bridge**

```bash
git add packages/threejs-sidebar-sidecar/patch.json packages/threejs-sidebar-sidecar/payloads/01-threejs-sidebar-helpers-before-vko-2-1-201.js packages/threejs-sidebar-sidecar/payloads/16-threejs-sidebar-system-reminder-sink-after-dwc-2-1-201.js
git commit -m "feat: add threejs sidecar system reminder bridge"
```

---

### Task 4: Add live-scene path and status helpers

**Files:**
- Create: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene.ts`
- Create: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene_test.ts`

- [ ] **Step 1: Write failing Deno tests**

Create `live_scene_test.ts` with tests for env parsing, traversal rejection, dotfile rejection, symlink escape, and no-overwrite bootstrap. Use Deno's temp dirs:

```ts
import {
  assert,
  assertEquals,
  assertRejects,
} from "https://deno.land/std@0.224.0/assert/mod.ts";
import {
  bootstrapLiveScene,
  isAllowedLiveRelativePath,
  liveSceneStatus,
  parseLiveSceneOptions,
  resolveLivePath,
} from "./live_scene.ts";

Deno.test("parseLiveSceneOptions reads ~/.claude defaults and reload ms", () => {
  const env = new Map<string, string>([
    ["HOME", "/Users/example"],
    ["CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE", "~/.claude/harnessmonkey/threejs/scene.js"],
    ["CLAUDEMONKEY_THREE_SIDECAR_LIVE_ROOT", "~/.claude/harnessmonkey/threejs"],
    ["CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS", "2000"],
  ]);
  const opts = parseLiveSceneOptions((name) => env.get(name));
  assertEquals(opts.reloadMs, 2000);
  assertEquals(opts.scenePath, "/Users/example/.claude/harnessmonkey/threejs/scene.js");
  assertEquals(opts.liveRoot, "/Users/example/.claude/harnessmonkey/threejs");
});

Deno.test("resolveLivePath rejects traversal and dotfiles", async () => {
  const root = await Deno.makeTempDir();
  await assertRejects(() => resolveLivePath(root, "../secret.js"));
  await assertRejects(() => resolveLivePath(root, ".env"));
  await assertRejects(() => resolveLivePath(root, "nested/.secret.js"));
  assert(isAllowedLiveRelativePath("scene.js"));
  assert(!isAllowedLiveRelativePath("../scene.js"));
});

Deno.test("bootstrapLiveScene writes default only when missing", async () => {
  const root = await Deno.makeTempDir();
  const scene = `${root}/scene.js`;
  const defaultScene = `${root}/default.js`;
  await Deno.writeTextFile(defaultScene, "export async function createScene(){return 'default'}\n");
  await bootstrapLiveScene(scene, defaultScene);
  assertEquals(await Deno.readTextFile(scene), "export async function createScene(){return 'default'}\n");
  await Deno.writeTextFile(scene, "export const user = true;\n");
  await bootstrapLiveScene(scene, defaultScene);
  assertEquals(await Deno.readTextFile(scene), "export const user = true;\n");
});

Deno.test("liveSceneStatus changes version after write", async () => {
  const root = await Deno.makeTempDir();
  const scene = `${root}/scene.js`;
  await Deno.writeTextFile(scene, "export const a = 1;\n");
  const first = await liveSceneStatus(scene);
  await new Promise((resolve) => setTimeout(resolve, 5));
  await Deno.writeTextFile(scene, "export const a = 2;\n");
  const second = await liveSceneStatus(scene);
  assert(first.ok);
  assert(second.ok);
  assert(first.version !== second.version);
});
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
cd packages/threejs-sidebar-sidecar/sidecar/browser-webgl
/opt/homebrew/bin/deno test --allow-read --allow-write --allow-env live_scene_test.ts
```

Expected: FAIL because `live_scene.ts` does not exist.

- [ ] **Step 3: Implement `live_scene.ts`**

Create `live_scene.ts` with exported helpers matching the tests. Include these implementation rules:

```ts
export type LiveSceneOptions = {
  scenePath: string;
  liveRoot: string;
  reloadMs: number;
};

export function expandHome(path: string, home: string): string {
  if (path === "~") return home;
  if (path.startsWith("~/")) return home + path.slice(1);
  return path;
}

export function parseLiveSceneOptions(readEnv: (name: string) => string | undefined): LiveSceneOptions {
  const home = readEnv("HOME") || Deno.env.get("HOME") || "/tmp";
  const scenePath = expandHome(
    readEnv("CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE") || "~/.claude/harnessmonkey/threejs/scene.js",
    home,
  );
  const liveRoot = expandHome(
    readEnv("CLAUDEMONKEY_THREE_SIDECAR_LIVE_ROOT") || "~/.claude/harnessmonkey/threejs",
    home,
  );
  const rawMs = Number(readEnv("CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS") || "2000");
  const reloadMs = Number.isFinite(rawMs) ? Math.max(500, Math.min(60000, Math.round(rawMs))) : 2000;
  return { scenePath, liveRoot, reloadMs };
}

export function isAllowedLiveRelativePath(rel: string): boolean {
  if (!rel || rel.includes("\0")) return false;
  if (rel.startsWith("/") || rel.startsWith("~")) return false;
  const decoded = decodeURIComponent(rel);
  if (decoded.split("/").some((part) => part === ".." || part === "" || part.startsWith("."))) return false;
  return /\.(js|mjs|json|png|jpg|jpeg|webp|hdr|gltf|glb|bin)$/i.test(decoded);
}

export async function resolveLivePath(root: string, rel: string): Promise<string> {
  if (!isAllowedLiveRelativePath(rel)) throw new Error("disallowed live path");
  const rootReal = await Deno.realPath(root).catch(async () => {
    await Deno.mkdir(root, { recursive: true });
    return await Deno.realPath(root);
  });
  const candidate = `${rootReal}/${decodeURIComponent(rel)}`;
  const parent = candidate.slice(0, candidate.lastIndexOf("/")) || rootReal;
  const parentReal = await Deno.realPath(parent).catch(() => parent);
  if (parentReal !== rootReal && !parentReal.startsWith(rootReal + "/")) {
    throw new Error("live path escapes root");
  }
  return candidate;
}

export async function bootstrapLiveScene(scenePath: string, defaultScenePath: string): Promise<boolean> {
  try {
    await Deno.stat(scenePath);
    return false;
  } catch {
    await Deno.mkdir(scenePath.slice(0, scenePath.lastIndexOf("/")), { recursive: true });
    await Deno.copyFile(defaultScenePath, scenePath);
    return true;
  }
}

export async function liveSceneStatus(scenePath: string): Promise<{ ok: boolean; version: string; mtimeMs: number; path: string; error?: string }> {
  try {
    const stat = await Deno.stat(scenePath);
    const mtimeMs = stat.mtime?.getTime() || 0;
    return { ok: true, version: `${mtimeMs}-${stat.size}`, mtimeMs, path: scenePath };
  } catch (error) {
    return { ok: false, version: "missing", mtimeMs: 0, path: scenePath, error: String(error instanceof Error ? error.message : error) };
  }
}
```

- [ ] **Step 4: Run Deno tests**

```bash
cd packages/threejs-sidebar-sidecar/sidecar/browser-webgl
/opt/homebrew/bin/deno test --allow-read --allow-write --allow-env live_scene_test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit live-scene helpers**

```bash
git add packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene.ts packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene_test.ts
git commit -m "feat: add browser webgl live scene path helpers"
```

---

### Task 5: Wire live-scene endpoints and reload loop into BrowserWebGL

**Files:**
- Modify: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/main.ts`
- Modify: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/main_test.ts`

- [ ] **Step 1: Extend Options and parseArgs**

Add fields to `Options`:

```ts
liveScenePath: string;
liveRoot: string;
reloadMs: number;
sourceWidth: number;
sourceHeight: number;
```

In `parseArgs`, populate them from env helpers. Preserve current defaults for non-live scenes.

- [ ] **Step 2: Add startup reminder emit from backend**

Add helper:

```ts
let startupReminderSent = false;
function emitSystemReminder(content: string): void {
  emit({ type: "system-reminder", content });
}
function emitStartupReminder(): void {
  if (startupReminderSent) return;
  startupReminderSent = true;
  emitSystemReminder(
    "You are running inside an experimental HarnessMonkey live three.js visualization sidebar. The sidecar loads a writable browser three.js scene from ~/.claude/harnessmonkey/threejs/scene.js. You may update that file at any point to change the visualization; the sidecar polls for changes and reloads the live JavaScript scene."
  );
}
```

Call `emitStartupReminder()` after the browser sends `/hello` successfully.

- [ ] **Step 3: Add secure endpoint state**

At module level:

```ts
import {
  bootstrapLiveScene,
  liveSceneStatus,
  parseLiveSceneOptions,
  resolveLivePath,
} from "./live_scene.ts";

const liveOpts = parseLiveSceneOptions(readEnv);
const liveToken = crypto.randomUUID() + crypto.randomUUID();
```

When serving browser app JS, include `liveToken`, `liveScenePath`, `liveRoot`, and `reloadMs` in `cfg`.

- [ ] **Step 4: Add endpoints in `handleRequest`**

Before the fallback HTML response, add:

```ts
function requireToken(url: URL): Response | null {
  if (url.searchParams.get("token") !== liveToken) {
    return new Response("forbidden", { status: 403 });
  }
  return null;
}
```

Add routes:

```ts
if (url.pathname === "/live-scene-status") {
  const denied = requireToken(url); if (denied) return denied;
  return json(await liveSceneStatus(liveOpts.scenePath));
}
if (url.pathname === "/live/scene.js") {
  const denied = requireToken(url); if (denied) return denied;
  const data = await Deno.readTextFile(liveOpts.scenePath);
  return new Response(data, { headers: { "content-type": "text/javascript; charset=utf-8", "cache-control": "no-store" } });
}
if (url.pathname.startsWith("/live/")) {
  const denied = requireToken(url); if (denied) return denied;
  const rel = decodeURIComponent(url.pathname.slice("/live/".length));
  const path = await resolveLivePath(liveOpts.liveRoot, rel);
  const data = await Deno.readFile(path);
  return new Response(data, { headers: { "content-type": contentTypeForPath(path), "cache-control": "no-store" } });
}
```

Implement `contentTypeForPath(path)` with an explicit allowlist for `.js`, `.mjs`, `.json`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.hdr`, `.gltf`, `.glb`, `.bin`.

- [ ] **Step 5: Bootstrap default scene before starting server**

In `startSidecar`, before `Deno.serve`, call:

```ts
await bootstrapLiveScene(
  liveOpts.scenePath,
  joinPath(sidecarRoot, "default-scenes", "capybara-onsen-webgl.scene.js"),
);
```

If `startSidecar` is not async, make it `async function startSidecar(): Promise<void>` and call `if (import.meta.main) startSidecar();`.

- [ ] **Step 6: Replace browser hardcoded `sceneState` with current scene loader**

In `browserAppJs()`, replace the single `const sceneState = await createScene(THREE, cfg);` path with these functions:

```js
let current = null;
let currentVersion = null;
async function loadScene(versionHint) {
  const mod = await import('/live/scene.js?v=' + encodeURIComponent(versionHint || Date.now()) + '&token=' + encodeURIComponent(cfg.liveToken));
  if (!mod || typeof mod.createScene !== 'function') throw new Error('live scene must export createScene(ctx)');
  const instance = await mod.createScene({ THREE, renderer, cfg, helpers: window.__hmThreeHelpers || {} });
  if (!instance || !instance.scene || !instance.camera || typeof instance.update !== 'function') throw new Error('live scene returned invalid instance');
  return instance;
}
async function pollSceneStatus() {
  const res = await fetch('/live-scene-status?token=' + encodeURIComponent(cfg.liveToken), { cache: 'no-store' });
  const status = await res.json();
  if (!status.ok) throw new Error(status.error || 'live scene status failed');
  if (currentVersion && status.version === currentVersion) return;
  const next = await loadScene(status.version);
  const prev = current;
  current = next;
  currentVersion = status.version;
  try { if (prev && typeof prev.dispose === 'function') prev.dispose(); } catch (_) {}
}
```

In the animation loop, use `current.update(t); renderer.render(current.scene, current.camera);`.

Catch poll/reload errors without setting `running=false`:

```js
async function reportSceneError(error, phase) {
  await fetch('/scene-error', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ phase, message: String(error && error.stack ? error.stack : error), version: currentVersion }) }).catch(() => {});
}
```

- [ ] **Step 7: Add non-fatal `/scene-error` backend route**

Add route:

```ts
if (url.pathname === "/scene-error" && req.method === "POST") {
  const body = await req.text();
  emit({ type: "scene-error", renderer: "browser-webgl-cef", message: body.slice(0, 2000) });
  return json({ ok: true });
}
```

Do not make parent payload treat `scene-error` as fallback.

- [ ] **Step 8: Add tests for parseArgs live env**

Extend `main_test.ts` with:

```ts
Deno.test("parseArgs reads live scene env defaults", () => {
  const previousScene = Deno.env.get("CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE");
  const previousReload = Deno.env.get("CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS");
  try {
    Deno.env.set("CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE", "~/.claude/harnessmonkey/threejs/scene.js");
    Deno.env.set("CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS", "2000");
    const opts = parseArgs(["--scene", "live-js"]);
    assertEquals(opts.scene, "live-js");
    assertEquals(opts.reloadMs, 2000);
    assert(opts.liveScenePath.endsWith("/.claude/harnessmonkey/threejs/scene.js"));
  } finally {
    if (previousScene === undefined) Deno.env.delete("CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE"); else Deno.env.set("CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE", previousScene);
    if (previousReload === undefined) Deno.env.delete("CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS"); else Deno.env.set("CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS", previousReload);
  }
});
```

- [ ] **Step 9: Run Deno tests**

```bash
cd packages/threejs-sidebar-sidecar/sidecar/browser-webgl
/opt/homebrew/bin/deno test --allow-read --allow-write --allow-env main_test.ts live_scene_test.ts
```

Expected: PASS.

- [ ] **Step 10: Commit live loader wiring**

```bash
git add packages/threejs-sidebar-sidecar/sidecar/browser-webgl/main.ts packages/threejs-sidebar-sidecar/sidecar/browser-webgl/main_test.ts
git commit -m "feat: load and reload live browser webgl scenes"
```

---

### Task 6: Add BrowserWebGL Capybara compatibility helpers

**Files:**
- Create: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-webgl-helpers.js`

- [ ] **Step 1: Create helper module**

Create `capybara-webgl-helpers.js` exporting `installCapybaraWebGLHelpers(THREE_BASE, renderer, cfg)`:

```js
export async function installCapybaraWebGLHelpers(THREE_BASE, renderer, cfg) {
  const THREE = Object.create(THREE_BASE);
  THREE.MeshStandardNodeMaterial = THREE_BASE.MeshStandardMaterial;
  THREE.MeshBasicNodeMaterial = THREE_BASE.MeshBasicMaterial;
  THREE.MeshPhysicalNodeMaterial = THREE_BASE.MeshPhysicalMaterial;
  THREE.uniform = (value) => ({ value });
  THREE.pmremTexture = (texture) => {
    try {
      const gen = new THREE_BASE.PMREMGenerator(renderer);
      const out = gen.fromEquirectangular(texture).texture;
      gen.dispose();
      return out;
    } catch (_) {
      return texture;
    }
  };

  globalThis.THREE = THREE;
  globalThis.b64toArrayBuffer = (input) => {
    if (input instanceof Uint8Array) return input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength);
    if (input instanceof ArrayBuffer) return input;
    const binary = atob(String(input));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  };

  globalThis.loadImageTexture = async (input, opts = {}) => {
    const bytes = input instanceof Uint8Array ? input : new Uint8Array(globalThis.b64toArrayBuffer(input));
    const url = URL.createObjectURL(new Blob([bytes]));
    try {
      const texture = await new Promise((resolve, reject) => {
        new THREE_BASE.TextureLoader().load(url, resolve, undefined, reject);
      });
      texture.colorSpace = opts.srgb ? THREE_BASE.SRGBColorSpace : THREE_BASE.NoColorSpace;
      texture.wrapS = texture.wrapT = opts.wrap ?? THREE_BASE.RepeatWrapping;
      if (opts.repeat) texture.repeat.set(opts.repeat[0], opts.repeat[1]);
      if (opts.anisotropy) texture.anisotropy = opts.anisotropy;
      texture.needsUpdate = true;
      return texture;
    } finally {
      URL.revokeObjectURL(url);
    }
  };

  globalThis.placeOn = function placeOn(obj, target, opts = {}) {
    const box = new THREE_BASE.Box3().setFromObject(target);
    const objBox = new THREE_BASE.Box3().setFromObject(obj);
    const xz = Array.isArray(opts.xz) ? opts.xz : [(box.min.x + box.max.x) / 2, (box.min.z + box.max.z) / 2];
    obj.position.x += xz[0] - ((objBox.min.x + objBox.max.x) / 2);
    obj.position.z += xz[1] - ((objBox.min.z + objBox.max.z) / 2);
    obj.position.y += box.max.y - objBox.min.y + (opts.yOffset || 0) - ((opts.sink || 0) * Math.max(0, objBox.max.y - objBox.min.y));
    return true;
  };

  function createWaterCompute(_renderer, opts = {}) {
    const segments = opts.segments || opts.width || 96;
    const bounds = opts.bounds || 8;
    const geometry = new THREE_BASE.PlaneGeometry(bounds, bounds, segments - 1, segments - 1);
    geometry.rotateX(-Math.PI / 2);
    const material = new THREE_BASE.MeshPhysicalMaterial({
      color: opts.color ?? 0x163f4a,
      roughness: opts.roughness ?? 0.075,
      metalness: opts.metalness ?? 0.18,
      transparent: true,
      opacity: opts.opacity ?? 0.72,
      transmission: 0.05,
    });
    const mesh = new THREE_BASE.Mesh(geometry, material);
    const disturbances = [];
    let tick = 0;
    return {
      mesh,
      step() {
        tick += 1 / Math.max(1, cfg.fps || 24);
        const pos = geometry.attributes.position;
        for (let i = 0; i < pos.count; i++) {
          const x = pos.getX(i), z = pos.getZ(i);
          let y = Math.sin(x * 2.1 + tick * 1.4) * Math.cos(z * 1.7 - tick * 1.1) * 0.018;
          for (const d of disturbances) {
            const dx = x - d.x, dz = z - d.z, dist = Math.hypot(dx, dz);
            if (dist < d.radius) y += Math.cos((dist / Math.max(0.001, d.radius)) * Math.PI) * d.amp * d.life;
          }
          pos.setY(i, y);
        }
        for (const d of disturbances) d.life *= 0.92;
        while (disturbances.length && disturbances[0].life < 0.03) disturbances.shift();
        pos.needsUpdate = true;
        geometry.computeVertexNormals();
      },
      disturb(x, z, radius, amplitude) {
        disturbances.push({ x, z, radius, amp: amplitude, life: 1 });
      },
      _internals: { disturbances },
    };
  }

  function makeParticles(opts = {}) {
    const scene = opts.scene || globalThis._s;
    const count = opts.count || 64;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = (Math.random() - 0.5) * (opts.area || 1);
      positions[i * 3 + 1] = Math.random() * (opts.area || 1);
      positions[i * 3 + 2] = (Math.random() - 0.5) * (opts.area || 1);
    }
    const geometry = new THREE_BASE.BufferGeometry();
    geometry.setAttribute('position', new THREE_BASE.BufferAttribute(positions, 3));
    const material = new THREE_BASE.PointsMaterial({
      color: opts.color || 0xffffff,
      size: opts.size || 0.05,
      transparent: true,
      opacity: opts.opacity ?? 0.5,
      map: opts.map || null,
      depthWrite: false,
      blending: opts.blending === 'normal' ? THREE_BASE.NormalBlending : THREE_BASE.AdditiveBlending,
    });
    const mesh = new THREE_BASE.Points(geometry, material);
    mesh.position.set(...(opts.origin || opts.position || [0, 0, 0]));
    if (scene) scene.add(mesh);
    const update = () => { mesh.rotation.y += 0.002; };
    return { mesh, material, update, uniforms: {} };
  }

  return { THREE, createWaterCompute, makeParticles };
}
```

This helper is visually simpler than the WebGPU helpers but preserves callable APIs so the scene port remains source-preserving.

- [ ] **Step 2: Wire helper installation into `browserAppJs`**

Before loading a live scene, import:

```js
const helperMod = await import('/live/default-scenes/capybara-webgl-helpers.js?token=' + encodeURIComponent(cfg.liveToken));
window.__hmThreeHelpers = await helperMod.installCapybaraWebGLHelpers(THREE, renderer, cfg);
```

If this exact `/live/default-scenes/...` path is awkward because default helpers are packaged, serve it under an explicit `/default-scenes/` tokenized route instead and adjust the import URL.

- [ ] **Step 3: Commit helpers**

```bash
git add packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-webgl-helpers.js packages/threejs-sidebar-sidecar/sidecar/browser-webgl/main.ts
git commit -m "feat: add webgl helpers for capybara scene port"
```

---

### Task 7: Add source-preserving Capybara default scene

**Files:**
- Create: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-onsen-webgl.scene.js`
- Create: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-source-retention.md`

- [ ] **Step 1: Copy the source scene**

```bash
cp /Users/MAC/Documents/eidoverse-video/work/capybara-onsen-v2/wide-gap-scene.js \
  packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-onsen-webgl.scene.js
```

- [ ] **Step 2: Apply mechanical wrapper changes**

Edit the copied file with these exact structural changes:

1. Add at the top:

```js
import { installCapybaraWebGLHelpers } from './capybara-webgl-helpers.js';
const THREE = globalThis.THREE;

export const assets = {
  hdri: 'work/capybara-onsen-v2/assets/hdri.hdr',
  lanternModel: 'work/capybara-onsen-v2/assets/lantern_01_embedded.gltf',
  stoneAlbedo: 'work/capybara-onsen-v2/assets/wet_river_stone/wet_river_stone_diff.jpg',
  stoneNormal: 'work/capybara-onsen-v2/assets/wet_river_stone/wet_river_stone_normal.jpg',
  stoneRough: 'work/capybara-onsen-v2/assets/wet_river_stone/wet_river_stone_rough.jpg',
  bambooAlbedo: 'work/capybara-onsen-v2/assets/bamboo/Bamboo001C_Color.jpg',
  bambooNormal: 'work/capybara-onsen-v2/assets/bamboo/Bamboo001C_NormalGL.jpg',
  bambooRough: 'work/capybara-onsen-v2/assets/bamboo/Bamboo001C_Roughness.jpg',
  woodAlbedo: 'work/capybara-onsen-v2/assets/warm_cedar_wood/texturecan_135_diff.jpg',
  woodNormal: 'work/capybara-onsen-v2/assets/warm_cedar_wood/texturecan_135_normal_dx_8bit.png',
  woodRough: 'work/capybara-onsen-v2/assets/warm_cedar_wood/texturecan_135_rough.jpg',
  smokeTex: 'eidoverse/assets/particle_textures/smoke_07.png',
  sparkTex: 'eidoverse/assets/particle_textures/spark_05.png',
  glowTex: 'eidoverse/assets/particle_textures/glow_soft.png',
};
```

2. Replace `globalThis.setup = async function () {` with:

```js
export async function createScene(ctx) {
    const { THREE: THREE_FROM_CTX, renderer, cfg, helpers } = ctx;
    const helperSet = helpers && helpers.THREE ? helpers : await installCapybaraWebGLHelpers(THREE_FROM_CTX, renderer, cfg);
    globalThis.THREE = helperSet.THREE;
    globalThis.makeParticles = helperSet.makeParticles;
    const { createWaterCompute } = helperSet;
    const WIDTH = cfg.sourceWidth || 1280;
    const HEIGHT = cfg.sourceHeight || 720;
```

3. Delete the WebGPU renderer construction block:

```js
const renderer = new THREE.WebGPURenderer({ canvas, antialias: true, adapter: GPU_ADAPTER, device: GPU_DEVICE });
renderer.setSize(WIDTH, HEIGHT);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
await renderer.init();
```

Replace it with:

```js
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
```

4. Replace:

```js
const { HDRLoader } = await import('npm:three@0.184.0/addons/loaders/HDRLoader.js');
```

with:

```js
const { HDRLoader } = globalThis;
```

5. Replace:

```js
const { createWaterCompute } = await import(globalThis.EIDOVERSE_DIR + 'water_compute.js');
```

with no statement, because `createWaterCompute` is already in scope from helperSet.

6. Replace the end of setup where it assigns globals with:

```js
    globalThis._s = scene;
    globalThis._c = camera;
    globalThis._rich = { camera, water, stream, drops, capyA, capyB, yuzu, spirit, lantern, bambooFeature, warmFill, moonKey };
    return {
        scene,
        camera,
        update: globalThis.renderFrame,
        dispose() {
            scene.traverse((obj) => {
                if (obj.geometry && typeof obj.geometry.dispose === 'function') obj.geometry.dispose();
                const mats = Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : [];
                for (const mat of mats) if (mat && typeof mat.dispose === 'function') mat.dispose();
            });
        },
    };
}
```

7. Replace `globalThis.renderFrame = async function (t) {` with:

```js
async function renderCapybaraFrame(t) {
```

and replace `await globalThis._r.renderAsync(globalThis._s, globalThis._c);` with:

```js
    for (const obj of globalThis._s.children) {
        if (obj && typeof obj.userData?.update === 'function') obj.userData.update(t);
    }
```

8. Before returning the scene instance, assign:

```js
globalThis.renderFrame = renderCapybaraFrame;
```

- [ ] **Step 3: Confirm no WebGPU renderer remains**

Run:

```bash
rg -n "WebGPURenderer|renderAsync|three@0\.184\.0/tsl|water_compute" packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-onsen-webgl.scene.js
```

Expected: no matches for `WebGPURenderer`, `renderAsync`, `three@0.184.0/tsl`, or `water_compute`.

- [ ] **Step 4: Create source-retention note**

Create `capybara-source-retention.md` with:

```markdown
# Capybara BrowserWebGL Source Retention

Source: `/Users/MAC/Documents/eidoverse-video/work/capybara-onsen-v2/wide-gap-scene.js`

Retained intentionally:
- actor construction functions (`makeCapybara`, `makeCapybaraFaceDetails`, `makeYuzuCluster`, `makeBambooSpout`, `makeSideBambooGrove`, `makeBathSpirit`, `loadLanternModel`)
- actor/object names used by the original scene
- animation timing formulas for breathing, ear flick, water pulse, drops, yuzu/spirit drift, lantern glow, warm fill, and camera drift
- camera framing function `wideCenterSafeCamera`
- two-panel composition constants

Intentional changes:
- renderer construction removed; BrowserWebGL sidecar owns `THREE.WebGLRenderer`, render target, readback, and final render calls
- `globalThis.setup/renderFrame` converted to `createScene(ctx)` plus returned `update(t)`
- WebGPU `water_compute.js` replaced by API-compatible WebGL helper
- TSL `makeParticles` replaced by API-compatible WebGL helper
- `npm:` addon import replaced by sidecar-provided browser addon globals
- `renderAsync` removed because WebGLRenderer uses synchronous `render`

Acceptance rule: future edits should keep actor/timing code source-close unless they are directly required by BrowserWebGL compatibility or verified visual smoke.
```

- [ ] **Step 5: Commit default scene port**

```bash
git add packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-onsen-webgl.scene.js packages/threejs-sidebar-sidecar/sidecar/browser-webgl/default-scenes/capybara-source-retention.md
git commit -m "feat: add source-preserving capybara webgl scene"
```

---

### Task 8: Add browser addon and asset loading support

**Files:**
- Modify: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/main.ts`
- Modify: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene.ts`
- Modify: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene_test.ts`

- [ ] **Step 1: Add allowlisted vendor addon routes**

Extend `/vendor/` handling to allow these exact addon paths only:

```ts
const ALLOWED_VENDOR_ADDONS = new Set([
  "addons/loaders/GLTFLoader.js",
  "addons/loaders/HDRLoader.js",
  "addons/loaders/DRACOLoader.js",
  "addons/utils/BufferGeometryUtils.js",
]);
```

Serve them from `joinPath(assetRoot, "node_modules", "three", "examples", "jsm", relativeWithoutAddonsPrefix)` for `/vendor/addons/...` requests. Keep existing direct `three/build` serving for `/vendor/three.module.js` and related build files.

- [ ] **Step 2: Install loader globals in browser app**

In `browserAppJs()`, after importing THREE:

```js
const [{ GLTFLoader }, { HDRLoader }] = await Promise.all([
  import('/vendor/addons/loaders/GLTFLoader.js'),
  import('/vendor/addons/loaders/HDRLoader.js'),
]);
globalThis.GLTFLoader = GLTFLoader;
globalThis.HDRLoader = HDRLoader;
```

- [ ] **Step 3: Add default Capybara asset route**

In `main.ts`, read `THREE_SIDECAR_EIDOVERSE_ROOT`. Add `/live-assets/<key>` route that maps keys from the default scene `assets` object to paths under that root only. Use realpath checks so no asset escapes the configured root.

- [ ] **Step 4: Add browser asset prefetch**

In the browser loader, after importing the scene module and before calling `createScene(ctx)`:

```js
async function installSceneAssets(mod) {
  const assets = mod.assets || {};
  const out = {};
  for (const [key, rel] of Object.entries(assets)) {
    const res = await fetch('/live-assets/' + encodeURIComponent(key) + '?token=' + encodeURIComponent(cfg.liveToken), { cache: 'no-store' });
    if (!res.ok) throw new Error('asset failed: ' + key + ' HTTP ' + res.status);
    out[key] = new Uint8Array(await res.arrayBuffer());
  }
  globalThis.ASSETS = out;
}
```

Call `await installSceneAssets(mod);` before `mod.createScene(ctx)`.

- [ ] **Step 5: Run tests**

```bash
cd packages/threejs-sidebar-sidecar/sidecar/browser-webgl
/opt/homebrew/bin/deno test --allow-read --allow-write --allow-env main_test.ts live_scene_test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit addon/asset support**

```bash
git add packages/threejs-sidebar-sidecar/sidecar/browser-webgl/main.ts packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene.ts packages/threejs-sidebar-sidecar/sidecar/browser-webgl/live_scene_test.ts
git commit -m "feat: serve allowlisted capybara webgl assets"
```

---

### Task 9: Update docs and package tests for the complete feature

**Files:**
- Modify: `packages/threejs-sidebar-sidecar/README.md`
- Modify: `packages/threejs-sidebar-sidecar/sidecar/browser-webgl/README.md`
- Modify: `tests/test_threejs_sidebar_live_scene.py`

- [ ] **Step 1: Document live JS mode**

Add to both READMEs:

```markdown
### Browser WebGL live JS scene mode

`capybara-onsen-threejs-sidecar` selects BrowserWebGL live JS mode. On first run, the sidecar creates `~/.claude/harnessmonkey/threejs/scene.js` from the packaged Capybara WebGL default scene if the file is missing. It never overwrites an existing file. The browser app polls for changes every two seconds and reloads the JavaScript module in place. Broken reloads keep the last good scene and emit a non-fatal `scene-error` diagnostic.

The scene file is ordinary browser ESM and should export `createScene(ctx)`. It is code, not JSON scene state.
```

- [ ] **Step 2: Extend package tests**

Add assertions to `tests/test_threejs_sidebar_live_scene.py`:

```python
def test_browser_webgl_default_scene_is_live_js_not_video() -> None:
    scene = (THREE_PACKAGE / "sidecar" / "browser-webgl" / "default-scenes" / "capybara-onsen-webgl.scene.js").read_text(encoding="utf-8")
    assert "export async function createScene" in scene
    assert "WebGPURenderer" not in scene
    assert "renderAsync" not in scene
    assert "VideoTexture" not in scene
    assert "left_soaking_capybara_brave_soaking_with_towel" in scene
    assert "right_sleepy_capybara_graceful_lounging" in scene
```

- [ ] **Step 3: Run Python tests**

```bash
uv run pytest tests/test_threejs_sidebar_live_scene.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit docs/tests**

```bash
git add packages/threejs-sidebar-sidecar/README.md packages/threejs-sidebar-sidecar/sidecar/browser-webgl/README.md tests/test_threejs_sidebar_live_scene.py
git commit -m "docs: describe live browser webgl scene mode"
```

---

### Task 10: Verification and manual smoke preparation

**Files:**
- No required source edits unless verification exposes bugs.

- [ ] **Step 1: Run Python tests for new contracts**

```bash
uv run pytest tests/test_threejs_sidebar_live_scene.py tests/test_pool_hop_composition.py tests/test_capybara_onsen.py -q
```

Expected: PASS or documented skips for missing local Claude source.

- [ ] **Step 2: Run BrowserWebGL Deno tests**

```bash
cd packages/threejs-sidebar-sidecar/sidecar/browser-webgl
/opt/homebrew/bin/deno test --allow-read --allow-write --allow-env main_test.ts live_scene_test.ts
```

Expected: PASS.

- [ ] **Step 3: Validate package manifest**

```bash
uv run harnessmonkey validate-package \
  --source /Users/MAC/.local/share/claude/versions/2.1.201 \
  --package packages/threejs-sidebar-sidecar \
  --source-version 2.1.201 \
  --source-version-output '2.1.201 (Claude Code)' \
  --platform darwin \
  --arch arm64
```

Expected: validation passes with `ok=true`.

- [ ] **Step 4: Build BrowserWebGL Deno Desktop app**

```bash
cd packages/threejs-sidebar-sidecar/sidecar/browser-webgl
./build-browser-webgl.sh
```

Expected: `dist/ThreeJsBrowserWebglSidecar.app` is created locally and remains untracked.

- [ ] **Step 5: Run sidecar smoke with live JS**

```bash
cd packages/threejs-sidebar-sidecar/sidecar/browser-webgl
CLAUDEMONKEY_THREE_SIDECAR_SCENE=live-js \
CLAUDEMONKEY_THREE_SIDECAR_LIVE_SCENE=~/.claude/harnessmonkey/threejs/scene.js \
CLAUDEMONKEY_THREE_SIDECAR_LIVE_ROOT=~/.claude/harnessmonkey/threejs \
CLAUDEMONKEY_THREE_SIDECAR_RELOAD_MS=2000 \
THREE_SIDECAR_EIDOVERSE_ROOT=/Users/MAC/Documents/eidoverse-video \
THREE_SIDECAR_CHAFA_BIN=/opt/homebrew/bin/chafa \
THREE_SIDECAR_BROWSER_WEBGL_WINDOW_MODE=offscreen \
./run-sidecar-browser-webgl.sh --width 160 --height 54 --fps 8 --frames 3 --scene live-js --ansi chafa-vhalf --layout two-side --left-width 50 --right-width 50
```

Expected stdout includes one `hello`, one `system-reminder`, and at least one `frame-pair`. No fatal `error` appears.

- [ ] **Step 6: Run reload smoke**

With the sidecar running without `--frames`, edit `~/.claude/harnessmonkey/threejs/scene.js` by changing a visible color constant. Expected: frame output changes within roughly two seconds without process restart.

Then temporarily write an invalid scene file:

```bash
cp ~/.claude/harnessmonkey/threejs/scene.js /tmp/hm-scene-good.js
printf 'export async function createScene(){ throw new Error("reload smoke") }\n' > ~/.claude/harnessmonkey/threejs/scene.js
```

Expected: sidecar emits `scene-error` and keeps rendering the previous valid scene. Restore:

```bash
mv /tmp/hm-scene-good.js ~/.claude/harnessmonkey/threejs/scene.js
```

- [ ] **Step 7: Commit any verification fixes**

If verification required edits:

```bash
git add <changed files>
git commit -m "fix: stabilize live browser webgl verification"
```

If no edits were required, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage:
  - live JS file under `~/.claude`: Tasks 2, 4, 5, 10
  - no JSON scene state: Tasks 2, 7, 9
  - BrowserWebGL + Chafa: Tasks 2, 5, 10
  - `dWc(...)`-anchored system reminder bridge: Task 3
  - non-fatal reload errors: Task 5
  - hardened live serving: Tasks 4, 5, 8
  - source-preserving Capybara port: Tasks 6, 7, 9
  - option migration away from WebGPU: Task 2
- Placeholder scan: no forbidden placeholder markers are intentionally present.
- Type consistency: live scene instance is `{ scene, camera, update, dispose }`; helper API uses `createWaterCompute(renderer, opts)` and `makeParticles(opts)` consistently.
