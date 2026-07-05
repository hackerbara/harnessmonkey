"""Boot the v11 binary in a tall PTY, capture one rendered frame, and rasterize
its half-block ANSI back to a PNG — a faithful image of what the binary paints.

Parses absolute cursor positioning (CSI H / CSI row;colH), SGR truecolor/256,
and ▀ half-blocks into a cell grid, then expands each cell into 2 vertical pixels.
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

ROWS, COLS = 55, 120
# Place a locally built, codesigned patched binary here before running (see README) --
# this build artifact is not shipped in the repo.
BIN = Path(__file__).resolve().parent / 'build' / 'claude'
OUT = Path(__file__).parent / 'v11-REAL-frame.png'


def grab() -> bytes:
    env = os.environ.copy()
    env.update({'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', 'FORCE_COLOR': '1'})
    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, 0, 0))
    proc = subprocess.Popen([str(BIN)], stdin=slave, stdout=slave, stderr=slave,
                            cwd=str(Path.home()), env=env, start_new_session=True, close_fds=True)
    os.close(slave)
    chunks = []
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        r, _, _ = select.select([master], [], [], 0.1)
        if r:
            try:
                d = os.read(master, 65536)
            except OSError:
                break
            if not d:
                break
            chunks.append(d)
        if proc.poll() is not None:
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
    return b''.join(chunks)


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


def render(data: bytes) -> None:
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
    i = 0
    n = len(frame)
    while i < n:
        c = frame[i]
        if c == '\x1b':
            m = re.match(r'\x1b\[([0-9;?]*)([A-Za-z])', frame[i:])
            if not m:
                i += 1
                continue
            params, cmd = m.group(1), m.group(2)
            if cmd == 'H':
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
            i += m.end()
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
        else:
            if 0 <= cy < ROWS and 0 <= cx < COLS:
                grid_ch[cy][cx] = c
                grid_fg[cy][cx] = fg
                grid_bg[cy][cx] = bg
            cx += 1
            i += 1
            continue

    # rasterize: each cell -> 2 vertical px. ▀ => top=fg, bottom=bg; else solid bg.
    scale = 5
    px = bytearray()
    for y in range(ROWS):
        for half in (0, 1):  # top row of px then bottom row
            scan = bytearray()
            for x in range(COLS):
                ch = grid_ch[y][x]
                if ch == '▀':
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


if __name__ == '__main__':
    render(grab())
