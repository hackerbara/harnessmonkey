#!/usr/bin/env python3
"""Render sidecar NDJSON ANSI frames into a watchable GIF.

This is intentionally a spike helper, not a terminal emulator. It supports the
SGR truecolor subset emitted by Chafa and our in-process encoders: reset, fg
38;2;r;g;b, bg 48;2;r;g;b, newline, and printable one-cell glyphs.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ESC_RE = re.compile(r"\x1b\[([0-9;]*)m")
DEFAULT_FG = (210, 220, 235)
DEFAULT_BG = (4, 7, 20)
DEFAULT_FONT = "/System/Library/Fonts/Menlo.ttc"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ndjson", type=Path, help="Sidecar NDJSON capture")
    parser.add_argument("output", type=Path, help="Output GIF path")
    parser.add_argument("--fps", type=float, default=6.0, help="Animation frames per second")
    parser.add_argument("--cell-width", type=int, default=10, help="Rendered pixel width per terminal cell")
    parser.add_argument("--cell-height", type=int, default=20, help="Rendered pixel height per terminal cell")
    parser.add_argument("--font-size", type=int, default=18, help="Font size for terminal glyphs")
    parser.add_argument("--font", default=DEFAULT_FONT, help="Monospace font path")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum frames to render")
    return parser.parse_args()


def load_frames(path: Path, limit: int = 0) -> list[dict]:
    frames: list[dict] = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") != "frame" or "data" not in msg:
            continue
        ansi = base64.b64decode(msg["data"]).decode("utf-8", errors="replace")
        frames.append({
            "ansi": ansi,
            "width": int(msg.get("width") or 80),
            "height": int(msg.get("height") or 32),
            "seq": int(msg.get("seq") or len(frames) + 1),
        })
        if limit and len(frames) >= limit:
            break
    if not frames:
        raise SystemExit(f"No frame messages with base64 ANSI data found in {path}")
    return frames


def apply_sgr(params: str, fg: tuple[int, int, int], bg: tuple[int, int, int]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    codes = [0] if params == "" else [int(part) if part else 0 for part in params.split(";")]
    i = 0
    while i < len(codes):
        code = codes[i]
        if code == 0:
            fg, bg = DEFAULT_FG, DEFAULT_BG
            i += 1
        elif code == 39:
            fg = DEFAULT_FG
            i += 1
        elif code == 49:
            bg = DEFAULT_BG
            i += 1
        elif code == 38 and i + 4 < len(codes) and codes[i + 1] == 2:
            fg = tuple(max(0, min(255, c)) for c in codes[i + 2:i + 5])  # type: ignore[assignment]
            i += 5
        elif code == 48 and i + 4 < len(codes) and codes[i + 1] == 2:
            bg = tuple(max(0, min(255, c)) for c in codes[i + 2:i + 5])  # type: ignore[assignment]
            i += 5
        else:
            i += 1
    return fg, bg


def render_ansi_frame(frame: dict, font: ImageFont.FreeTypeFont, cell_w: int, cell_h: int) -> Image.Image:
    cols = frame["width"]
    rows = frame["height"]
    image = Image.new("RGB", (cols * cell_w, rows * cell_h), DEFAULT_BG)
    draw = ImageDraw.Draw(image)
    fg = DEFAULT_FG
    bg = DEFAULT_BG
    x = 0
    y = 0
    text_y_offset = -2
    text = frame["ansi"]
    i = 0
    while i < len(text) and y < rows:
        ch = text[i]
        if ch == "\x1b":
            match = ESC_RE.match(text, i)
            if match:
                fg, bg = apply_sgr(match.group(1), fg, bg)
                i = match.end()
                continue
            # Skip unknown CSI/control-ish escape conservatively.
            i += 1
            continue
        if ch == "\n":
            x = 0
            y += 1
            i += 1
            continue
        if ch == "\r":
            x = 0
            i += 1
            continue
        if ord(ch) < 32:
            i += 1
            continue
        if x < cols:
            x0 = x * cell_w
            y0 = y * cell_h
            draw.rectangle((x0, y0, x0 + cell_w, y0 + cell_h), fill=bg)
            if ch != " ":
                draw.text((x0, y0 + text_y_offset), ch, font=font, fill=fg)
            x += 1
        i += 1
    return image


def main() -> None:
    args = parse_args()
    frames = load_frames(args.ndjson, args.limit)
    font = ImageFont.truetype(args.font, args.font_size)
    images = [render_ansi_frame(frame, font, args.cell_width, args.cell_height) for frame in frames]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = max(1, int(round(1000 / max(args.fps, 0.1))))
    images[0].save(
        args.output,
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
        disposal=2,
    )
    print(json.dumps({
        "output": str(args.output),
        "frames": len(images),
        "width": images[0].width,
        "height": images[0].height,
        "durationMs": duration_ms,
    }))


if __name__ == "__main__":
    main()
