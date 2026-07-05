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
- Continues the pool water into the composer flanks so the bath reaches the very
  bottom corners; the bottom chrome parent is tinted deep indigo `rgb(10,12,26)`. The right gutter collapses at terminal widths `<= 140` columns and returns at `>= 141`.

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

All eight are `replace_exact` inserts/replacements (non-overlapping), at the same
full-frame app-shell anchors as `heraldic-dragons` — the two packages are **mutually
exclusive**; the builder's byte-range overlap check rejects co-application:

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
