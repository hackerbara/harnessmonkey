# Shared Drawer Card Scrolling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shared drawer framework own card rendering and nested card scrolling for Hidden Context, Thinking, and Codex Work, while leaving Reminders custom and Markdown Preview as flat-content.

**Architecture:** `drawer-dock` becomes the only card renderer for any frame that exposes `frame.blocks`. Card scroll state becomes `{cardIndex, innerOffset, key}`: the drawer scrolls within a large card before advancing to the next card, and uses stable card keys to survive live updates. Hidden Context and Thinking continue to produce blocks but stop using row-offset semantics; Codex Work becomes a block producer and delegates panel rendering to `drawer-dock`.

**Tech Stack:** HarnessMonkey public patch packages, Bun graph repack payload JavaScript, Ink/React component literals already present in Claude Code's bundled module, Python pytest package tests, `harnessmonkey validate-package`, local build smoke only.

---

## File Structure

- Modify `packages/drawer-dock/payloads/01-real-target-helpers-and-overlay.js`
  - Replace flattened block row slicing with shared card rendering.
  - Add card scroll normalization, nested intra-card scroll advancement, stable keys, colored card title helper, omitted-line click support, and generic key/wheel helpers.
  - Keep the existing `flatContent` line renderer for Markdown Preview only.
  - Keep the Reminders action wrapper exception.

- Modify `packages/hidden-context-drawer/payloads/01-projection-helpers-before-ypr-2.1.201.js`
  - Keep block generation.
  - Add `cardCount` and stop treating `lineCount` as the renderer's scroll range.
  - Preserve diagnostic `lines`/`lineKinds` if useful, but they are not the card-rendering contract.

- Modify `packages/hidden-context-drawer/payloads/17-panel-real-target.js`
  - Continue delegating to `__codexFDRenderDrawerPanel`.
  - No custom renderer.
  - Pass the same scroll global/setter; the shared renderer now stores card scroll objects.

- Modify `packages/thinking-drawer/payloads/01-thinking-text-helpers.js`
  - Replace row-offset thinking scroll with card scroll state.
  - Preserve live/provisional entry keys so character-by-character deltas update a stable card.
  - Refresh scroll by anchor key across live updates and structured/final merges.

- Modify `packages/thinking-drawer/payloads/17-panel-real-target.js`
  - Continue delegating to shared drawer panel.
  - Use a thinking scroll setter that stores card scroll objects.

- Modify `packages/codex-work-drawer/payloads/01-codex-work-helpers.js`
  - Return `frame.blocks`, not `frame.cards`.
  - Keep assistant-message parsing and omitted expansion state.
  - Make `__codexCWDKey` delegate to shared card scrolling.

- Modify `packages/codex-work-drawer/payloads/17-panel-real-target.js`
  - Delete the custom card renderer.
  - Render through `__codexFDRenderDrawerPanel` with `onOmittedClick: __codexCWDClickOmitted`.

- Modify `packages/markdown-preview-drawer/payloads/03-md-link-preview-panel.js`
  - Keep Markdown Preview as a flat-content line drawer.
  - Update it to call the renamed line-scroll helper instead of the removed generic clamp helper.

- Modify tests:
  - `tests/test_drawer_dock_package.py`
  - `tests/test_hidden_context_drawer_package.py`
  - `tests/test_thinking_drawer_package.py`
  - `tests/test_codex_work_drawer_package.py`

---

## Task 1: Add shared card-scroll primitives to drawer-dock tests

**Files:**
- Modify: `tests/test_drawer_dock_package.py`

- [ ] **Step 1: Update the shared primitive test to reject row-sliced block rendering**

Replace the body of `test_footer_drawers_owns_shared_boxed_drawer_display_primitives` with assertions for the new contract:

```python
def test_footer_drawers_owns_shared_boxed_drawer_display_primitives() -> None:
    text = (FOOTER_DRAWERS / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    for name in [
        "__codexFDViewport",
        "__codexFDNormalizeCardScroll",
        "__codexFDCardRows",
        "__codexFDMaxInnerOffset",
        "__codexFDAdvanceCardScroll",
        "__codexFDVisibleCards",
        "__codexFDRenderCardList",
        "__codexFDVisibleLines",
        "__codexFDRenderLineList",
        "__codexFDRenderDrawerPanel",
        "__codexFDKeyScroll",
    ]:
        assert f"function {name}" in text
    assert "function __codexFDVisibleBlocks" not in text
    assert "__codexFDBlocksLineCount" not in text
    assert 'borderStyle:"single"' in text
    assert 'borderStyle:"round"' in text
    assert 'top:g' in text
    assert 'onWheel' in text
    assert 'bodyLines' in text
    assert 'flatContent' in text
    assert "innerOffset" in text
    assert "anchorKey" in text or "key:" in text
```

- [ ] **Step 2: Add a node-level behavior test for nested scrolling**

Add this test near the primitive test. It directly evaluates the helper payload with tiny Ink stubs, then proves down-scroll stays inside a large card before advancing.

```python
def test_footer_drawers_card_scroll_stays_inside_large_card_before_advancing() -> None:
    helper = (FOOTER_DRAWERS / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    script = f'''
const Xd = {{
  jsx: (type, props, key) => ({{type: typeof type === "function" ? type.name : type, props, key}}),
  jsxs: (type, props, key) => ({{type: typeof type === "function" ? type.name : type, props, key}}),
}};
function B(props) {{ return props; }}
function v(props) {{ return props; }}
function Er() {{ return {{rows: 40}}; }}
{helper}
const frame = {{blocks:[
  {{key:"a", header:"A", bodyLines:Array.from({{length:20}}, (_, i) => `a-${{i}}`)}},
  {{key:"b", header:"B", bodyLines:["b-0"]}},
]}};
let s = __codexFDNormalizeCardScroll(frame, 0, 8);
if (s.cardIndex !== 0 || s.innerOffset !== 0 || s.key !== "a") throw new Error(JSON.stringify(s));
s = __codexFDAdvanceCardScroll(frame, s, 1, 8);
if (s.cardIndex !== 0 || s.innerOffset <= 0) throw new Error("first down should scroll within card: "+JSON.stringify(s));
for (let i = 0; i < 20; i++) s = __codexFDAdvanceCardScroll(frame, s, 1, 8);
if (s.cardIndex !== 1 || s.innerOffset !== 0 || s.key !== "b") throw new Error("should advance to next card after card bottom: "+JSON.stringify(s));
const last = __codexFDAdvanceCardScroll(frame, s, 1, 8);
if (last.cardIndex !== 1 || last.innerOffset !== 0 || last.key !== "b") throw new Error("down at last card should stay put: "+JSON.stringify(last));
s = __codexFDAdvanceCardScroll(frame, s, -1, 8);
if (s.cardIndex !== 0 || s.innerOffset <= 0 || s.key !== "a") throw new Error("up from next card should return to previous card bottom: "+JSON.stringify(s));
const top = __codexFDAdvanceCardScroll(frame, {{cardIndex:0, innerOffset:0, key:"a"}}, -1, 8);
if (top.cardIndex !== 0 || top.innerOffset !== 0 || top.key !== "a") throw new Error("up at first card top should stay put: "+JSON.stringify(top));
const visible = __codexFDVisibleCards(frame, {{cardIndex:0, innerOffset:3, key:"a"}}, 8);
if (visible.length !== 1) throw new Error("large clipped card should occupy viewport");
if (visible[0].bodyOffset !== 3) throw new Error("body offset not preserved");
console.log(JSON.stringify({{ok:true}}));
'''
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["ok"] is True
```

- [ ] **Step 3: Run the focused test and observe failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_drawer_dock_package.py::test_footer_drawers_owns_shared_boxed_drawer_display_primitives tests/test_drawer_dock_package.py::test_footer_drawers_card_scroll_stays_inside_large_card_before_advancing -q
```

Expected: FAIL because the helper names and behavior do not exist yet.

---

## Task 2: Implement shared card renderer and nested scroll in drawer-dock

**Files:**
- Modify: `packages/drawer-dock/payloads/01-real-target-helpers-and-overlay.js`

- [ ] **Step 1: Replace row-sliced block helpers with card helpers**

In `01-real-target-helpers-and-overlay.js`, replace these functions:

```js
function __codexFDClampScroll(e,t,n){...}
function __codexFDBlockLineCount(e){...}
function __codexFDBlocksLineCount(e){...}
function __codexFDVisibleBlocks(e,t,n){...}
function __codexFDRenderBlockList(e){...}
```

with compact helpers equivalent to this behavior:

```js
function __codexFDClampLineScroll(e,t,n){let r=__codexFDViewport(n),o=Math.max(0,(Number(t)||1)-r);return Math.max(0,Math.min(Number(e)||0,o))}
function __codexFDBlocks(e){return Array.isArray(e?.blocks)?e.blocks:[]}
function __codexFDCardCount(e){let t=__codexFDBlocks(e).length;return t>0?t:1}
function __codexFDCardTitle(e){return String(e?.title??e?.header??"")}
function __codexFDCardColor(e,t){return e?.borderColor||e?.color||(e?.kind==="omitted"||e?.kind==="empty"?"warning":t||"permission")}
function __codexFDBorderTitle(e,t){let n=e==="warning"?"\x1b[33m":"\x1b[34m";return` ${n}${String(t||"")}\x1b[39m `}
function __codexFDNormalizeCardScroll(e,t,n){let r=__codexFDBlocks(e),o=__codexFDCardCount(e),s=typeof t==="object"&&t!==null?t:{cardIndex:Number(t)||0,innerOffset:0},i=s.key||s.anchorKey||null,a=i?r.findIndex(c=>c?.key===i):-1,l=a>=0?a:Math.max(0,Math.min(Number(s.cardIndex)||0,o-1)),u=r[l],d=__codexFDMaxInnerOffset(u,n),p=Math.max(0,Math.min(Number(s.innerOffset)||0,d));return{cardIndex:l,innerOffset:p,key:u?.key??String(l)}}
function __codexFDCardRows(e,t){let n=t>0?1:0,r=Array.isArray(e?.meta)&&e.meta.length?1:0,o=Math.max(1,(e?.bodyLines||[""]).length);return n+2+r+o}
function __codexFDCardBodyBudget(e,t){let n=Array.isArray(e?.meta)&&e.meta.length?1:0;return Math.max(1,__codexFDViewport(t)-2-n)}
function __codexFDMaxInnerOffset(e,t){let n=Math.max(1,(e?.bodyLines||[""]).length),r=__codexFDCardBodyBudget(e,t);return Math.max(0,n-r)}
function __codexFDAdvanceCardScroll(e,t,n,r){let o=__codexFDBlocks(e),s=__codexFDNormalizeCardScroll(e,t,r),i=__codexFDScrollStep(),a=__codexFDMaxInnerOffset(o[s.cardIndex],r);if(n>0){if(s.innerOffset<a)return __codexFDNormalizeCardScroll(e,{...s,innerOffset:s.innerOffset+i},r);if(s.cardIndex>=o.length-1)return s;let l=s.cardIndex+1;return __codexFDNormalizeCardScroll(e,{cardIndex:l,innerOffset:0,key:o[l]?.key},r)}if(n<0){if(s.innerOffset>0)return __codexFDNormalizeCardScroll(e,{...s,innerOffset:s.innerOffset-i},r);if(s.cardIndex<=0)return s;let l=s.cardIndex-1,c=__codexFDMaxInnerOffset(o[l],r);return __codexFDNormalizeCardScroll(e,{cardIndex:l,innerOffset:c,key:o[l]?.key},r)}return __codexFDNormalizeCardScroll(e,{cardIndex:0,innerOffset:0},r)}
function __codexFDClipCardForViewport(e,t,n,r){let o=e?.bodyLines||[""],s=__codexFDCardBodyBudget(e,t),i=Math.max(0,Math.min(Number(n)||0,Math.max(0,o.length-s))),a=o.slice(i,i+s);return{...e,bodyLines:a.length?a:[""],bodyOffset:i,viewportClipped:o.length>s}}
function __codexFDVisibleCards(e,t,n){let r=__codexFDBlocks(e),o=__codexFDNormalizeCardScroll(e,t,n),s=[],i=0;if(!r.length)return[];let a=__codexFDClipCardForViewport(r[o.cardIndex],n,o.innerOffset,0);s.push(a);i+=__codexFDCardRows(a,0);if(a.viewportClipped)return s;for(let l=o.cardIndex+1;l<r.length;l++){let c=__codexFDCardRows(r[l],s.length);if(i+c>__codexFDViewport(n))break;s.push(r[l]);i+=c}return s}
```

Keep names compact and ASCII-only, matching existing payload style.

- [ ] **Step 2: Add shared omitted-line rendering**

Add helpers equivalent to:

```js
function __codexFDOmittedLine(e){return /^\.\.\. \d+ .*omitted.*click/.test(String(e||""))}
function __codexFDCanClickLine(e,t){return __codexFDOmittedLine(t)&&(e?.expandKey&&!e?.expanded||e?.expandOlder)}
function __codexFDRenderBodyLine(e,t,n,r,o){let s=Number(e?.bodyOffset)||0,i=s+r,a=__codexFDCanClickLine(e,n),l=Xd.jsx(v,{dimColor:a||e?.viewportClipped&&/^\.\.\./.test(String(n||"")),wrap:"truncate-end",children:n},`${e.key||o}:body:${i}`);return a?Xd.jsx(B,{onClick:()=>t?.(e),width:"100%",children:l},`${e.key||o}:click:${i}`):l}
function __codexFDRenderCard(e,t,n,r,o){let s=__codexFDCardColor(e,n),i=e?.meta||[],a=e?.bodyLines||[""];return Xd.jsxs(B,{flexDirection:"column",width:"100%",flexShrink:0,borderStyle:"single",borderColor:s,borderText:{content:__codexFDBorderTitle(s,__codexFDCardTitle(e)),position:"top",align:"start",offset:1},paddingX:1,marginTop:t===0?0:1,children:[i.length>0&&Xd.jsx(v,{dimColor:!0,wrap:"truncate-end",children:i.join(" | ")},`${e.key||t}:meta`),...a.map((l,c)=>__codexFDRenderBodyLine(e,o,l,c,t))]},e.key||t)}
function __codexFDRenderCardList(e){let t=__codexFDVisibleCards(e?.frame,e?.scroll,e?.viewport),n=e?.borderColor||"permission";return t.map((r,o)=>__codexFDRenderCard(r,o,n,e?.refresh,e?.onOmittedClick))}
```

- [ ] **Step 3: Update line-mode helpers to use line-specific clamp only**

Change line helpers to call `__codexFDClampLineScroll`, not the old generic block clamp:

```js
function __codexFDVisibleLines(e,t,n){let r=e?.lines||[],o=Math.max(0,Number(t)||0),s=o+__codexFDViewport(n);return r.slice(o,s)}
function __codexFDRenderLineList(e){let t=__codexFDVisibleLines(e?.frame,e?.scroll,e?.viewport);return t.map((n,r)=>Xd.jsx(v,{wrap:"wrap",children:n},`line:${(Number(e?.scroll)||0)+r}`))}
```

- [ ] **Step 4: Update generic drawer panel to branch between flat lines and cards**

In `__codexFDRenderDrawerPanel`, keep `flatContent`/`renderMode:"lines"` line behavior, but make `frame.blocks` use card scroll state:

```js
let f=e?.flatContent===!0||t.renderMode==="lines"||Array.isArray(t.lines)&&!Array.isArray(t.blocks);
let l=f?__codexFDClampLineScroll(globalThis[e?.scrollGlobal]??t.scroll??0,t.lineCount??t.lines?.length??1,i):__codexFDNormalizeCardScroll(t,globalThis[e?.scrollGlobal]??t.scroll??0,i);
let h=f?__codexFDRenderLineList({frame:t,scroll:l,viewport:i,borderColor:r}):__codexFDRenderCardList({frame:t,scroll:l,viewport:i,borderColor:r,refresh:m=>e?.refresh?.(m),onOmittedClick:e?.onOmittedClick});
```

Status text should mention cards when rendering blocks:

```js
let y=f?"up/down or mouse wheel scroll | x closes":`card ${l.cardIndex+1}/${__codexFDCardCount(t)} | up/down or wheel | x closes`;
```

Wheel handling should use line clamping for line mode and `__codexFDAdvanceCardScroll` for card mode.

- [ ] **Step 5: Add generic key scroll helper and update drawer-specific key paths**

Add:

```js
function __codexFDSetDrawerScroll(e,t,n){let r=e?.flatContent===!0||e?.frame?.renderMode==="lines"?__codexFDClampLineScroll(t,e?.frame?.lineCount??e?.frame?.lines?.length??1,n):__codexFDNormalizeCardScroll(e?.frame,t,n);if(e?.scrollGlobal)globalThis[e.scrollGlobal]=r;try{e?.onScroll?.(r,e?.frame?.lineCount??1,n)}catch{}try{e?.setScroll?.(r)}catch{}try{e?.refresh?.(Date.now())}catch{}return r}
function __codexFDKeyScroll(e,t){let n=globalThis[e?.viewportGlobal]||18,r=e?.frame,o=globalThis[e?.scrollGlobal]??r?.scroll??0,s=t==="jumpTop"?__codexFDNormalizeCardScroll(r,{cardIndex:0,innerOffset:0},n):__codexFDAdvanceCardScroll(r,o,t==="down"?1:-1,n);return __codexFDSetDrawerScroll(e,s,n),!0}
```

Then make Hidden Context, Thinking, and Codex key handlers call `__codexFDKeyScroll` instead of calculating line offsets or card indices themselves. For Thinking, pass `onScroll:o=>__codexTTDSetScroll(o)` into `__codexFDKeyScroll`; otherwise global scroll updates but the thinking frame cache can retain stale numeric scroll.

- [ ] **Step 6: Run drawer-dock focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_drawer_dock_package.py::test_footer_drawers_owns_shared_boxed_drawer_display_primitives tests/test_drawer_dock_package.py::test_footer_drawers_card_scroll_stays_inside_large_card_before_advancing -q
```

Expected: PASS.

---

## Task 3: Migrate Hidden Context to card-scroll state

**Files:**
- Modify: `packages/hidden-context-drawer/payloads/01-projection-helpers-before-ypr-2.1.201.js`
- Modify: `packages/hidden-context-drawer/payloads/17-panel-real-target.js`
- Modify: `tests/test_hidden_context_drawer_package.py`

- [ ] **Step 1: Update hidden context test expectations**

In `test_hidden_context_frame_exposes_shared_render_blocks`, replace the line-count assertion:

```python
assert(frame.lineCount >= frame.blocks[0].bodyLines.length + 3, 'lineCount should include box border/header overhead');
```

with:

```python
assert(frame.cardCount === frame.blocks.length, 'cardCount should track shared card blocks');
assert(frame.blocks[0].key === 'row-1', 'stable card key should preserve attachment identity');
```

- [ ] **Step 2: Update hidden context frame construction**

In `__codexNCHCDrawerFrameFromList`, keep `blocks:d`, keep diagnostic `lines` if existing tests still use them, but set:

```js
cardCount:d.length,lineCount:d.length||1,scroll:globalThis.__CODEX_HIDDEN_CONTEXT_DRAWER_SCROLL_V13__||0
```

Do not call `__codexFDBlocksLineCount` anymore.

- [ ] **Step 3: Keep the panel as shared-renderer-only**

`17-panel-real-target.js` should still call:

```js
return __codexFDRenderDrawerPanel({title:"Hidden Context",countText:`${n?.tokenCount??0} tokens`,borderColor:"warning",frame:n,scrollGlobal:"__CODEX_HIDDEN_CONTEXT_DRAWER_SCROLL_V13__",viewportGlobal:"__CODEX_HIDDEN_CONTEXT_DRAWER_VIEWPORT_V13__",setScroll:globalThis.__CODEX_HIDDEN_CONTEXT_DRAWER_SET_SCROLL_V13__,refresh:t})
```

No custom hidden renderer is added.

- [ ] **Step 4: Run hidden context tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_hidden_context_drawer_package.py -q
```

Expected: PASS.

---

## Task 4: Migrate Thinking to anchored card scroll

**Files:**
- Modify: `packages/thinking-drawer/payloads/01-thinking-text-helpers.js`
- Modify: `packages/thinking-drawer/payloads/17-panel-real-target.js`
- Modify: `tests/test_thinking_drawer_package.py`

- [ ] **Step 1: Add a thinking test for stable live-delta card identity**

Add a test after `test_helper_fixture_merge_and_actual_text_only_sources` or near other helper fixture tests:

```python
def test_thinking_live_deltas_keep_one_stable_card_and_scroll_anchor() -> None:
    helper = read_rel("payloads/01-thinking-text-helpers.js")
    drawer = (ROOT / "packages" / "drawer-dock" / "payloads" / "01-real-target-helpers-and-overlay.js").read_text(encoding="utf-8")
    script = textwrap.dedent(
        f"""
        const Xd = {{ jsx:()=>null, jsxs:()=>null }};
        function B(props) {{ return props; }}
        function v(props) {{ return props; }}
        function Er() {{ return {{rows: 40}}; }}
        {drawer}
        {helper}
        globalThis.__CODEX_THINKING_TEXT_DRAWER_FRAME_V1__ = undefined;
        globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__ = 8;
        __codexTTDRecordLiveThinking({{text:'a', streamKey:'s1', turnKey:'turn'}});
        let frame = __codexTTDDrawerFrame();
        const key = frame.blocks[0].key;
        globalThis.__CODEX_THINKING_TEXT_DRAWER_SCROLL_V1__ = {{cardIndex:0, innerOffset:0, key}};
        __codexTTDRecordLiveThinking({{text:'bc', streamKey:'s1', turnKey:'turn'}});
        __codexTTDRecordLiveThinking({{text:'def', streamKey:'s1', turnKey:'turn'}});
        frame = __codexTTDDrawerFrame();
        if (frame.blocks.length !== 1) throw new Error(`blocks ${{frame.blocks.length}}`);
        if (frame.blocks[0].key !== key) throw new Error(`key changed ${{frame.blocks[0].key}} vs ${{key}}`);
        if (!frame.blocks[0].bodyLines.join("\\n").includes('abcdef')) throw new Error(frame.blocks[0].bodyLines.join("\\n"));
        if (frame.scroll.key !== key || frame.scroll.cardIndex !== 0) throw new Error(JSON.stringify(frame.scroll));
        console.log(JSON.stringify({{ok:true, key}}));
        """
    )
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["ok"] is True
```

- [ ] **Step 2: Update existing thinking row-scroll assertions**

In `test_helper_fixture_exposes_box_blocks_for_rendering`, replace the line-count overhead assertion with:

```js
assert(frame.cardCount === frame.blocks.length, 'cardCount should track shared card blocks');
assert(frame.lineCount === frame.cardCount, 'lineCount should no longer be flattened block rows');
```

In `test_helper_fixture_review_regressions`, remove direct `__codexTTDClampScroll(...)` calls. Replace the scroll section with card-scroll assertions that use `__codexTTDSetScroll({cardIndex:0, innerOffset:999, key:...})` for a large card and then assert `frame.scroll.innerOffset` clamps through `__codexFDNormalizeCardScroll`. For the structured-update case, assert the scroll `key` remains the same and `innerOffset` remains at the card bottom after that card grows.

- [ ] **Step 3: Replace thinking row-scroll helpers**

In `01-thinking-text-helpers.js`, keep text capture/merge behavior but replace line-scroll functions:

```js
function __codexTTDDrawerLineCount(e){...}
function __codexTTDClampScroll(e,t,r){...}
function __codexTTDRefreshScroll(e,t){...}
```

with card-aware equivalents:

```js
function __codexTTDDrawerCardCount(e){let t=__codexTTDVisibleEntries(e),n={...e,omittedEntryCount:Math.max(0,e.entries.length-t.length)},r=__codexTTDFrameBlocks(t,n);return r.length||1}
function __codexTTDSetScroll(e,t){let n=Array.isArray(t)?{blocks:t}:{blocks:__codexTTDFrameBlocks(__codexTTDVisibleEntries(__codexTTDEnsure()),__codexTTDEnsure())},r=typeof __codexFDNormalizeCardScroll==="function"?__codexFDNormalizeCardScroll(n,e,globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__||18):e,o=__codexTTDEnsure();o.scroll=r;globalThis.__CODEX_THINKING_TEXT_DRAWER_SCROLL_V1__=r;return r}
function __codexTTDRefreshScroll(e,t){let n=__codexTTDVisibleEntries(e),r={...e,omittedEntryCount:Math.max(0,e.entries.length-n.length)},o=__codexTTDFrameBlocks(n,r),s=globalThis.__CODEX_THINKING_TEXT_DRAWER_SCROLL_V1__??e.scroll??0,i=globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__||18,a=typeof __codexFDNormalizeCardScroll==="function"?__codexFDNormalizeCardScroll({blocks:o},s,i):s;if(t?.stickToBottom&&typeof __codexFDMaxInnerOffset==="function")a={...a,innerOffset:__codexFDMaxInnerOffset(o[a.cardIndex],i)};e.scroll=a;globalThis.__CODEX_THINKING_TEXT_DRAWER_SCROLL_V1__=a;return a}
```

Keep `__codexTTDLineCount` only if another diagnostic test uses it; it must not drive drawer scrolling.

- [ ] **Step 4: Update upsert/merge refresh calls**

In `__codexTTDUpsert` and `__codexTTDMergeStructured`, remove the previous-line-count argument. Before mutating an existing entry, calculate whether the current scroll is anchored to that entry and at that card's bottom:

```js
let beforeBlocks=__codexTTDFrameBlocks(__codexTTDVisibleEntries(t),{...t,omittedEntryCount:0});
let beforeScroll=typeof __codexFDNormalizeCardScroll==="function"?__codexFDNormalizeCardScroll({blocks:beforeBlocks},globalThis.__CODEX_THINKING_TEXT_DRAWER_SCROLL_V1__??t.scroll??0,globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__||18):t.scroll;
let beforeCard=beforeBlocks[beforeScroll?.cardIndex||0];
let wasAtCardBottom=beforeCard&&beforeScroll?.key===beforeCard.key&&typeof __codexFDMaxInnerOffset==="function"&&beforeScroll.innerOffset>=__codexFDMaxInnerOffset(beforeCard,globalThis.__CODEX_THINKING_TEXT_DRAWER_VIEWPORT_V1__||18);
```

After the mutation, call:

```js
__codexTTDRefreshScroll(t,{stickToBottom:wasAtCardBottom});
```

This preserves bottom anchoring when a live/provisional or structured card grows, while still preserving a fixed `innerOffset` when the user is reading the middle of a card.

- [ ] **Step 5: Update `__codexTTDDrawerFrame`**

Set card-oriented fields:

```js
cardCount:o.length,lineCount:o.length||1,scroll:__codexTTDRefreshScroll(e)
```

where `o` is the frame block array. Keep `lines` and `lineKinds` as diagnostic/export fields.

- [ ] **Step 6: Update Thinking panel onScroll callback**

Change panel callback from row-clamp to setter:

```js
onScroll:(o)=>__codexTTDSetScroll(o)
```

- [ ] **Step 7: Run thinking tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_thinking_drawer_package.py -q
```

Expected: PASS.

---

## Task 5: Migrate Codex Work to shared card rendering

**Files:**
- Modify: `packages/codex-work-drawer/payloads/01-codex-work-helpers.js`
- Modify: `packages/codex-work-drawer/payloads/17-panel-real-target.js`
- Modify: `tests/test_codex_work_drawer_package.py`
- Modify: `tests/test_drawer_dock_package.py` if needed for helper-name assertions

- [ ] **Step 1: Update Codex Work helper test from `cards` to `blocks`**

In `test_codex_work_helper_extracts_assistant_messages_and_expands_omissions`, replace frame/card reads:

```js
let card = frame.cards[0];
```

with:

```js
let card = frame.blocks[0];
```

and keep the existing omitted expansion assertions.

- [ ] **Step 2: Add test that Codex Work no longer ships a custom card renderer**

Add:

```python
def test_codex_work_panel_delegates_to_shared_drawer_renderer() -> None:
    panel = read_rel("payloads/17-panel-real-target.js")
    assert "__codexFDRenderDrawerPanel" in panel
    assert "__codexCWDRenderCard" not in panel
    assert "__codexCWDRenderPanel" not in panel
    assert "onOmittedClick:e=>__codexCWDClickOmitted(e,t)" in panel
```

- [ ] **Step 3: Change Codex Work frame shape**

In `__codexCWDFrame`, return blocks:

```js
return{title:"Codex Work",blocks:t,cardCount:t.length,entryCount:e.length,generation:__codexCWDSignature(e)}
```

Do not return `cards`.

- [ ] **Step 4: Change Codex Work key handler to shared card scroll**

Replace `__codexCWDClampScroll` and `__codexCWDKey` with:

```js
function __codexCWDKey(e){try{let t=__codexCWDFrame();return __codexFDKeyScroll({frame:t,scrollGlobal:"__CODEX_CODEX_WORK_DRAWER_SCROLL_V1__",viewportGlobal:"__CODEX_CODEX_WORK_DRAWER_VIEWPORT_V1__"},e)}catch{return!1}}
```

- [ ] **Step 5: Move omitted-click behavior out of the deleted custom panel**

Before replacing the panel file, move this function into `packages/codex-work-drawer/payloads/01-codex-work-helpers.js` so the shared panel can still call it:

```js
function __codexCWDClickOmitted(e,t){try{if(e?.expandOlder)globalThis.__CODEX_CODEX_WORK_DRAWER_SHOW_ALL_V1__=!0;else if(e?.expandKey)__codexCWDToggleExpanded(e.expandKey)}catch{}try{t?.(Date.now())}catch{}return!0}
```

- [ ] **Step 6: Replace custom Codex Work panel with shared panel**

Replace `17-panel-real-target.js` with:

```js
function __codexCWDPanel(){let[e,t]=A_.useState(0);A_.useEffect(()=>{let o=setInterval(()=>t(Date.now()),1000);return()=>clearInterval(o)},[]);let n=globalThis.__CODEX_CODEX_WORK_DRAWER_SELECTED_V1__===!0&&globalThis.__CODEX_CODEX_WORK_DRAWER_OPEN_V1__===!0;if(!n)return null;let r=__codexCWDFrame();return __codexFDRenderDrawerPanel({title:"Codex Work",countText:`${r?.entryCount??0} runs | assistant messages`,borderColor:"permission",frame:r,scrollGlobal:"__CODEX_CODEX_WORK_DRAWER_SCROLL_V1__",viewportGlobal:"__CODEX_CODEX_WORK_DRAWER_VIEWPORT_V1__",onOmittedClick:e=>__codexCWDClickOmitted(e,t),refresh:t})}
```

- [ ] **Step 7: Run Codex Work tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_codex_work_drawer_package.py -q
```

Expected: PASS.

---

## Task 6: Integrate action wrapper and drawer ordering checks

**Files:**
- Modify: `packages/drawer-dock/payloads/01-real-target-helpers-and-overlay.js`
- Modify: `tests/test_drawer_dock_package.py`

- [ ] **Step 1: Update action wrapper assertions if helper names changed**

In `test_footer_drawers_action_wrapper_routes_by_real_selected_target`, replace strict assertions that expect row-scroll functions with card-scroll helpers. Keep assertions that prove all targets route correctly:

```python
assert 'function __codexFDWrapRealTargetActions(e,t,n,r)' in text
assert 'function __codexFDScrollStep(){return 6}' in text
assert 't==="hiddenContext"' in text
assert 't==="thinking"' in text
assert 't==="reminders"&&typeof __codexRMWrapActions==="function"' in text
assert 't==="codexWork"' in text
assert '__codexFDKeyScroll' in text
assert 'footer:clearSelection' in text
assert 'footer:close' in text
assert 'footer:jumpTop' in text
```

- [ ] **Step 2: Ensure the action wrapper uses generic key scrolling for block drawers**

The wrapper should still special-case Reminders first. Hidden Context, Thinking, and Codex Work should all call card-aware helpers. The shape should be equivalent to:

```js
if(t==="hiddenContext"&&r?.hiddenOpen&&__codexFDHiddenContextScroll("up",r))return;
if(t==="thinking"&&globalThis.__CODEX_THINKING_TEXT_DRAWER_OPEN_V1__===!0&&__codexFDThinkingKey("up"))return;
if(t==="codexWork"&&globalThis.__CODEX_CODEX_WORK_DRAWER_OPEN_V1__===!0&&typeof __codexCWDKey==="function"&&__codexCWDKey("up"))return;
```

Use action strings (`"up"`, `"down"`, `"jumpTop"`) rather than numeric row deltas. Hidden Context must pass its current frame, `scrollGlobal`, `viewportGlobal`, `setScroll`, and `refresh` through to `__codexFDKeyScroll`; otherwise the global scroll object changes but the React state setter may not fire.

- [ ] **Step 3: Run drawer-dock package tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_drawer_dock_package.py -q
```

Expected: PASS or skip only for missing local Claude source artifacts.

---

## Task 7: Preserve Markdown Preview as flat-content line scrolling

**Files:**
- Modify: `packages/markdown-preview-drawer/payloads/03-md-link-preview-panel.js`
- Modify: `tests/test_markdown_preview_drawer_package.py` if existing assertions mention the old helper name

- [ ] **Step 1: Update Markdown Preview to use the line-scroll helper**

Replace `__codexFDClampScroll` calls with `__codexFDClampLineScroll` in `03-md-link-preview-panel.js`. The drawer must still pass `flatContent:!0` to `__codexFDRenderDrawerPanel`.

- [ ] **Step 2: Run Markdown Preview tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_markdown_preview_drawer_package.py -q
```

Expected: PASS.

---

## Task 8: Package validation and local smoke build

**Files:**
- No source files unless validation reveals manifest hash updates are required.

- [ ] **Step 1: Run focused package tests together**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_drawer_dock_package.py \
  tests/test_hidden_context_drawer_package.py \
  tests/test_thinking_drawer_package.py \
  tests/test_codex_work_drawer_package.py \
  tests/test_markdown_preview_drawer_package.py \
  tests/test_reminders_drawer.py \
  -q
```

Expected: PASS, with existing skips only where local Claude artifacts are unavailable.

- [ ] **Step 2: Run package validation for touched packages**

Run:

```bash
SRC="$HOME/.local/share/claude/versions/2.1.201"
.venv/bin/python -m harnessmonkey validate-package --source "$SRC" --package packages/drawer-dock --source-version 2.1.201 --source-version-output "2.1.201 (Claude Code)"
.venv/bin/python -m harnessmonkey validate-package --source "$SRC" --package packages/hidden-context-drawer --source-version 2.1.201 --source-version-output "2.1.201 (Claude Code)"
.venv/bin/python -m harnessmonkey validate-package --source "$SRC" --package packages/thinking-drawer --source-version 2.1.201 --source-version-output "2.1.201 (Claude Code)"
.venv/bin/python -m harnessmonkey validate-package --source "$SRC" --package packages/codex-work-drawer --source-version 2.1.201 --source-version-output "2.1.201 (Claude Code)"
.venv/bin/python -m harnessmonkey validate-package --source "$SRC" --package packages/markdown-preview-drawer --source-version 2.1.201 --source-version-output "2.1.201 (Claude Code)"
```

Expected: all five validations pass. If payload SHA mismatches occur, update only the touched operation replacement sha256 fields in the affected patch.json files to match the edited payload bytes, then rerun validation.

- [ ] **Step 3: Build a local test binary, not the live harness monkey**

Run the same local build style used by recent drawer work, writing under `.development/` only. If an exact helper script exists, use it; otherwise use the CLI package build command for the touched packages with output like:

```bash
.venv/bin/python -m harnessmonkey build \
  --package drawer-dock \
  --package hidden-context-drawer \
  --package thinking-drawer \
  --package codex-work-drawer \
  --package markdown-preview-drawer \
  --output-dir .development/build-shared-card-drawers
```

Expected: build succeeds and produces a local binary under `.development/build-shared-card-drawers/`.

- [ ] **Step 4: Do not sync to `/Users/MAC/.harnessmonkey/patches` yet**

Stop before home mirror sync. Report the local binary path and verification result first. The user can then decide whether to port/sync to the live installed HarnessMonkey state.

---

## Self-Review

- Spec coverage: the plan migrates all content/block drawers (`Hidden Context`, `Thinking`, `Codex Work`) to shared card rendering, keeps `Markdown Preview` as flat-content, and leaves `Reminders` custom.
- Nested scroll coverage: Task 1 and Task 2 explicitly test and implement intra-card scrolling before card advancement.
- Thinking live update coverage: Task 4 adds a live-delta stability test and uses key-anchored card scroll.
- Backcompat scope: no legacy `__codexFDVisibleBlocks` or `__codexFDBlocksLineCount` path remains in the shared renderer. Diagnostic `lines` may remain on frames, but not as the renderer contract.
- Live safety: Task 8 builds a local binary only and explicitly stops before home mirror sync.
