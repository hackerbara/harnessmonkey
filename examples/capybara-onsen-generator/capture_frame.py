"""Boot the capybara-onsen binary in a tall PTY, capture the fully-painted
screen (waiting for output to go quiet), and rasterize its half-block ANSI
back to a PNG — a faithful image of what the binary paints.

Parses absolute cursor positioning (CSI H / CSI row;colH), SGR truecolor/256,
and half-blocks into a cell grid, then expands each cell into 2 vertical
pixels. Adapted from highdef-v11's capture_frame.py template for the
capybara-onsen build.
"""
from __future__ import annotations

import os
import pty
import re
import select
import signal
import struct
import subprocess
import fcntl
import termios
import time
from pathlib import Path

ROWS, COLS = 50, 140
# Place a locally built, codesigned patched binary here before running (see README) --
# this build artifact is not shipped in the repo.
BIN = Path(__file__).resolve().parent / 'build' / 'claude'
OUT = Path(__file__).parent / 'onsen-REAL-frame.png'
RAW_LOG = Path(__file__).parent / 'onsen-REAL-raw.bin'

QUIET_SECONDS = 3.0
CAP_SECONDS = 30.0


def grab() -> bytes:
    env = os.environ.copy()
    env.update({'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', 'FORCE_COLOR': '1'})
    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, 0, 0))
    proc = subprocess.Popen([str(BIN)], stdin=slave, stdout=slave, stderr=slave,
                            cwd=str(Path.home()), env=env, start_new_session=True, close_fds=True)
    os.close(slave)
    chunks = []
    start = time.monotonic()
    last_data = start
    deadline = start + CAP_SECONDS
    while True:
        now = time.monotonic()
        if now >= deadline:
            break
        if now - last_data >= QUIET_SECONDS and chunks:
            break
        r, _, _ = select.select([master], [], [], 0.2)
        if r:
            try:
                d = os.read(master, 65536)
            except OSError:
                break
            if not d:
                break
            chunks.append(d)
            last_data = time.monotonic()
        if proc.poll() is not None:
            # give it a brief moment in case more output trails the exit
            time.sleep(0.1)
            break
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass
    os.close(master)
    data = b''.join(chunks)
    RAW_LOG.write_bytes(data)
    print(f'captured {len(data)} bytes over {time.monotonic() - start:.1f}s')
    return data


CUBE = [0, 95, 135, 175, 215, 255]


def ansi256_rgb(n: int) -> tuple[int, int, int]:
    if n < 16:
        base = [(0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0), (0, 0, 128),
                (128, 0, 128), (0, 128, 128), (192, 192, 192), (128, 128, 128),
                (255, 0, 0), (0, 255, 0), (255, 255, 0), (0, 0, 255), (255, 0, 255),
                (0, 255, 255), (255, 255, 255)]
        return base[n]
    if n >= 232:
        v = 8 + (n - 232) * 10
        return (v, v, v)
    n -= 16
    return (CUBE[(n // 36) % 6], CUBE[(n // 6) % 6], CUBE[n % 6])


def render(data: bytes) -> tuple[list, list, list]:
    text = data.decode('utf-8', 'replace')
    # Frames after the first are cell-DIFFS. Accumulate the whole stream into a
    # persistent grid (ignoring clears) so the final grid ~= full painted screen.
    frame = text
    grid_fg = [[(0, 0, 0)] * COLS for _ in range(ROWS)]
    grid_bg = [[(0, 0, 0)] * COLS for _ in range(ROWS)]
    grid_ch = [[' '] * COLS for _ in range(ROWS)]
    cx = cy = 0
    fg = (200, 200, 200)
    bg = (0, 0, 0)
    saved_cx = saved_cy = 0
    alt_screen_entries = 0
    i = 0
    n = len(frame)
    while i < n:
        c = frame[i]
        if c == '\x1b':
            # CSI sequences: ESC [ params letter
            m = re.match(r'\x1b\[([0-9;?]*)([A-Za-z@])', frame[i:])
            if m:
                params, cmd = m.group(1), m.group(2)
                if cmd == 'H' or cmd == 'f':
                    nums = [int(x) for x in params.split(';') if x] or [1, 1]
                    cy = (nums[0] - 1) if len(nums) >= 1 else 0
                    cx = (nums[1] - 1) if len(nums) >= 2 else 0
                elif cmd == 'm':
                    ps = [p for p in params.split(';')]
                    j = 0
                    while j < len(ps):
                        p = ps[j]
                        if p == '' or p == '0':
                            fg, bg = (200, 200, 200), (0, 0, 0)
                        elif p == '38' and j + 1 < len(ps) and ps[j + 1] == '2':
                            fg = (int(ps[j + 2]), int(ps[j + 3]), int(ps[j + 4]))
                            j += 4
                        elif p == '48' and j + 1 < len(ps) and ps[j + 1] == '2':
                            bg = (int(ps[j + 2]), int(ps[j + 3]), int(ps[j + 4]))
                            j += 4
                        elif p == '38' and j + 1 < len(ps) and ps[j + 1] == '5':
                            fg = ansi256_rgb(int(ps[j + 2]))
                            j += 2
                        elif p == '48' and j + 1 < len(ps) and ps[j + 1] == '5':
                            bg = ansi256_rgb(int(ps[j + 2]))
                            j += 2
                        j += 1
                elif cmd == 'G':
                    cx = (int(params) - 1) if params else 0
                elif cmd == 'd':
                    cy = (int(params) - 1) if params else 0
                elif cmd in 'ABCDEF':
                    k = int(params) if params else 1
                    if cmd == 'A':
                        cy = max(0, cy - k)
                    elif cmd == 'B':
                        cy += k
                    elif cmd == 'C':
                        cx += k
                    elif cmd == 'D':
                        cx = max(0, cx - k)
                    elif cmd == 'E':
                        cy += k
                        cx = 0
                    elif cmd == 'F':
                        cy = max(0, cy - k)
                        cx = 0
                elif cmd == 'J':
                    # erase display: 0=below,1=above,2=all,3=all+scrollback
                    mode = int(params) if params else 0
                    if mode == 2 or mode == 3:
                        for yy in range(ROWS):
                            for xx in range(COLS):
                                grid_ch[yy][xx] = ' '
                                grid_bg[yy][xx] = (0, 0, 0)
                    elif mode == 0:
                        for xx in range(cx, COLS):
                            grid_ch[cy][xx] = ' '
                        for yy in range(cy + 1, ROWS):
                            for xx in range(COLS):
                                grid_ch[yy][xx] = ' '
                    elif mode == 1:
                        for xx in range(0, cx + 1):
                            grid_ch[cy][xx] = ' '
                        for yy in range(0, cy):
                            for xx in range(COLS):
                                grid_ch[yy][xx] = ' '
                elif cmd == 'K':
                    mode = int(params) if params else 0
                    if mode == 0:
                        for xx in range(cx, COLS):
                            if 0 <= cy < ROWS:
                                grid_ch[cy][xx] = ' '
                    elif mode == 1:
                        for xx in range(0, cx + 1):
                            if 0 <= cy < ROWS:
                                grid_ch[cy][xx] = ' '
                    elif mode == 2:
                        if 0 <= cy < ROWS:
                            for xx in range(COLS):
                                grid_ch[cy][xx] = ' '
                elif cmd == 's':
                    saved_cx, saved_cy = cx, cy
                elif cmd == 'u':
                    cx, cy = saved_cx, saved_cy
                elif cmd == 'h' and '?' in params:
                    if '1049' in params or '47' in params:
                        alt_screen_entries += 1
                i += m.end()
                continue
            i += 1
            continue
        elif c == '\n':
            cy += 1
            cx = 0
            i += 1
            continue
        elif c == '\r':
            cx = 0
            i += 1
            continue
        elif c == '\x08':
            cx = max(0, cx - 1)
            i += 1
            continue
        else:
            if 0 <= cy < ROWS and 0 <= cx < COLS:
                grid_ch[cy][cx] = c
                grid_fg[cy][cx] = fg
                grid_bg[cy][cx] = bg
            cx += 1
            i += 1
            continue

    print(f'alt-screen enter sequences seen: {alt_screen_entries}')
    return grid_fg, grid_bg, grid_ch


def rasterize(grid_fg, grid_bg, grid_ch, scale=6) -> None:
    px = bytearray()
    for y in range(ROWS):
        for half in (0, 1):  # top row of px then bottom row
            scan = bytearray()
            for x in range(COLS):
                ch = grid_ch[y][x]
                if ch == '▀':  # ▀
                    rgb = grid_fg[y][x] if half == 0 else grid_bg[y][x]
                else:
                    rgb = grid_bg[y][x]
                scan.extend(bytes(rgb) * scale)
            for _ in range(scale):
                px.extend(scan)
    ppm = OUT.with_suffix('.ppm')
    ppm.write_bytes(f'P6\n{COLS * scale} {ROWS * 2 * scale}\n255\n'.encode() + bytes(px))
    subprocess.run(['sips', '-s', 'format', 'png', str(ppm), '--out', str(OUT)],
                   check=True, capture_output=True)
    print('wrote', OUT)


def find_color(grid_fg, grid_bg, target, tol=6):
    hits = []
    for y in range(ROWS):
        for x in range(COLS):
            for label, grid in (('fg', grid_fg), ('bg', grid_bg)):
                r, g, b = grid[y][x]
                tr, tg, tb = target
                if abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol:
                    hits.append((y, x, label, (r, g, b)))
    return hits


if __name__ == '__main__':
    data = grab()
    grid_fg, grid_bg, grid_ch = render(data)
    rasterize(grid_fg, grid_bg, grid_ch)

    lantern = find_color(grid_fg, grid_bg, (255, 198, 92), tol=10)
    print(f'lantern-color hits (tol=10): {len(lantern)}')
    for h in lantern[:40]:
        print('  ', h)

    capy = find_color(grid_fg, grid_bg, (142, 96, 58), tol=10)
    print(f'capy-brown hits (tol=10): {len(capy)}')

    stream = find_color(grid_fg, grid_bg, (236, 248, 255), tol=10)
    print(f'stream-blue hits (tol=10): {len(stream)}')

    print('--- right wall rows 17-20, cols 108-139 dump ---')
    for y in range(17, 21):
        for x in range(108, 140):
            fg = grid_fg[y][x]
            bg = grid_bg[y][x]
            ch = grid_ch[y][x]
            if ch != ' ' or fg != (0, 0, 0) or bg != (0, 0, 0):
                print(f'  y={y} x={x} ch={ch!r} fg={fg} bg={bg}')
