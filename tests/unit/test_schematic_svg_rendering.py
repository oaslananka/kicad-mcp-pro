"""Real rasterizer regression tests for the default schematic PNG tool."""

from __future__ import annotations

import base64
import io
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PIL import Image

from kicad_mcp.tools.schematic import _render_svg_to_png

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60">{}</svg>'


def _svg(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "sheet.svg"
    path.write_text(_SVG.format(content), encoding="utf-8")
    return path


@pytest.mark.parametrize("crop", [False, True])
def test_render_without_system_cairo(tmp_path: Path, crop: bool) -> None:
    source = _svg(tmp_path, '<rect x="30" y="20" width="40" height="20" fill="black"/>')
    before = source.read_bytes()
    output = tmp_path / "sheet.png"

    report = _render_svg_to_png(source, output, dpi=100, crop_to_content=crop)

    assert source.read_bytes() == before
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.size == (report["width_px"], report["height_px"])
        assert image.size == ((48, 28) if crop else (100, 60))
        assert image.convert("RGBA").getbbox() is not None
    assert report["cropped"] is crop
    assert not (tmp_path / "sheet.full.png").exists()


@pytest.mark.parametrize(
    "href",
    [
        "../private.png",
        "file:///tmp/private.png",
        "https://example.invalid/private.png",
        "data:image/svg+xml;base64,PHN2Zy8+",
        "data:image/png;base64,PHN2Zy8+",
    ],
)
def test_renderer_refuses_nonlocal_or_nested_svg_resources(tmp_path: Path, href: str) -> None:
    source = _svg(tmp_path, f'<image href="{href}" width="30" height="30"/>')
    output = tmp_path / "sheet.png"
    with pytest.raises(RuntimeError, match="SVG resource"):
        _render_svg_to_png(source, output, dpi=100, crop_to_content=False)
    assert not output.exists()


def test_renderer_accepts_embedded_png(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (2, 2), "red").save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    source = _svg(tmp_path, f'<image href="data:image/png;base64,{data}" width="30" height="30"/>')
    output = tmp_path / "sheet.png"
    _render_svg_to_png(source, output, dpi=100, crop_to_content=False)
    with Image.open(output) as image:
        assert image.convert("RGBA").getpixel((10, 10)) == (255, 0, 0, 255)


@pytest.mark.parametrize(
    "content",
    [
        '<image href="#not-a-raster-resource" width="20" height="20"/>',
        '<image xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xlink:href="../private.png" width="20" height="20"/>',
        '<feImage href="../private.png"/>',
        '<image href="data:image/png;base64,???" width="20" height="20"/>',
    ],
)
def test_renderer_rejects_other_unsafe_resource_forms(tmp_path: Path, content: str) -> None:
    source = _svg(tmp_path, content)
    with pytest.raises(RuntimeError, match="SVG resource"):
        _render_svg_to_png(source, tmp_path / "output.png", dpi=100, crop_to_content=False)


def test_renderer_allows_internal_use_and_inert_link(tmp_path: Path) -> None:
    source = _svg(
        tmp_path,
        '<defs><rect id="block" width="20" height="20" fill="black"/></defs>'
        '<a href="https://example.invalid/datasheet"><use href="#block" x="10" y="10"/></a>',
    )
    output = tmp_path / "output.png"
    _render_svg_to_png(source, output, dpi=100, crop_to_content=False)
    with Image.open(output) as image:
        assert image.convert("RGBA").getpixel((15, 15)) == (0, 0, 0, 255)


@pytest.mark.parametrize(
    "svg",
    [
        "<svg>",
        '<!DOCTYPE svg [<!ENTITY unsafe SYSTEM "file:///private.png">]>'
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">&unsafe;</svg>',
    ],
)
def test_renderer_rejects_invalid_or_unsafe_xml(tmp_path: Path, svg: str) -> None:
    source = tmp_path / "sheet.svg"
    source.write_text(svg, encoding="utf-8")
    output = tmp_path / "output.png"
    with pytest.raises(RuntimeError, match="Invalid schematic SVG"):
        _render_svg_to_png(source, output, dpi=100, crop_to_content=False)
    assert not output.exists()


def test_png_renderer_is_in_default_package_dependencies() -> None:
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    metadata = tomllib.loads(project.read_text(encoding="utf-8"))["project"]
    runtime = {
        canonicalize_name(Requirement(requirement).name) for requirement in metadata["dependencies"]
    }
    assert {"pillow", "resvg-py"} <= runtime
    assert "cairosvg" not in runtime
