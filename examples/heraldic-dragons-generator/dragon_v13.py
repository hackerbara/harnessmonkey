"""v13 dragon: full-height serpentine dragon with a BIGGER, clearer head placed
lower (mid-screen) so a large flame region opens above it. Body coils to the
very bottom edge. No stone, no rampart.

Left gutter; right mirrored at runtime. Head faces INWARD (right = toward center).

Letters: '.' void  D outline  B belly  G scale  W wing  H highlight  E eye
         C claw/horn/tooth  N nostril  F frill(ember-red)
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

OUT = Path(__file__).parent
W, H = 32, 100

COLOR = {
    '.': (0, 0, 0),
    'D': (4, 13, 10), 'B': (22, 52, 34), 'G': (38, 96, 52), 'W': (12, 40, 33),
    'H': (78, 150, 86), 'E': (255, 210, 40), 'C': (206, 178, 124), 'N': (2, 6, 5),
    'F': (170, 46, 12),
}

grid = [['.'] * W for _ in range(H)]


def put(x, y, ch, over=True):
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < W and 0 <= yi < H:
        if over or grid[yi][xi] == '.':
            grid[yi][xi] = ch


def swept(points, width_fn, ch, over=True):
    n = len(points)
    for i in range(n - 1):
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        seg = max(1, int(math.hypot(x1 - x0, y1 - y0) * 2))
        for s in range(seg + 1):
            u = s / seg
            t = (i + u) / (n - 1)
            cx, cy = x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
            hw = width_fn(t)
            dx, dy = x1 - x0, y1 - y0
            L = math.hypot(dx, dy) or 1
            px, py = -dy / L, dx / L
            for w in range(-int(hw), int(hw) + 1):
                put(cx + px * w, cy + py * w, ch, over)


# --- BIG HEAD, profile facing RIGHT (inner), snout elongated, jaws AGAPE. -----
# 22 wide x 26 tall.  Maw opens to the right where fire issues.
# Big head, snout raised UP-RIGHT with a large wedge OPEN MAW (fire pours up-right).
HEAD = [
    "...............CCC......",  # 0  upper-jaw tip + fang
    "..............CCGG......",  # 1
    ".............CGGG.......",  # 2  snout (upper jaw) rising up-right
    "............CGGG........",  # 3
    ".....CC....CGGGG........",  # 4  horns (left) + snout
    "....CCG...CGGGG.........",  # 5
    "...CCGGGGGGGGGG.C.......",  # 6  skull crown + upper jaw; C tooth
    "..FCGGGEEGGGGG.CC.......",  # 7  EE eye; fangs hang from upper jaw
    "..FGGGGEEGGGGG..........",  # 8
    "..FGGGGGGGGGG...........",  # 9  <==== OPEN MAW (void) opens up-right ====
    "...NGGGGGGG.............",  # 10 N nostril; throat
    "...GGGGGG......CC.......",  # 11 lower fangs rising
    "...GGGGG....CCGG........",  # 12 lower jaw rising up-right
    "..BBBBBBB.CCGGG.........",  # 13 lower jaw
    "..BBBBBBBBBGGG..........",  # 14
    "...BBBBBBBBB............",  # 15 lower jaw underside
    "....BBBBBB..............",  # 16 jaw hinge
    ".....BBB................",  # 17 chin
    ".....GGG................",  # 18 -> neck
    "......GG................",  # 19
]
HEAD_ORIGIN = (3, 30)                 # head occupies x3.., y30..49
MOUTH = (HEAD_ORIGIN[0] + 16, HEAD_ORIGIN[1] + 8)    # ~(19, 38) FRONT of the open maw


def stamp_head():
    ox, oy = HEAD_ORIGIN
    for r, line in enumerate(HEAD):
        for c, ch in enumerate(line):
            if ch != '.':
                put(ox + c, oy + r, ch)


def build_dragon():
    # --- SPINE: neck-base under head, coiling S all the way to the bottom edge ---
    SPINE = [
        (12, 52),   # under the chin
        (13, 61),
        (18, 69),   # coil inner
        (20, 77),
        (15, 83),   # coil back toward outer
        (9, 88),
        (6, 93),    # sweep into the OUTER-BOTTOM corner (screen corner)
        (3, 99),    # tail fills the corner, reaching the bottom edge
    ]
    def spine_w(t):
        # stay THICK through the lower body so the corner reads full, then a short barb
        return 6.0 * math.sin(min(1, t * 1.2) * math.pi * 0.52) * (1 - 0.32 * t) + 1.4
    swept(SPINE, spine_w, 'G')
    put(2, 99, 'C'); put(1, 98, 'C'); put(4, 99, 'C')       # tail barb in the corner

    # belly plates along the inner edge of the coil
    for i in range(len(SPINE) - 1):
        (x0, y0), (x1, y1) = SPINE[i], SPINE[i + 1]
        t = i / (len(SPINE) - 1)
        for s in range(6):
            u = s / 5
            cx, cy = x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
            hw = spine_w(t)
            put(cx + hw * 0.55, cy, 'B')
            put(cx + hw * 0.82, cy, 'B')

    # --- FOLDED WING hump on the outer shoulder ---
    for y in range(58, 78):
        t = (y - 58) / 20
        xL = 4 + 2.5 * math.sin(t * math.pi)
        xR = 11 + 2.5 * math.sin(t * math.pi)
        for x in range(int(xL), int(xR)):
            put(x, y, 'W', over=False)
    for ry in (61, 66, 71):
        swept([(10, ry), (5, ry + 3)], lambda t: 0.5, 'D')

    # --- RAISED FORELEG clawing toward center ---
    swept([(18, 64), (23, 67), (26, 72), (27, 76)], lambda t: 1.9 * (1 - t) + 0.7, 'G')
    for cx in (27, 29):
        put(cx, 77, 'C'); put(cx, 78, 'C')
    put(28, 75, 'C')
    # --- BROAD HAUNCH/COIL filling the outer-bottom corner. The conversation view
    #     clips the dragon somewhere in the lower body, so keep this whole region
    #     broad (hugging the outer edge x0) so the corner reads full wherever it cuts.
    for y in range(76, 100):
        t = (y - 76) / 24
        # outer edge pinned near x0; inner edge bulges then tapers
        inner = 15 - int(8 * t) + int(2 * math.sin(y * 0.5))
        for x in range(0, max(3, inner)):
            put(x, y, 'G', over=False)
    # belly shading on the inner side of the haunch
    for y in range(78, 98):
        t = (y - 78) / 20
        bx = 12 - int(7 * t)
        put(bx, y, 'B'); put(bx - 1, y, 'B')
    # hindleg claw gripping at the base
    for cx in (2, 4, 6):
        put(cx, 98, 'C'); put(cx, 99, 'C')

    # --- DORSAL FRILL: spikes along the OUTER edge of the coil ---
    for i in range(len(SPINE) - 1):
        (x0, y0), (x1, y1) = SPINE[i], SPINE[i + 1]
        t = i / (len(SPINE) - 1)
        for s in range(3):
            u = s / 3
            cx, cy = x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
            hw = spine_w(t)
            put(cx - hw - 1, cy, 'C')
            put(cx - hw, cy, 'D')

    # --- HEAD ---
    stamp_head()
    # (whiskers removed — they read as stray lines, not whiskers)

    # --- OUTLINE pass: scale/wing/belly touching void -> dark rim.
    #     SKIP the head bounding box so the open maw is never sealed. ---
    hx0, hy0 = HEAD_ORIGIN
    hy1 = hy0 + len(HEAD) + 1
    base = [row[:] for row in grid]
    for y in range(H):
        for x in range(W):
            if hy0 - 1 <= y <= hy1 and x <= hx0 + 24:
                continue
            if base[y][x] in ('G', 'W', 'B'):
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and base[ny][nx] == '.':
                        grid[ny][nx] = 'D'
    # --- scale highlights on the back/haunch ---
    for (hx, hy) in [(10, 64), (12, 70), (18, 72), (9, 88), (16, 60)]:
        if grid[hy][hx] == 'G':
            grid[hy][hx] = 'H'


def render():
    global grid
    grid = [['.'] * W for _ in range(H)]
    build_dragon()
    return [''.join(r) for r in grid]


def write_png(rows, path, scale=7):
    mirror = [''.join(reversed(r)) for r in rows]
    gap = 6
    width = (W * 2 + gap) * scale
    px = bytearray()
    for y in range(H):
        line = rows[y] + '.' * gap + mirror[y]
        scan = bytearray()
        for ch in line:
            scan.extend(bytes(COLOR.get(ch, (255, 0, 255))) * scale)
        for _ in range(scale):
            px.extend(scan)
    ppm = path.with_suffix('.ppm')
    ppm.write_bytes(f'P6\n{width} {H * scale}\n255\n'.encode() + bytes(px))
    subprocess.run(['sips', '-s', 'format', 'png', str(ppm), '--out', str(path)],
                   check=True, capture_output=True)


if __name__ == '__main__':
    write_png(render(), OUT / 'v13-dragon-only.png')
    print('mouth', MOUTH)
    print('wrote', OUT / 'v13-dragon-only.png')
