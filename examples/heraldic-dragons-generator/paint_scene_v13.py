"""v13 integrated scene: full-height serpentine dragon + big mouth-anchored flame.
No stone, no rampart, no embers (per user feedback). Pure dragon + fire on black.

Left gutter; right mirrored at runtime. Fire is born at the dragon's maw and rises
in a big billowing plume filling the space above the head; the two mirrored plumes
crown together at center-top. 8 animated phases; only fire animates (v8 rule).
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import dragon_v13 as drg

OUT = Path(__file__).parent
W, H = 32, 100
PHASES = 8
MOUTH = drg.MOUTH                      # (15, 39)

COLOR = dict(drg.COLOR)
COLOR.update({
    'r': (175, 12, 0), 'o': (235, 45, 0), 'y': (255, 115, 13),
    'w': (255, 250, 186), 's': (42, 36, 34),
})


def jit(n, amp=1.0, freq=0.6):
    return amp * math.sin(n * freq) * math.cos(n * 0.23 + 1.7)


def dragon_layer():
    return drg.render()   # returns list[str], rebuilds fresh


def fire_layer(phase):
    """Plume issues from the FRONT of the maw and shoots UP-RIGHT (up-inner) along
    the snout direction, billowing then tapering as it climbs to center-top."""
    g = [['.'] * W for _ in range(H)]
    mx, my = MOUTH
    ph = phase / PHASES * 2 * math.pi

    def put(x, y, ch):
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < W and 0 <= yi < H:
            g[yi][xi] = ch

    # Centerline path: from the mouth-front up-right toward the inner-top corner.
    # x grows as it rises (up-right lean); a light phase sway animates the tongue.
    for y in range(0, my + 1):
        h = (my - y)                            # rows above the mouth
        t = h / my                              # 0 at mouth, 1 at top
        cx = mx + h * 0.62 + 2.6 * math.sin(ph + t * 3.2) * t
        # billow: narrow at the mouth, bulging mid-plume, softening at the top
        halfw = 1.3 + 8.0 * math.sin(min(1, t * 1.06) * math.pi * 0.66)
        halfw *= 0.9 + 0.1 * math.sin(ph * 2 + y * 0.3)
        left = cx - halfw + jit(y + phase * 3, 1.2)
        right = min(W, cx + halfw + jit(y + phase * 5, 1.0))
        if right <= left:
            continue
        span = right - left
        b_r = left + span * 0.26                # ember rim (outer)
        b_o = left + span * 0.55                # flame
        b_y = left + span * 0.82                # glow (inner)
        for x in range(int(left), int(right)):
            put(x, y, 'r' if x < b_r else ('o' if x < b_o else 'y'))
        # white-hot core thread hugging the inner side of the tongue
        if 0.12 < t < 0.95:
            wc = cx + halfw * 0.30
            put(wc, y, 'w'); put(wc + 1, y, 'w')

    # smoke curling off the very top of the plume
    for y in range(0, 5):
        if (y + phase) % 3 == 0:
            put(int(mx + my * 0.62) + int(jit(y + phase, 3)), y, 's')
    return g


def compose(phase):
    dragon = dragon_layer()
    fire = fire_layer(phase)
    out = [['.'] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            c = '.'
            if fire[y][x] != '.':
                c = fire[y][x]
            if dragon[y][x] != '.':        # dragon in front; maw is void -> fire shows through
                c = dragon[y][x]
            out[y][x] = c
    return [''.join(r) for r in out]


def tower_layer():
    """8-row band for the composer flank, CONTINUING the wall dragon's broad,
    outer-anchored lower body down to the floor and tapering to the tail tip.

    The wall dragon's visible bottom is broad and pinned to the outer edge (x0),
    so this starts equally broad at x0 and narrows — same outer anchor => no seam.
    Left wall; mirrored at runtime."""
    g = [['.'] * W for _ in range(8)]

    def put(x, y, ch):
        if 0 <= x < W and 0 <= y < 8:
            g[y][x] = ch
    for y in range(8):
        t = y / 7.0
        width = max(3, int(round(18 - 15 * t)))    # 18 at top -> 3 at the tail tip
        for x in range(0, width):
            put(x, y, 'G')
        put(width - 1, y, 'D')                      # inner rim (dark)
        if width > 5:
            put(width - 2, y, 'B')                  # belly plate on the inner side
        if y % 2 == 0:
            put(0, y, 'C')                          # dorsal frill spike on the outer edge
    put(2, 1, 'H'); put(3, 3, 'H')                  # scale highlights
    put(0, 7, 'C'); put(1, 7, 'C'); put(2, 7, 'C')  # tail barb at the floor
    return [''.join(r) for r in g]


def render_static_and_phases():
    dragon = dragon_layer()
    static = [''.join(r) for r in dragon]      # no-fire scene is just the dragon
    phases = [compose(p) for p in range(PHASES)]
    return static, phases


def write_png(path, scale=6):
    p0, p4 = compose(0), compose(4)
    grids = [p0, [''.join(reversed(r)) for r in p0], p4, [''.join(reversed(r)) for r in p4]]
    gap = 5
    width = (W * len(grids) + gap * (len(grids) - 1)) * scale
    px = bytearray()
    for y in range(H):
        line = []
        for gi, g in enumerate(grids):
            if gi:
                line += [(12, 12, 12)] * gap
            line += [COLOR.get(ch, (255, 0, 255)) for ch in g[y]]
        scan = bytearray()
        for rgb in line:
            scan.extend(bytes(rgb) * scale)
        for _ in range(scale):
            px.extend(scan)
    ppm = path.with_suffix('.ppm')
    ppm.write_bytes(f'P6\n{width} {H * scale}\n255\n'.encode() + bytes(px))
    subprocess.run(['sips', '-s', 'format', 'png', str(ppm), '--out', str(path)],
                   check=True, capture_output=True)


if __name__ == '__main__':
    write_png(OUT / 'v13-scene-preview.png')
    print('mouth', MOUTH)
    print('wrote', OUT / 'v13-scene-preview.png')
