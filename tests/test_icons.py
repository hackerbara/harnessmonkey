import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / "src" / "harnessmonkey" / "gui" / "assets"


def test_generator_writes_expected_files(tmp_path):
    subprocess.run([sys.executable, "scripts/generate_icons.py"], check=True)
    for name, size in [("monkey-tray-18.png", 18), ("monkey-tray-36.png", 36),
                       ("monkey-color-512.png", 512)]:
        img = Image.open(ASSETS / name)
        assert img.size == (size, size) and img.mode == "RGBA"


def test_tray_icon_is_monochrome_with_alpha():
    img = Image.open(ASSETS / "monkey-tray-18.png").convert("RGBA")
    colors = {px[:3] for px in img.getdata() if px[3] > 0}
    assert colors == {(0, 0, 0)}  # template: pure black + alpha only


# ---------------------------------------------------------------------------
# Pending-rebuild tray icon variant
# ---------------------------------------------------------------------------


def test_generator_writes_pending_variant_files(tmp_path):
    subprocess.run([sys.executable, "scripts/generate_icons.py"], check=True)
    for name, size in [("monkey-tray-18-pending.png", 18), ("monkey-tray-36-pending.png", 36)]:
        img = Image.open(ASSETS / name)
        assert img.size == (size, size) and img.mode == "RGBA"


def test_pending_tray_icon_is_monochrome_with_alpha():
    img = Image.open(ASSETS / "monkey-tray-18-pending.png").convert("RGBA")
    width, height = img.size
    colors = {
        img.getpixel((x, y))[:3]
        for x in range(width)
        for y in range(height)
        if img.getpixel((x, y))[3] > 0
    }
    assert colors == {(0, 0, 0)}  # still template: pure black + alpha only


def test_pending_variant_is_visually_distinct_from_normal():
    # Since template icons are monochrome, the "pending" variant can't be
    # distinguished by color -- it must differ in *shape* (which pixels have
    # alpha > 0). The badge adds opaque pixels the normal icon doesn't have.
    normal = Image.open(ASSETS / "monkey-tray-36.png").convert("RGBA")
    pending = Image.open(ASSETS / "monkey-tray-36-pending.png").convert("RGBA")
    normal_opaque = {(x, y) for x in range(36) for y in range(36) if normal.getpixel((x, y))[3] > 0}
    pending_opaque = {
        (x, y) for x in range(36) for y in range(36) if pending.getpixel((x, y))[3] > 0
    }
    assert pending_opaque != normal_opaque
    assert pending_opaque - normal_opaque  # the badge adds new opaque pixels


def test_tray_icon_variant_selects_matching_asset_files(qapp):
    from harnessmonkey.gui.icons import tray_icon

    normal = tray_icon("normal")
    pending = tray_icon("pending")
    assert normal.isNull() is False
    assert pending.isNull() is False
    assert normal.availableSizes() != []
    assert pending.availableSizes() != []
