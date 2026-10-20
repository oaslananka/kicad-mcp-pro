from __future__ import annotations

from pathlib import Path

from PIL import Image

from kicad_mcp import tray


def test_tray_uses_brand_asset_and_retains_status_indicator() -> None:
    asset = Path(tray.__file__).with_name("tray_assets") / "icon_64.png"
    with Image.open(asset) as source:
        base = source.convert("RGBA")

    for status in ("running", "stopped", "error", "starting"):
        icon = tray._create_icon(status)
        assert icon.crop((0, 0, 64, 46)).tobytes() == base.crop((0, 0, 64, 46)).tobytes()
        assert icon.getpixel((54, 54)) == (*tray._STATUS_COLORS[status], 255)
