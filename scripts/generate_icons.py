"""Deterministic monkey icon generator for HarnessMonkey.

Generates two icon families under ``src/harnessmonkey/gui/assets/``:

- "tray" icons: opaque-black-on-transparent template masks (for the macOS
  menu bar), sizes 18 and 36 px, plus a "-pending" badge variant of each
  (shown while a rebuild is pending -- see `gui/window_model.tray_icon_variant`).
- "color" icons: full-color application icons, sizes 128, 256, and 512 px.

All shapes are drawn as hard-edged filled ellipses directly on an RGBA
canvas (no antialiasing, no resampling), so the tray icons contain only
pure black (0, 0, 0) at any pixel with alpha > 0 -- required for macOS
template/mask icon semantics and for byte-for-byte reproducible output.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parents[1] / "src" / "harnessmonkey" / "gui" / "assets"

TRAY_SIZES = (18, 36)
COLOR_SIZES = (128, 256, 512)

BLACK_OPAQUE = (0, 0, 0, 255)
TRANSPARENT = (0, 0, 0, 0)
BROWN = (0x8B, 0x5E, 0x3C, 255)
TAN = (0xD9, 0xB3, 0x8C, 255)

# Geometry, as fractions of icon size ``s``.
HEAD_BOX = (0.18, 0.22, 0.82, 0.88)
EAR_CENTERS = ((0.16, 0.34), (0.84, 0.34))
EAR_RADIUS = 0.14
FACE_BOX = (0.30, 0.42, 0.70, 0.86)
EYE_CENTERS = ((0.40, 0.52), (0.60, 0.52))
EYE_RADIUS = 0.045
NOSTRIL_CENTERS = ((0.46, 0.70), (0.54, 0.70))
NOSTRIL_RADIUS = 0.02

# Pending-rebuild badge (spec: tray icon must be visibly distinct while
# `rebuildRequired` -- see `gui/window_model.tray_icon_variant`). macOS
# template icons are monochrome (opaque black + alpha only), so this can't
# be a color change -- instead a solid dot sits outside the head/ear
# silhouette (bottom-right corner), changing the icon's overall alpha shape
# enough to read as visually distinct at a glance.
BADGE_CENTER = (0.86, 0.86)
BADGE_RADIUS = 0.16


Box = tuple[float, float, float, float]


def _scaled_box(box: Box, size: int) -> Box:
    x0, y0, x1, y1 = box
    return (x0 * size, y0 * size, x1 * size, y1 * size)


def _circle_box(center: tuple[float, float], radius: float, size: int) -> Box:
    cx, cy = center
    cx *= size
    cy *= size
    r = radius * size
    return (cx - r, cy - r, cx + r, cy + r)


def render_tray_icon(size: int) -> Image.Image:
    """Render the opaque-black-on-transparent template/mask icon."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    draw.ellipse(_scaled_box(HEAD_BOX, size), fill=BLACK_OPAQUE)
    for center in EAR_CENTERS:
        draw.ellipse(_circle_box(center, EAR_RADIUS, size), fill=BLACK_OPAQUE)
    # Punch the face inset out to fully transparent.
    draw.ellipse(_scaled_box(FACE_BOX, size), fill=TRANSPARENT)
    return img


def render_tray_icon_pending(size: int) -> Image.Image:
    """Same as `render_tray_icon` plus a solid corner-dot badge.

    Used for the pending-rebuild tray-icon variant (see
    `gui/window_model.tray_icon_variant`, `gui/icons.tray_icon`).
    """
    img = render_tray_icon(size)
    draw = ImageDraw.Draw(img)
    draw.ellipse(_circle_box(BADGE_CENTER, BADGE_RADIUS, size), fill=BLACK_OPAQUE)
    return img


def render_color_icon(size: int) -> Image.Image:
    """Render the full-color application icon."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    draw.ellipse(_scaled_box(HEAD_BOX, size), fill=BROWN)
    draw.ellipse(_scaled_box(FACE_BOX, size), fill=TAN)
    for center in EYE_CENTERS:
        draw.ellipse(_circle_box(center, EYE_RADIUS, size), fill=BLACK_OPAQUE)
    for center in NOSTRIL_CENTERS:
        draw.ellipse(_circle_box(center, NOSTRIL_RADIUS, size), fill=BLACK_OPAQUE)
    return img


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for size in TRAY_SIZES:
        path = ASSETS_DIR / f"monkey-tray-{size}.png"
        render_tray_icon(size).save(path)
        written.append(path)

        pending_path = ASSETS_DIR / f"monkey-tray-{size}-pending.png"
        render_tray_icon_pending(size).save(pending_path)
        written.append(pending_path)

    for size in COLOR_SIZES:
        path = ASSETS_DIR / f"monkey-color-{size}.png"
        render_color_icon(size).save(path)
        written.append(path)

    for path in written:
        print(path)


if __name__ == "__main__":
    main()
