# capybara-onsen generator (example)

This directory is the source pipeline for the shipped `packages/capybara-onsen/`
patch package. The scene scripts draw and compile the art; `generate_package.py`
wraps that compiled scene data into the current responsive Claude Code renderer
patch for whichever target binary you point it at.

`tests/test_generator_parity.py` runs the emitter with `HM_GENERATE_OUT` and the
currently pinned binary, then compares the emitted package to
`packages/capybara-onsen/` byte-for-byte (except any hand-captured
`preview.png`).

## What it does

Paints a twilight Japanese onsen scene (two capybaras, kakei water spout,
stone lantern, 16-phase water/steam animation) as half-block (`▀`) ANSI art and
ships it as a responsive Claude Code patch package.

## Script order

1. **`water_sim.py`** — pure, deterministic per-phase animation functions
   (stream, impact spray, ripple, steam, ear flick). No file I/O.
2. **`paint_scene.py`** — hand-authored static scene grids (sky, moon, rocks,
   bamboo, lantern, capybaras) for the left/right walls; composites in
   `water_sim` per phase. `python paint_scene.py` writes a PNG preview
   (`onsen-scene-preview.png`) via macOS `sips`.
3. **`compile.py`** — imports `paint_scene`, RLE-encodes every static/animated/
   pool band into `[topColorIdx, botColorIdx, width]` runs, and writes
   `onsen-data.json` next to itself.
4. **`generate_package.py`** — reads `onsen-data.json` (running `compile.py` on
   demand if the data file is missing), inspects the requested Claude Code
   binary for source/module identity, and emits `patch.json` + `payloads/*.js`.
5. **`capture_frame.py`** — optional verification tool: boots a locally built,
   codesigned patched binary in a PTY, captures its real ANSI output, and
   rasterizes it back to a PNG.

## How to run

From this directory:

```bash
python3 compile.py
HM_GENERATE_OUT=/tmp/capybara-onsen python3 generate_package.py \
  --source ~/.local/share/claude/versions/2.1.201 \
  --source-version 2.1.201 \
  --source-version-output "2.1.201 (Claude Code)"
python3 generate_package.py
```

Inputs can be CLI flags or environment variables:

- `--source` / `HM_GENERATE_SOURCE`: target Claude Code binary.
- `--source-version` / `HM_GENERATE_SOURCE_VERSION`: manifest
  `claudeVersion`.
- `--source-version-output` / `HM_GENERATE_SOURCE_VERSION_OUTPUT`: manifest
  `versionOutput`.
- `HM_GENERATE_OUT`: output package directory. Without it, the emitter writes
  to `packages/capybara-onsen/`.

If no source is provided, the emitter defaults to the newest file under
`~/.local/share/claude/versions/` and asks that binary for `--version`.

## Version-fragile anchors

All exact anchors and minified renderer glue live in the clearly marked
`VERSION_FRAGILE_ANCHORS` block in `generate_package.py`. On a routine Claude
version bump where anchors survive, run the emitter against the new binary. If a
minified name or exact range moved, edit that block and rerun the emitter; source
identity and module hashes are recomputed from the binary and must not be
hardcoded.

## Dependencies

Standard library only, plus this repo's own binary-inspection modules imported
from `src/`. PNG preview generation shells out to macOS `sips` (macOS-only).
