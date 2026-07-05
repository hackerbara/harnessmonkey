"""Deterministic water/steam/ear animation for the capybara-onsen scene.

16 phases on a 180ms tick. The water elements (kakei stream, impact spray,
pool ripple, steam) cycle at phase%8 (a 1.44s loop); the resting capybara's
ears flick only in phases 6..8 of the full 16-loop, so the scene is perfectly
still for ~2.3s between flicks. Everything is a pure function of
(phase, geometry) — no random, no clock. Frames are baked at build time
(v8 rule: only the animated band may depend on phase).
"""
from __future__ import annotations

import math

PHASES = 16
CYCLE = 8   # water/steam sub-cycle


def stream_cells(phase, x, y_top, y_bot):
    """Full clear-blue kakei stream, 2px wide, white glints descending."""
    p = phase % CYCLE
    cells = []
    for y in range(y_top, y_bot):
        core = (y - p * 2) % CYCLE < 3          # pulses travel DOWN as phase advances
        cells.append((x, y, 'u' if core else 'U'))
        cells.append((x + 1, y, 'U' if core else 'u'))
        if y - y_top < 2:                        # widest right at the spout lip
            cells.append((x - 1, y, 'U'))
    return cells


def impact_cells(phase, cx, cy):
    """Livelier spray where the stream lands on the soaking capybara's head."""
    p = phase % CYCLE
    cells = [(cx, cy, 'u'), (cx + 1, cy, 'u'), (cx - 1, cy, 'U'), (cx + 2, cy, 'U')]
    if p % 2 == 0:
        cells += [(cx - 2, cy, 'F'), (cx + 3, cy - 1, 'U')]
    else:
        cells += [(cx + 3, cy, 'F'), (cx - 2, cy - 1, 'U')]
    if p % 4 < 2:
        cells.append((cx - 1, cy - 1, 'F'))
    else:
        cells.append((cx + 2, cy - 1, 'F'))
    return cells


def ripple_cells(phase, cx, cy):
    """Expanding ring on the pool surface around the soak; spans the FULL
    16-phase loop (half speed vs. the water/steam sub-cycle) so it drifts
    calmly instead of flickering against the submerged-body dither, then
    restarts. Caller must mask these onto water cells only."""
    r = 2 + phase // 2                           # 2..9 across all 16 phases
    young = phase < PHASES - 6
    ch = 'F' if young else 'V'                   # foam fades into warm water
    cells = [(cx - r, cy, ch), (cx + r, cy, ch)]
    if r > 3:                                    # slight elliptical perspective
        cells += [(cx - r + 1, cy + 1, ch), (cx + r - 1, cy + 1, ch)]
    return cells


def steam_cells(phase, seeds, y_bot, y_top):
    """Short sinuous wisps rising off the water. seeds = x anchors at the
    waterline. y_top is the HARD ceiling (static-band protection)."""
    p = phase % CYCLE
    cells = []
    for i, sx in enumerate(seeds):
        height = 8 + (i * 3) % 4
        rise = p / CYCLE                         # wisp slowly rises, then renews
        for k in range(height):
            y = y_bot - k - int(rise * 3)
            if y < y_top or y > y_bot:
                continue
            if (k + p + i * 2) % 5 == 0:         # a gap or two per wisp
                continue
            t = k / height
            drift = 1.4 * t * math.sin(k * 0.7 + p * math.pi / 4 + i * 2.1)
            x = int(round(sx + drift))
            cells.append((x, y, 'T' if k in (2, 3) else 't'))
    return cells


def ear_pose(phase):
    """0 = rest (13 of 16 phases). A double-flick: lift, splay, lift, rest."""
    return {6: 1, 7: 2, 8: 1}.get(phase, 0)


# --- determinism / liveliness asserts (reinstating what v13 dropped) ----------
assert stream_cells(3, 17, 66, 75) == stream_cells(3, 17, 66, 75)
assert stream_cells(0, 17, 66, 75) != stream_cells(1, 17, 66, 75)
assert steam_cells(2, [8, 25], 83, 58) == steam_cells(2, [8, 25], 83, 58)
assert steam_cells(0, [8, 25], 83, 58) != steam_cells(4, [8, 25], 83, 58)
assert all(y >= 58 for _, y, _ in steam_cells(5, [8, 25], 83, 58))
assert [ear_pose(p) for p in range(PHASES)].count(0) == 13
