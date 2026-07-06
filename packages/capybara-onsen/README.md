# Capybara Onsen

A calming twilight Japanese hot spring flanks the Claude Code terminal — high-def
half-block pixel art. On the left, a capybara soaks to its chin while a thin
clear-blue stream from a bamboo kakei spout pours gently onto its head. On the
right, a second capybara rests on a rock shelf under the amber glow of a stone
lantern, flicking its ears every few seconds. Steam drifts off the water.

![preview](preview.png)

## What it does

- Renders **two independent walls** (no mirroring — it's one continuous scene) in
  30-column visible gutters clipped from 32-column source art: moon, stars, bamboo leaning inward, stepped mossy rocks,
  kakei spout + soaking capybara + floating yuzu (left); stone lantern with a
  warm dithered halo + resting capybara (right).
- **Animated regions** (bottom 22 cell rows only): the spout stream with
  descending pulses and impact spray, an expanding pool ripple, rising steam
  wisps, and the resting capybara's occasional double ear-flick.
- Each wall is a single full-height box spanning the entire terminal column,
  top to bottom edge, so the pool basin, floating yuzu, and subagent pups are
  never clipped (an earlier build capped wall height short of the bottom row
  and cut them off). The bottom chrome parent is tinted deep indigo
  `rgb(10,12,26)` so the seam between wall and chrome is invisible. The right
  gutter collapses at terminal widths `<= 140` columns and returns at `>= 141`.

## How it works (rendering)

Same skeleton as `heraldic-dragons`: pre-baked art drawn through the bundled
renderer's native `ink-raw-ansi` direct-draw node (`▀` half-blocks, fg=top /
bg=bottom subpixel → 2× vertical resolution, truecolor per subpixel). ANSI
strings are assembled once at module eval; per 180 ms tick only the two
animated-band strings swap (16 phases; water cycles at 8, the ear flick occupies
3 of 16 phases so the scene is still ~2.3 s between flicks).

Deliberate differences from the dragons:

- **Two authored walls** instead of left + runtime mirror (the scene is
  asymmetric).
- **Animated band at the BOTTOM** + `justifyContent:"flex-end"` containers: on
  short terminals the *sky* clips first — the capybaras and all motion survive
  any height.
- **180 ms tick** instead of 95 ms — calm cadence, fewer redraws.

Shared discipline:

- **Mojibake-safe**: payloads contain no literal `▀` or ESC bytes — both are
  produced at runtime via `String.fromCharCode(9600)` / `(27)`. Art data is
  embedded as numeric RLE run arrays.
- **Truecolor primary; 256-color fallback** via a 6×6×6 cube map at runtime.
- Static band is byte-identical across all 16 phases (asserted at compile time).

## Target

- Claude Code **2.1.201**, `darwin/arm64` (Bun standalone macho64).
- Module: `/$bunfs/root/src/entrypoints/cli.js`.
- Pinned by whole-binary SHA-256, whole-module SHA-256/length, and per-operation
  old-range SHA-256/length.

## Operations (seams)

All eleven are `replace_exact` inserts/replacements (non-overlapping). The
first eight sit at the same full-frame app-shell anchors as `heraldic-dragons` —
the two packages are **mutually exclusive**; the builder's byte-range overlap
check rejects co-application. The ninth and tenth are separate, small anchors
elsewhere in the module (see Pool-hop trigger and Pool-hop note injection
below). The eleventh is another full-frame app-shell anchor, wrapping the
stack ops 3/4/5 compose into one full-height wall per side:

1. `…-context-frame-helpers-before-vko` — scene components, clipped gutters,
   responsive right-gutter collapse, a center-column `fde` provider, and modal-only `t4` provider.
2. `…-center-columns-a` — shrinks the app shell's local column context by the
   left gutter, responsive right gutter, and any sidebar.
3. `…-main-window-me` — physically wraps the fullscreen main window/transcript row.
4. `…-bottom-stack-de` — physically wraps fullscreen prompt/footer
   bottom chrome.
5. `…-fullscreen-modal-center-fe` — constrains fullscreen modal/sub-agent overlays.
6. `…-qde-bottom-stack-ee` — constrains the terminal-scroll-region prompt/footer path without clipping footer overlays.
7. `…-qde-overlay-center-te` — constrains the terminal-scroll-region overlay path.
8. `…-fallback-window-v` — applies the same frame in the non-fullscreen fallback path.
9. `…-assistant-text-hook` — feeds assistant message text to the pool-hop trigger just before the transcript-item switch; this is the only operation with a runtime side effect beyond layout.
10. `…-note-sink-after-dwc` — registers the pool-break note-injection callback beside the existing session-name bridge in the REPL component (see Pool-hop note injection below).
11. `…-full-column-frame-ve` — wraps the composed transcript+prompt+modal stack in one full-height wall per side; ops 3/4 now only provide center-column context.

## Pool-hop trigger

Say a trigger phrase (case-insensitive substring match) in an assistant message
and the right capybara hops into the pool for a soak (the left wall is
unaffected -- the two walls are independent, per `paint_scene.py`): it plays a
jump-in transition immediately (starts on the next tick, no phase-alignment
wait -- a small steam discontinuity at takeoff is accepted for
responsiveness), then holds a soaking pose for ~7s (39 ticks at 180ms) and
climbs back out immediately once the hold expires (no phase-alignment wait on
exit either -- another small steam discontinuity accepted at that boundary),
then plays a jump-out transition back to its normal resting animation; the
landing itself stays phase-aligned/seamless (transOut always resets to phase
0). The
phrases are `TRIGGER_PHRASES` in `generate_package.py` — edit and regenerate to
change them. Retriggers during an active soak are queued and play out as
additional complete hop-in/soak/hop-out cycles rather than being dropped or
restarting the current one. Streaming-safe: growth of the same messages
text is deduped against the highest trigger count already seen for that
message id, so partial-token streaming re-renders never enqueue duplicate
hops. Op 09
(`…-assistant-text-hook`) is the text hook that feeds message text into this
state machine; it is wrapped in try/catch and never affects message rendering.

## Pool-hop note injection

When a hop actually starts (queue consumed, not merely queued), a short note
is appended to the conversation as a **hidden-context attachment row**
(`ki({type:"critical_system_reminder",content:…})`). It is invisible in the
stock UI (the `Ypr` gate filters hidden attachment types before the row
renderer), surfaced automatically by whichever hidden-context surfacing
package is installed — `hidden-context-inline` shows it inline in
chat, `hidden-context-drawer` routes it to the footer drawer, both through
their existing `critical_system_reminder` projection branch with no
capybara-specific code — and, this is the point, included in the model's own
context on its next turn wrapped in `<system-reminder>` tags, so it "knows"
it just got a pool break. One note per hop, including queued repeat hops.
Mechanism: op 10
(`…-note-sink-after-dwc`) registers a callback into a module-scope slot
(`__coCapyNoteSink`) from inside the REPL component, the same bridge pattern
the app already uses for its session-name file-watcher callback. The 180ms
animation tick (outside React render) calls that sink at hop start, wrapped
in try/catch, with a live-assembled note: a one-line ASCII scene postcard
(soaking capybara plus one pup per active subagent) and a `with:` line naming
the running subagents' Task descriptions, framed by a short fixed lead/close.
The row is built with the app's own
attachment factory (`ki`), so it persists to the session JSONL and survives
`/resume` — intended, not a leak (composition contract locked by
`tests/test_pool_hop_composition.py`).

## Subagent pup capybaras

Every running Task-tool subagent adds a small "pup" capybara soaking in the
right-wall pool (max 3 at once in a slot grid; further agents queue FIFO for
a free slot, no badge). Pups splash in when the subagent spawns, flick their
ears in sync with the resident capybara, and hop out when the task
completes, fails, or is killed -- an agent that finishes mid-arrival still
plays its full arrival before departing. Detection reads the app's own
AppState.tasks registry (records with type "local_agent" and status
"running") via the store handle captured from our own wall component --
zero additional patch operations; if the store is unavailable the feature
degrades to zero pups. Sprites are runtime-composited overlays stamped onto
the right-wall animation band (about 1KB of baked data total). When the
right gutter is collapsed (terminal <= 140 columns) the pups are hidden
with the rest of the right wall; state keeps tracking and they reappear on
widen. Version fragility: the store getter and record shape are pinned by
RUNTIME_IDENTITY_ANCHORS in generate_package.py, verified at generation
time.

## Build pipeline

This package is generated, not hand-edited. Its source pipeline lives in
`examples/capybara-onsen-generator/`: `paint_scene.py` (hand-authored masks +
preview PNGs), `water_sim.py` (deterministic phase animation, no `random`),
`compile.py` (RLE + palette → `onsen-data.json`, with determinism and
static-band asserts), `generate_package.py` (emits this package from whichever
target binary you point it at). See that directory's README for the full
regeneration walkthrough.

```bash
cd examples/capybara-onsen-generator
python3 compile.py
python3 generate_package.py \
  --source ~/.local/share/claude/versions/2.1.201 \
  --source-version 2.1.201 \
  --source-version-output "2.1.201 (Claude Code)"
```

Then build the patched binary from the repo root:

```bash
uv run harnessmonkey enable-patch capybara-onsen
uv run harnessmonkey build --activate
```

## Manual smoke

`manualSmoke.required = true`. Purely visual TUI art — automated sign/smoke gates
pass, but activation is gated on interactive confirmation in a truecolor
terminal (Ghostty/iTerm2/WezTerm/kitty/alacritty). Report `status` will be
`manual_smoke_pending` with `automatedStatus: passed`.
