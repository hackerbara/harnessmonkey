from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

TRAY_ICON_VARIANTS = ("normal", "pending")


def tray_icon(variant: str = "normal") -> QIcon:
    """Tray `QIcon` for `variant` ("normal" or "pending").

    `variant` is decided by `gui/window_model.tray_icon_variant` -- this
    function only picks the matching asset files (`Tray.render` is the
    caller). "pending" is a badge/dot variant of the same monochrome
    template icon (see `scripts/generate_icons.py`'s `render_tray_icon_pending`)
    -- macOS template icons can't use color to signal state, so a shape
    change is the robust choice.
    """
    suffix = "" if variant == "normal" else f"-{variant}"
    icon = QIcon()
    for size in (18, 36):
        icon.addFile(str(ASSETS_DIR / f"monkey-tray-{size}{suffix}.png"))
    icon.setIsMask(True)  # macOS template behavior; harmless on Windows
    return icon


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (128, 256, 512):
        icon.addFile(str(ASSETS_DIR / f"monkey-color-{size}.png"))
    return icon
