# heraldic-dragons generator (example)

This directory is the source pipeline for the shipped `packages/heraldic-dragons/`
patch package. The scene scripts draw and compile the art; `generate_package.py`
wraps that compiled scene data into the current responsive Claude Code renderer
patch for whichever target binary you point it at.

`tests/test_generator_parity.py` runs the emitter with `HM_GENERATE_OUT` and the
currently pinned binary, then compares the emitted package to
`packages/heraldic-dragons/` byte-for-byte (except any hand-captured
`preview.png`). This is not a hedge: the generator regenerates the live
package exactly, byte-for-byte, given the same pinned target binary.

This is the curated final version of a multi-iteration development process
(v11 → v12 → v13). Only the v13 scripts are part of the live source pipeline.
Earlier iterations were left out as design-process debris.

## What it does

Paints two heraldic fire-breathing dragons (full-height serpentine body,
mouth-anchored flame plume, 8-phase baked fire animation) as half-block (`▀`)
ANSI art and ships it as a responsive Claude Code patch package.

## Script order

1. **`dragon_v13.py`** — hand-authored full-height serpentine dragon body +
   head grid (left wall; mirrored at runtime for the right wall). No animation;
   the dragon itself is static.
2. **`paint_scene_v13.py`** — imports `dragon_v13`, adds the animated
   mouth-anchored flame plume (8 phases), composites dragon + fire per phase,
   and provides `tower_layer()` for the composer-flank continuation.
3. **`compile_v13.py`** — imports `paint_scene_v13`, RLE-encodes the static
   dragon band, the 8 fire-phase bands, and the tower band into
   `[topColorIdx, botColorIdx, width]` runs, and writes `v11-data.json` next to
   itself (filename retained from the v11 data schema reused by v13).
4. **`generate_package.py`** — reads `v11-data.json` (running `compile_v13.py`
   on demand if the data file is missing), inspects the requested Claude Code
   binary for source/module identity, and emits `patch.json` + `payloads/*.js`.
5. **`capture_frame.py`** — optional verification tool: boots a locally built,
   codesigned patched binary in a PTY, captures its real ANSI output, and
   rasterizes it back to a PNG. Its dimensions were tuned for the original v11
   build, so treat it as illustrative unless refreshed.

## How to run

From this directory:

```bash
python3 compile_v13.py
HM_GENERATE_OUT=/tmp/heraldic-dragons python3 generate_package.py \
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
  to `packages/heraldic-dragons/`.

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
