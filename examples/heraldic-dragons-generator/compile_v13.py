"""v12 compiler: composite the v12 scene (stone + serpentine dragon + mouth-anchored
flame) and emit compact numeric run-data matching the v11 helper's schema, so the
existing build-heraldic-highdef-v11.py pipeline bakes the new art unchanged.

Writes v11-data.json (same schema): pal, w, fireCellRows, cellRows, phases,
staticBand (bottom rows, no fire), fireBands (8 phases, top rows, dragon+fire), tower.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import paint_scene_v13 as scene

OUT = Path(__file__).parent
W = scene.W
CELL_ROWS = scene.H // 2           # 50
FIRE_CELL_ROWS = 22                # top 22 cell rows animate (subrows 0..43)

PAL_MAP = dict(scene.COLOR)
LETTERS = ['.'] + sorted(k for k in PAL_MAP if k != '.')
PAL = [list(PAL_MAP[c]) for c in LETTERS]
IDX = {c: i for i, c in enumerate(LETTERS)}


def cellrow_runs(grid: list[str], cell_row: int) -> list[list[int]]:
    top = grid[cell_row * 2]
    bot = grid[cell_row * 2 + 1]
    runs: list[list[int]] = []
    for x in range(W):
        ti, bi = IDX[top[x]], IDX[bot[x]]
        if runs and runs[-1][0] == ti and runs[-1][1] == bi:
            runs[-1][2] += 1
        else:
            runs.append([ti, bi, 1])
    return runs


def band_runs(grid: list[str], r0: int, r1: int) -> list:
    return [cellrow_runs(grid, r) for r in range(r0, r1)]


def tower_runs() -> list:
    # v13: composer-flank continues the dragon's broad outer-anchored lower body
    # down to the floor (paint_scene_v13.tower_layer()). Same outer anchor as the
    # wall dragon => the tail lines up, no black-box corner.
    rows = []
    for line in scene.tower_layer():
        runs = []
        for x in range(W):
            i = IDX.get(line[x], 0)
            if runs and runs[-1][0] == i and runs[-1][1] == i:
                runs[-1][2] += 1
            else:
                runs.append([i, i, 1])
        rows.append(runs)
    return rows


def main() -> None:
    static_grid, phase_grids = scene.render_static_and_phases()
    assert len(static_grid) == scene.H
    static_band = band_runs(static_grid, FIRE_CELL_ROWS, CELL_ROWS)
    fire_bands = [band_runs(pg, 0, FIRE_CELL_ROWS) for pg in phase_grids]
    data = {
        'pal': PAL, 'w': W,
        'fireCellRows': FIRE_CELL_ROWS, 'cellRows': CELL_ROWS,
        'phases': scene.PHASES,
        'staticBand': static_band,
        'fireBands': fire_bands,
        'tower': tower_runs(),
    }
    payload = json.dumps(data, separators=(',', ':'))
    (OUT / 'v11-data.json').write_text(payload)      # overwrite: reused by v11 build
    print('palette', len(PAL), 'phases', data['phases'],
          'fireRows', FIRE_CELL_ROWS, 'staticRows', CELL_ROWS - FIRE_CELL_ROWS,
          'tower', len(data['tower']))
    print('json bytes', len(payload))
    print('wrote', OUT / 'v11-data.json')


if __name__ == '__main__':
    main()
