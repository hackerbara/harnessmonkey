"""capybara-onsen compiler: composite the hand-authored onsen scene (twilight Japanese
onsen, two capybaras, water/steam animation) and emit compact numeric run-data matching
the heraldic-dragons helper's schema, so the existing generate_package.py pipeline bakes
the new art unchanged.

Two independent walls (asymmetric scene: spout+soaking capybara left, stone
lantern+resting capybara right) -- NO runtime mirroring, both authored in screen
orientation. The animated band lives at the BOTTOM of each wall (v8-rule: the static
band, which sits on TOP and clips first on short terminals, must be byte-identical
across every phase).

Writes onsen-data.json: pal, w, animCellRows, cellRows, phases,
staticL/R (static band runs, top 28 cell rows), animL/R (16 phase bands, bottom 22
cell rows), poolL/R (8-row composer-flank bands).
"""
from __future__ import annotations

import json
from pathlib import Path

import paint_scene as scene

OUT = Path(__file__).parent
W = scene.W
H = scene.H
CELL_ROWS = H // 2                              # 50
ANIM_CELL_ROWS = 22                              # bottom 22 cell rows animate (subrows 56..99)
STATIC_CELL_ROWS = CELL_ROWS - ANIM_CELL_ROWS    # 28 (top, subrows 0..55)
STATIC_SUBROWS = STATIC_CELL_ROWS * 2            # 56 -- the v8-rule boundary

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


def pool_runs(rows: list[str]) -> list:
    # composer-flank band: 1 python row = 1 terminal row, solid color (top==bot idx,
    # same [idx,idx,width] shape heraldic-dragons' tower_runs used).
    out = []
    for line in rows:
        runs: list[list[int]] = []
        for x in range(W):
            i = IDX[line[x]]
            if runs and runs[-1][0] == i and runs[-1][1] == i:
                runs[-1][2] += 1
            else:
                runs.append([i, i, 1])
        out.append(runs)
    return out


def _check_chars(name: str, rows: list[str]) -> None:
    for r, line in enumerate(rows):
        for x, ch in enumerate(line):
            if ch not in PAL_MAP:
                raise AssertionError(f'{name}: unknown char {ch!r} at row {r} col {x} (not in scene.COLOR)')


def _check_v8_rule(wall: str, static_rows: list[str], phase: int, composed: list[str]) -> None:
    for r in range(STATIC_SUBROWS):
        if composed[r] != static_rows[r]:
            raise AssertionError(
                f'v8-rule violation: wall={wall!r} phase={phase} row={r} -- composed frame\'s '
                f'static-band row does not match static_{wall}() baseline (animation leaked '
                f'into the static band, or the static band itself is non-deterministic)'
            )


def main() -> None:
    # painter interface contract
    assert scene.W == 32, f'expected scene.W == 32, got {scene.W}'
    assert scene.H == 100, f'expected scene.H == 100, got {scene.H}'
    assert scene.PHASES == 16, f'expected scene.PHASES == 16, got {scene.PHASES}'
    assert scene.ANIM_CELL_ROWS == ANIM_CELL_ROWS, (
        f'expected scene.ANIM_CELL_ROWS == {ANIM_CELL_ROWS}, got {scene.ANIM_CELL_ROWS}'
    )

    static_l = scene.static_left()
    static_r = scene.static_right()
    assert len(static_l) == H, f'static_left(): expected {H} rows, got {len(static_l)}'
    assert len(static_r) == H, f'static_right(): expected {H} rows, got {len(static_r)}'

    # determinism
    assert scene.compose_left(0) == scene.compose_left(0), 'compose_left(0) is not deterministic'
    assert scene.compose_right(0) == scene.compose_right(0), 'compose_right(0) is not deterministic'

    frames_l = [scene.compose_left(p) for p in range(scene.PHASES)]
    frames_r = [scene.compose_right(p) for p in range(scene.PHASES)]

    for wall, static_rows, frames in (('left', static_l, frames_l), ('right', static_r, frames_r)):
        assert len(frames) == scene.PHASES
        for p, frame in enumerate(frames):
            assert len(frame) == H, f'compose_{wall}({p}): expected {H} rows, got {len(frame)}'
            _check_v8_rule(wall, static_rows, p, frame)
        distinct = len({tuple(f) for f in frames})
        assert distinct >= 2, (
            f'{wall}: expected at least 2 distinct animated frames across '
            f'{scene.PHASES} phases, got {distinct}'
        )

    # pool-hop frame sets: submerged idle loop + one-shot jump transitions
    assert scene.TRANS_FRAMES == 6, f'expected TRANS_FRAMES == 6, got {scene.TRANS_FRAMES}'
    frames_r_sub = [scene.compose_right_submerged(p) for p in range(scene.PHASES)]
    frames_r_in = [scene.compose_right_jump_in(f) for f in range(scene.TRANS_FRAMES)]
    frames_r_out = [scene.compose_right_jump_out(f) for f in range(scene.TRANS_FRAMES)]
    assert frames_r_sub[0] == scene.compose_right_submerged(0), (
        'compose_right_submerged not deterministic'
    )
    for label, frames in (
        ('submerged', frames_r_sub),
        ('jump_in', frames_r_in),
        ('jump_out', frames_r_out),
    ):
        for i, frame in enumerate(frames):
            assert len(frame) == H, f'{label}[{i}]: expected {H} rows, got {len(frame)}'
            _check_v8_rule(f'right/{label}', static_r, i, frame)
            _check_chars(f'{label}({i})', frame)
    assert len({tuple(f) for f in frames_r_sub}) >= 2, 'submerged loop has no motion'

    pool_l = scene.pool_left()
    pool_r = scene.pool_right()
    assert len(pool_l) == 8, f'pool_left(): expected 8 rows, got {len(pool_l)}'
    assert len(pool_r) == 8, f'pool_right(): expected 8 rows, got {len(pool_r)}'

    for name, rows in (
        ('static_left', static_l), ('static_right', static_r),
        ('pool_left', pool_l), ('pool_right', pool_r),
    ):
        _check_chars(name, rows)
    for p in range(scene.PHASES):
        _check_chars(f'compose_left({p})', frames_l[p])
        _check_chars(f'compose_right({p})', frames_r[p])

    static_l_runs = band_runs(static_l, 0, STATIC_CELL_ROWS)
    static_r_runs = band_runs(static_r, 0, STATIC_CELL_ROWS)
    anim_l_runs = [band_runs(frames_l[p], STATIC_CELL_ROWS, CELL_ROWS) for p in range(scene.PHASES)]
    anim_r_runs = [band_runs(frames_r[p], STATIC_CELL_ROWS, CELL_ROWS) for p in range(scene.PHASES)]

    data = {
        'pal': PAL, 'w': W,
        'animCellRows': ANIM_CELL_ROWS, 'cellRows': CELL_ROWS,
        'phases': scene.PHASES,
        'staticL': static_l_runs, 'staticR': static_r_runs,
        'animL': anim_l_runs, 'animR': anim_r_runs,
        'animRSub': [
            band_runs(frames_r_sub[p], STATIC_CELL_ROWS, CELL_ROWS) for p in range(scene.PHASES)
        ],
        'transInR': [
            band_runs(frames_r_in[f], STATIC_CELL_ROWS, CELL_ROWS)
            for f in range(scene.TRANS_FRAMES)
        ],
        'transOutR': [
            band_runs(frames_r_out[f], STATIC_CELL_ROWS, CELL_ROWS)
            for f in range(scene.TRANS_FRAMES)
        ],
        'poolL': pool_runs(pool_l), 'poolR': pool_runs(pool_r),
    }
    payload = json.dumps(data, separators=(',', ':'))
    (OUT / 'onsen-data.json').write_text(payload)
    print('palette', len(PAL), 'phases', data['phases'],
          'staticRows', STATIC_CELL_ROWS, 'animRows', ANIM_CELL_ROWS,
          'pool', len(data['poolL']), len(data['poolR']))
    print('json bytes', len(payload))
    print('wrote', OUT / 'onsen-data.json')


if __name__ == '__main__':
    main()
