"""Render documentation icons from the canonical SVG asset."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from shutil import copyfile

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = ROOT / "assets" / "icon.svg"
ASSET_DIR = ROOT / "docs" / "assets"
SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)


def _render_png(size: int) -> bytes:
    rendered = cairosvg.svg2png(url=str(SVG_PATH), output_width=size, output_height=size)
    if rendered is None:
        raise RuntimeError(f"failed to render {SVG_PATH}")
    with Image.open(BytesIO(rendered)) as image:
        output = BytesIO()
        image.convert("RGBA").save(output, format="PNG", compress_level=9)
        return output.getvalue()


def main() -> int:
    if not SVG_PATH.is_file():
        print(f"missing SVG: {SVG_PATH}")
        return 1

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    copyfile(SVG_PATH, ASSET_DIR / "icon.svg")
    for size in SIZES:
        data = _render_png(size)
        target = ASSET_DIR / f"icon-{size}.png"
        target.write_bytes(data)
        print(f"wrote {target.relative_to(ROOT)} ({size}x{size})")
        if size == 512:
            (ASSET_DIR / "icon.png").write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
