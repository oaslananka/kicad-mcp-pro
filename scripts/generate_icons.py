"""Generate tray and MCP package icons from a source SVG.

Usage:
    python scripts/generate_icons.py --source assets/icon.svg
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _render_svg(source: Path, output: Path, size: int) -> None:
    """Render ``source`` to ``output`` using CairoSVG."""
    try:
        import cairosvg
    except ImportError as exc:  # pragma: no cover - developer environment guard
        raise SystemExit("cairosvg is required: uv sync --extra dev") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(
        url=str(source),
        write_to=str(output),
        output_width=size,
        output_height=size,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Source SVG file.")
    args = parser.parse_args()

    source = args.source
    if not source.exists():
        raise SystemExit(f"Source SVG not found: {source}")

    tray_dir = Path("src/kicad_mcp/tray_assets")
    _render_svg(source, tray_dir / "icon_64.png", 64)
    _render_svg(source, Path("packaging/mcpb/icon.png"), 512)
    _render_svg(source, Path("packages/kicad-plugin/icon.png"), 64)
    print(f"Generated icons from {source}")


if __name__ == "__main__":
    main()
