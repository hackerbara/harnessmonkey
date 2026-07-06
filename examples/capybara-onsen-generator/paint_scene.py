"""Capybara-onsen scene painter: twilight Japanese hot spring, two capybaras.

Two INDEPENDENT walls (no runtime mirroring — the scene is asymmetric):
  LEFT  wall (screen-left,  x0 = outer edge): moon, bamboo leaning inward,
        stepped rocks with a bamboo kakei spout pouring a thin clear stream
        onto a soaking capybara's head; a yuzu floats nearby.
  RIGHT wall (screen-right, x0 = INNER edge): stars, bamboo, a glowing stone
        lantern (toro) on the outer rocks, and a second capybara resting on a
        shelf at the pool edge, ears flicking occasionally.

Grid: 32 cells wide x 100 subpixel rows (half-block: fg=top / bg=bottom).
Static band = subrows 0..55 (sky/moon/bamboo/lantern top). Animated band =
subrows 56..99 (stream, spray, ripple, steam, ears). 16 phases, 180ms tick.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import water_sim as ws

OUT = Path(__file__).parent
W, H = 32, 100
PHASES = 16
ANIM_CELL_ROWS = 22
ANIM_TOP = 56                 # first animated subrow (v8-rule boundary)
WATERLINE = 84                # pool surface subrow, shared by both walls

COLOR = {
    '.': (6, 8, 22),          # void == deep night (never visible; sky covers all)
    # sky
    'k': (8, 10, 28), 'K': (14, 18, 44), 'z': (26, 32, 62),
    'M': (226, 232, 240), 'm': (64, 72, 112),
    # flora / rock
    'b': (10, 26, 20), 'L': (18, 44, 30),
    'R': (44, 48, 60), 'r': (28, 30, 40), 'g': (38, 74, 50),
    # kakei spout
    'S': (112, 98, 54), 'd': (58, 50, 28),
    # water
    'W': (24, 72, 80), 'V': (38, 98, 96), 'v': (14, 44, 52), 'F': (150, 220, 220),
    # capybaras
    'C': (142, 96, 58), 'c': (94, 62, 38), 'A': (216, 152, 76), 'E': (26, 16, 10),
    'N': (52, 32, 20),        # snoot nostril/cleft
    # stream
    'U': (168, 218, 252), 'u': (236, 248, 255),
    # steam
    'T': (92, 102, 132), 't': (52, 60, 88),
    # yuzu
    'O': (240, 162, 42), 'o': (188, 110, 22),
    # lantern
    'P': (76, 80, 94), 'p': (42, 44, 56), 'Y': (255, 198, 92), 'h': (96, 74, 48),
}

WATER_CH = ('W', 'V', 'v', 'F')

# geometry shared with the animation
SPOUT_MOUTH_X = 17            # stream column
SPOUT_LIP_Y = 58              # stream starts just under the spout lip (>= ANIM_TOP)
CAPY_L_HEAD_TOP = 71          # stream lands here
STEAM_SEEDS_L = (4, 30)
STEAM_SEEDS_R = (22, 23)
STEAM_CEIL = 58               # hard ceiling, safely below ANIM_TOP


def fresh():
    return [['.'] * W for _ in range(H)]


def put(g, x, y, ch):
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < W and 0 <= yi < H:
        g[yi][xi] = ch


def stamp(g, ox, oy, rows):
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch != '.':
                put(g, ox + c, oy + r, ch)


# --- sky ----------------------------------------------------------------------

def sky(g, wall):
    for y in range(H):
        for x in range(W):
            noise = (x * 3 + y * 5) % 7        # ordered pseudo-noise, no stripes
            if y < 12:
                ch = 'k'
            elif y < 26:                       # k -> K ramp
                ch = 'K' if noise < (y - 12) * 7 // 14 else 'k'
            elif y < 64:
                ch = 'K'
            elif y < 80:                       # K -> z ramp toward the water glow
                ch = 'z' if noise < (y - 64) * 7 // 16 else 'K'
            else:
                ch = 'z'
            g[y][x] = ch
    stars = [(14, 20), (24, 6), (29, 16), (4, 30), (19, 12)] if wall == 'L' else \
            [(6, 8), (14, 26), (10, 16), (29, 6), (17, 4)]
    for sx, sy in stars:
        put(g, sx, sy, 'm')


def moon(g):
    cx, cy, r = 7, 9, 4.4
    for y in range(3, 16):
        for x in range(1, 14):
            d2 = (x - cx) ** 2 + ((y - cy) * 1.0) ** 2
            if d2 <= r * r:
                g[y][x] = 'M'
            elif d2 <= (r + 2.2) ** 2 and (x + y) % 2:
                g[y][x] = 'm'


# --- flora / rock -------------------------------------------------------------

def bamboo(g, wall):
    # 3px culms with node gaps, leaning toward the conversation; leaf crowns
    if wall == 'L':
        stalks = [(21, 0.05, 8), (26, 0.07, 18)]        # inward = +x
        base = 60
    else:
        stalks = [(3, -0.05, 10), (7, -0.09, 22),       # inner edge; inward = -x
                  (20, -0.02, 6), (25, 0.03, 8)]        # tall culms filling the
        base = 80                                       # top-right negative space
    for x0, lean, top in stalks:
        for y in range(base, top, -1):
            if (base - y) % 12 == 11:                   # culm node gap
                continue
            x = x0 + (base - y) * lean
            put(g, x, y, 'b'); put(g, x + 1, y, 'b')
            put(g, x + 2, y, 'L' if y % 2 else 'b')     # lit edge texture
        tx = x0 + (base - top) * lean
        for dy, s, ln in ((0, 1, 6), (3, -1, 5), (7, 1, 4)):
            for k in range(1, ln):                      # drooping leaf strokes
                put(g, tx + s * k, top + dy + k // 2, 'L')
                put(g, tx + s * k, top + dy + 1 + k // 2, 'L')


def rocks_left(g):
    slabs = [                    # (x0, x1, y0, y1) stepped down toward the pool
        (0, 8, 48, 62),
        (0, 11, 60, 76),
        (0, 13, 74, WATERLINE + 2),
    ]
    for x0, x1, y0, y1 in slabs:
        for y in range(y0, y1):
            for x in range(x0, x1 - (1 if (y - y0) < 2 else 0)):
                g[y][x] = 'R'
        for x in range(x0, x1):                          # mossy top edge
            if g[y0][x] == 'R':
                g[y0][x] = 'g'
                if (x % 3) != 2:
                    put(g, x, y0 + 1, 'g')
        for y in range(y0, y1):                          # shadowed inner face
            put(g, x1 - 1, y, 'r')
            if y % 2:
                put(g, x1 - 2, y, 'r')


def spout(g):
    # bigger bamboo kakei, higher up: a taller drop for the stream
    for x in range(5, SPOUT_MOUTH_X + 1):
        dy = 1 if x > 12 else 0                          # gentle downward slope
        put(g, x, 53 + dy, 'd')
        put(g, x, 54 + dy, 'S')
        put(g, x, 55 + dy, 'S')
        put(g, x, 56 + dy, 'd')
    for dy in range(54, 58):                             # open dark mouth
        put(g, SPOUT_MOUTH_X, dy, 'd')
    put(g, SPOUT_MOUTH_X - 1, 55, 'd')
    for y in range(57, 76):                              # support post into rock
        put(g, 11, y, 'd')
        put(g, 12, y, 'd')
    put(g, 11, 56, 'S'); put(g, 12, 57, 'S')             # rope lash at the joint
    put(g, 10, 58, 'S'); put(g, 13, 58, 'S')


def rocks_right(g):
    # slimmer, shorter rock column carrying a smaller lantern
    for y in range(54, WATERLINE + 2):
        for x in range(24, W):
            g[y][x] = 'R'
    for x in range(24, W):
        g[54][x] = 'g'
        if x % 3 != 1:
            put(g, x, 55, 'g')
    for y in range(54, WATERLINE + 2):
        put(g, 24, y, 'r')
        if y % 2:
            put(g, 25, y, 'r')
    # low shelf at the pool edge where the capybara rests
    for y in range(80, 87):
        for x in range(1, 22):
            g[y][x] = 'R' if y < 83 else 'r'
    for x in range(1, 22):
        g[80][x] = 'g'
        if x % 3 == 0:
            put(g, x, 81, 'g')                    # ragged moss bleeding down the face
    for sx in (4, 9, 14, 19):                     # stone-block seams break up the slab
        put(g, sx, 81, 'r'); put(g, sx, 82, 'r')
        put(g, sx + 1, 82, 'r')
    for x in range(1, 22):                        # weathered flecks + a lit lower lip
        if (x * 3 + 1) % 7 == 0:
            put(g, x, 82, 'g')
        if x % 4 == 1:
            put(g, x, 83, 'R')


def lantern(g):
    # smaller stone toro on the rock column (top y40 .. base y53)
    put(g, 27, 40, 'p')                                   # finial
    put(g, 27, 41, 'P')
    for y in range(42, 45):                               # curved cap
        half = 3 - (44 - y)
        for x in range(27 - half, 28 + half):
            put(g, x, y, 'P')
    for x in range(24, 31):
        put(g, x, 44, 'p')
    for y in range(45, 50):                               # light box
        for x in range(25, 30):
            put(g, x, y, 'P')
    for y in range(46, 49):                               # glowing window
        for x in range(26, 29):
            put(g, x, y, 'Y')
    for y in range(50, 52):                               # post
        put(g, 26, y, 'p'); put(g, 27, y, 'p'); put(g, 28, y, 'p')
    for x in range(25, 30):                               # base
        put(g, x, 52, 'P'); put(g, x, 53, 'P')
    # warm two-tier halo dithered onto the sky around the light box
    for y in range(40, 54):
        for x in range(19, W):
            if g[y][x] in ('k', 'K', 'z'):
                d2 = (x - 27) ** 2 + ((y - 47) * 1.6) ** 2
                if d2 < 34 and (x + y) % 2 == 0:
                    g[y][x] = 'h'
                elif d2 < 80 and (x * 3 + y) % 5 == 0:
                    g[y][x] = 'h'


# --- water --------------------------------------------------------------------

def pool(g, wall):
    for y in range(WATERLINE, H):
        deep = (y - WATERLINE) / (H - WATERLINE)
        for x in range(W):
            if wall == 'L':
                warm = x / W                              # warmer toward center
            else:
                warm = max(0.0, 1.0 - abs(x - 24) / 16)   # warmer under the lantern
            if deep > 0.72:
                ch = 'v'
            elif warm > 0.62 and (x + y) % 2:
                ch = 'V'
            elif deep > 0.45 and (x + y) % 2:
                ch = 'v'
            else:
                ch = 'W'
            g[y][x] = ch
    # still-water sparkles on the surface row
    marks = (5, 13, 27) if wall == 'L' else (7, 15, 30)
    for x in marks:
        put(g, x, WATERLINE, 'F')
    if wall == 'R':
        for y in range(85, 87):                           # dappled shelf-shadow reflection
            for x in range(3, 19):                        # (dithered, not a flat slab)
                if (x + y) % 2 == 0:
                    g[y][x] = 'v'


# --- capybaras ----------------------------------------------------------------

CAPY_L = [       # BIG soak, facing viewer, head tilted up into the stream;
                 # the stream lands on the head top at x17
    "...cc.....cc........",   # y69 ear tips
    "..cCCc...cCCc.......",   # y70 ears (lit centers)
    "..cCCCCCCCCCCc......",   # y71 head top, rounded
    ".cCCCCCCCCCCCCc.....",   # y72
    ".cCCCCCCCCCCCCCc....",   # y73
    "cCCEECCCCCEECCCA....",   # y74 closed eyes (blissful 2px lines)
    "cCCCCCCCCCCCCCCA....",   # y75 cheek fur (buffer above the pad)
    "cCCcAAAAAAAcCCCAc...",   # y76 SNOOT: pad top, rounding in
    "cCcAANANANAAcCCCAc..",   # y77 SNOOT: small nostril slits + philtrum start
    "cCAAAAANAAAAACCCAc..",   # y78 SNOOT: widest row -- riser down into the mouth
    ".ccAAANNNAAAccCCCCA.",   # y79 SNOOT: mouth line, riser meets it dead-center
    ".cCcAAAAAAAcCCCCCCCA",   # y80 SNOOT: chin/jowl taper back into fur
    ".cCCCCCCCCCCCCCCCCCA",   # y81
    "..cCCCCCCCCCCCCCCCA.",   # y82 chin + back at the waterline
    "..ccCCCCCCcccCCCCc..",   # y83 waterline shadow
]
CAPY_L_ORIGIN = (9, 69)

CAPY_R_BODY = [   # BIG resting loaf in profile, facing inner (left);
                  # sphinx pose with little front paws; ears animate separately
    "..ccccc.............",   # y68 head top
    ".cCCCCCc............",   # y69
    ".cCCCCCCccccccccc...",   # y70 back line rises into the rump (no rim blob)
    "cCCECCCCCCCCCCCCCC..",   # y71 half-lidded eye
    "cCCCCCCCCCCCCCCCCC..",   # y72
    "NAACCCCCCCCCCCCCCCC.",   # y73 SNOOT: single nostril, high on the light pad
    "AAACCCCCCCCCCCCCCCC.",   # y74 SNOOT: plain pad front, no downstroke
    "AccACCCCCCCCCCCCCCCA",   # y75 SNOOT: mouth -- soft shadow-brown line, not ink-black
    ".cCCCCCCCCCCCCCCCCCA",   # y76
    ".cCCCCCCCCCCCCCCCCc.",   # y77
    "..cCCcccCCCCCCCCcc..",   # y78 chest fold / haunch
    "..cCCc..cCCc..cCc...",   # y79 little front paws + tucked hind foot
]
CAPY_R_ORIGIN = (1, 68)

EAR_POSES = {     # (x, y) cells; y65..67 — inside the animated band
    0: [(4, 66), (4, 67), (8, 66), (8, 67)],
    1: [(4, 65), (4, 66), (8, 65), (8, 66)],
    2: [(3, 65), (4, 66), (9, 65), (8, 66)],
}


def capy_left(g):
    stamp(g, *CAPY_L_ORIGIN, CAPY_L)
    # submerged body hinted below the surface
    for y in range(WATERLINE + 1, 92):
        for x in range(13, 29):
            if (x + y) % 2:
                put(g, x, y, 'v')


def capy_right(g, pose):
    stamp(g, *CAPY_R_ORIGIN, CAPY_R_BODY)
    for x, y in EAR_POSES[pose]:
        put(g, x, y, 'c')


YUZU = [              # a proper round yuzu with a small moss-green leaf on top
    "...g.",
    "..gg.",
    ".OOO.",
    "OOOOo",
    "OOOoo",
    ".ooo.",
]


def yuzu(g):
    # fully clear of the waterline -- the whole round fruit shows, sunk deep
    # enough into the pool that the leaf reads against open water
    stamp(g, 4, 86, YUZU)
    put(g, 6, 93, 'o')                                    # tiny reflection


def yuzu_right(g):
    # one proper yuzu floating in open water below the shelf
    stamp(g, 15, 89, YUZU)
    put(g, 17, 96, 'o')                                   # tiny reflection


# --- walls --------------------------------------------------------------------

def _static_left_grid():
    g = fresh()
    sky(g, 'L')
    moon(g)
    bamboo(g, 'L')
    rocks_left(g)
    spout(g)
    pool(g, 'L')
    capy_left(g)
    yuzu(g)
    return g


def _static_right_grid():
    g = fresh()
    sky(g, 'R')
    bamboo(g, 'R')
    rocks_right(g)
    lantern(g)
    pool(g, 'R')
    capy_right(g, 0)
    yuzu_right(g)
    return g


def _overlay(g, cells):
    for x, y, ch in cells:
        put(g, x, y, ch)


def _overlay_on_water(g, cells):
    for x, y, ch in cells:
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < W and 0 <= yi < H and g[yi][xi] in WATER_CH:
            g[yi][xi] = ch


def static_left():
    return [''.join(r) for r in _static_left_grid()]


def static_right():
    return [''.join(r) for r in _static_right_grid()]


def compose_left(phase):
    g = _static_left_grid()
    _overlay(g, ws.stream_cells(phase, SPOUT_MOUTH_X, SPOUT_LIP_Y, CAPY_L_HEAD_TOP))
    _overlay(g, ws.impact_cells(phase, SPOUT_MOUTH_X, CAPY_L_HEAD_TOP))
    _overlay_on_water(g, ws.ripple_cells(phase, 17, WATERLINE + 3))
    _overlay(g, ws.steam_cells(phase, STEAM_SEEDS_L, WATERLINE - 1, STEAM_CEIL))
    return [''.join(r) for r in g]


def compose_right(phase):
    g = fresh()
    sky(g, 'R')
    bamboo(g, 'R')
    rocks_right(g)
    lantern(g)
    pool(g, 'R')
    capy_right(g, ws.ear_pose(phase))
    yuzu_right(g)
    _overlay(g, ws.steam_cells(phase, STEAM_SEEDS_R, WATERLINE - 1, STEAM_CEIL))
    return [''.join(r) for r in g]


# --- pool-hop: submerged pose + jump transitions (all inside the anim band) ---

TRANS_FRAMES = 6

# The eyes row (y83) must stay gap-free ('.'-free): the splash draw-order fix
# in _compose_right_jump relies on the head mask fully overwriting any splash
# cells at the eye columns, so a '.' there would let splash bleed through.
CAPY_R_SOAK = [        # crown + eyes just proud of the water (WATERLINE=84)
    ".cCCCCCCCc.",     # y82 crown
    "cCEACCCAECc",     # y83 eyes at the surface
]
CAPY_R_SOAK_ORIGIN = (4, 82)

EAR_POSES_SOAK = {     # absolute (x, y) cells; same flick rhythm as EAR_POSES
    0: [(7, 80), (7, 81), (11, 80), (11, 81)],
    1: [(7, 79), (7, 80), (11, 79), (11, 80)],
    2: [(6, 79), (7, 80), (12, 79), (11, 80)],
}

JUMP_FRAMES_IN = [     # (body_origin | None for soak pose, splash_step)
    ((1, 70), 0),      # crouch on the shelf
    ((2, 64), 0),      # spring
    ((3, 68), 1),      # arc out over the water
    ((4, 76), 3),      # impact -- body clipped at the waterline
    (None, 4),         # under: soak pose + big burst
    (None, 2),         # settle: soak pose + fading burst
]
# Runtime phase choreography baked by JUMP_FRAMES_OUT (see _compose_right_jump
# and __coSoakTick in generate_package.py). Both the hop-in and the climb-out
# are un-gated by design (user-requested responsiveness tradeoffs -- the jump
# motion masks the steam discontinuity at each boundary):
#   dry loop (whatever phase it happened to be at) -> transIn bakes its own
#   fixed steam phases 0..5, independent of the interrupted dry phase (small
#   accepted discontinuity here) -> soak enters at animRSub[6], continuing
#   7, 8, 9, ... for as many ticks as __coSoakHoldTicks holds (soak-exit
#   phase is not gated either) -> transOut bakes its own fixed steam phases
#   10..15, independent of the interrupted soak phase (another small accepted
#   discontinuity here; final frame forced to compose_right(15)) -> dry
#   resumes at animR[0].
# The two internal handoffs that stay seamless by construction: transIn's
# last frame (phase 5) into soak's first frame (phase 6), and transOut's
# forced final frame (phase 15) into the resumed dry loop (phase 0) -- the
# landing. Only the two transition *entry* boundaries (dry->transIn,
# soak->transOut) carry an accepted steam jump.
JUMP_FRAMES_OUT = [
    (None, 1),         # gather
    ((4, 76), 3),      # burst upward
    ((3, 68), 2),      # arc back to the shelf
    ((2, 64), 0),      # apex
    ((1, 70), 0),      # land crouch
    ((1, 68), 0),      # settle into the rest pose
]


def stamp_clip(g, ox, oy, rows, y_max):
    """stamp(), but skip every subrow at or below y_max (waterline clipping)."""
    for r, line in enumerate(rows):
        if oy + r >= y_max:
            break
        for c, ch in enumerate(line):
            if ch != '.':
                put(g, ox + c, oy + r, ch)


def capy_right_soak(g, pose):
    stamp(g, *CAPY_R_SOAK_ORIGIN, CAPY_R_SOAK)
    for x, y in EAR_POSES_SOAK[pose]:
        put(g, x, y, 'c')


def _capy_right_at(g, ox, oy):
    """The dry body mask stamped at an arbitrary origin, clipped at the
    waterline, with rest-pose ears shifted by the same offset."""
    stamp_clip(g, ox, oy, CAPY_R_BODY, WATERLINE)
    dx, dy = ox - CAPY_R_ORIGIN[0], oy - CAPY_R_ORIGIN[1]
    for x, y in EAR_POSES[0]:
        if y + dy < WATERLINE:
            put(g, x + dx, y + dy, 'c')


def _base_right_grid_no_capy():
    g = fresh()
    sky(g, 'R')
    bamboo(g, 'R')
    rocks_right(g)
    lantern(g)
    pool(g, 'R')
    yuzu_right(g)
    return g


def compose_right_submerged(phase):
    g = _base_right_grid_no_capy()
    capy_right_soak(g, ws.ear_pose(phase))
    _overlay_on_water(g, ws.soak_ripple_cells(phase, 9, WATERLINE))
    _overlay(g, ws.steam_cells(phase, STEAM_SEEDS_R, WATERLINE - 1, STEAM_CEIL))
    return [''.join(r) for r in g]


def _compose_right_jump(table, frame, phase0):
    """Compose one jump-transition frame. `phase0` offsets the steam/ripple
    phase so consecutive rendered frames across state handoffs (dry <-> jump
    <-> soak) always advance by consecutive phases -- see the runtime phase
    choreography comment above JUMP_FRAMES_OUT."""
    origin, splash = table[frame]
    g = _base_right_grid_no_capy()
    if origin is None:
        # splash first, then stamp the soak pose on top: the head/eyes redraw
        # over the splash so the eye-clobber (splash_cells is centered on the
        # same column as the soak pose's eyes) cannot recur, while any splash
        # cells above the head remain visible as spray -- see
        # test_jump_in_starts_dry_and_ends_submerged and
        # test_jump_impact_frames_show_splash
        _overlay(g, ws.splash_cells(splash, 9, WATERLINE))
        capy_right_soak(g, 0)
        _overlay_on_water(g, ws.soak_ripple_cells(phase0 + frame, 9, WATERLINE))
    else:
        # body first, splash after: spray renders in front of the body/rock,
        # the physically correct occlusion at impact
        _capy_right_at(g, *origin)
        _overlay(g, ws.splash_cells(splash, 9, WATERLINE))
    _overlay(g, ws.steam_cells(phase0 + frame, STEAM_SEEDS_R, WATERLINE - 1, STEAM_CEIL))
    return [''.join(r) for r in g]


def compose_right_jump_in(frame):
    return _compose_right_jump(JUMP_FRAMES_IN, frame, 0)


def compose_right_jump_out(frame):
    if frame == TRANS_FRAMES - 1:
        # The runtime now lands on __coAnimR[0] immediately AFTER this final
        # out-frame, and the steam phase must run ...14, 15, then wrap to 0 --
        # so this frame is compose_right(15), not compose_right(0).
        return compose_right(15)
    return _compose_right_jump(JUMP_FRAMES_OUT, frame, 10)


# --- subagent pups: tiny capybaras that join the pool while a Task-tool -------
# subagent runs. Position-independent sprite canvases; the runtime stamps
# them at per-slot offsets (see generate_package.py __coStampBand). '.' is
# transparent (palette index 0 at compile time).

PUP_W = 8               # canvas width: mask ink cols 1-6, splay ears reach 0/7
PUP_H = 6               # canvas height in subrows == 3 cell rows
PUP_SPLASH_W = 9        # splash canvas width (splash_cells spread 4 -> cols 0-8)
PUP_TRANS_FRAMES = 4
# (cx, eye_y) per slot: NW, NE, SW, SE. Canvas top = eye_y-4 (must be even and
# >= ANIM_TOP -- cellrow alignment). SE is a baked reserve; runtime uses 3.
PUP_SLOTS = [(6, 90), (24, 90), (6, 96), (24, 96)]

PUP_SOAK = [            # settled pose: crown + eyes proud of the water
    "cCCCCc",           # mask row 0 -> canvas row 3 (crown)
    "CEAAEC",           # mask row 1 -> canvas row 4 (eyes)
]
PUP_HIGH = [            # arrival/departure pose: one extra row of body
    "cCCCCc",
    "CEAAEC",
    ".cCCc.",           # mask row 2 -> canvas row 5 (chest, "riding high")
]
EAR_POSES_PUP = {       # (dx, dy) relative to mask origin; same flick rhythm
    0: [(0, -1), (4, -1)],                       # rest
    1: [(0, -2), (4, -2)],                       # lift
    2: [(-1, -2), (1, -1), (3, -1), (5, -2)],    # splay (double-flick peak)
}


def _pup_render(mask, ear):
    g = [['.'] * PUP_W for _ in range(PUP_H)]
    for r, line in enumerate(mask):
        for c, ch in enumerate(line):
            if ch != '.':
                g[3 + r][1 + c] = ch
    for dx, dy in EAR_POSES_PUP[ear]:
        x, y = 1 + dx, 3 + dy
        if 0 <= y < PUP_H and 0 <= x < PUP_W:
            g[y][x] = 'c'
    return [''.join(r) for r in g]


def pup_sprite_soak(ear):
    return _pup_render(PUP_SOAK, ear)


def pup_sprite_high(ear):
    return _pup_render(PUP_HIGH, ear)


def pup_sprite_splash(step):
    """splash_cells reused verbatim on a local canvas: cx=4, waterline y=5."""
    g = [['.'] * PUP_SPLASH_W for _ in range(PUP_H)]
    for x, y, ch in ws.splash_cells(step, 4, 5):
        if 0 <= y < PUP_H and 0 <= x < PUP_SPLASH_W:
            g[y][x] = ch
    return [''.join(r) for r in g]


# --- composer-flank bands (8 rows, 1 python row = 1 terminal row, solid) -------

def pool_left():
    g = [['W'] * W for _ in range(8)]
    for y in range(8):
        for x in range(W):
            if y >= 6:
                g[y][x] = 'v'
            elif y >= 3 and (x + y) % 2:
                g[y][x] = 'v'
            elif x > 22 and (x + y) % 2:
                g[y][x] = 'V'
    g[0][6] = 'F'; g[0][18] = 'F'
    return [''.join(r) for r in g]


def pool_right():
    g = [['W'] * W for _ in range(8)]
    for y in range(8):
        for x in range(W):
            if y >= 6:
                g[y][x] = 'v'
            elif y >= 3 and (x + y) % 2:
                g[y][x] = 'v'
            elif 18 < x < 30 and (x + y) % 2 and y < 3:
                g[y][x] = 'V'
    g[0][10] = 'F'; g[0][26] = 'F'
    return [''.join(r) for r in g]


# --- preview ------------------------------------------------------------------

def write_png(path, scale=6):
    panels = [compose_left(0), compose_right(0), compose_left(6), compose_right(6)]
    gap = 5
    width = (W * len(panels) + gap * (len(panels) - 1)) * scale
    px = bytearray()
    for y in range(H):
        line = []
        for gi, p in enumerate(panels):
            if gi:
                line += [(12, 12, 12)] * gap
            line += [COLOR.get(ch, (255, 0, 255)) for ch in p[y]]
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
    for p in range(PHASES):
        for rows in (compose_left(p), compose_right(p)):
            assert len(rows) == H and all(len(r) == W for r in rows)
    write_png(OUT / 'onsen-scene-preview.png')
    print('wrote', OUT / 'onsen-scene-preview.png')
