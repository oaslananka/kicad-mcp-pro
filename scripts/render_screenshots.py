from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets"
SCREENSHOT_DIR = ASSET_DIR / "screenshots"
ICON_PATH = ASSET_DIR / "icon-256.png"
HASH_PATH = ROOT / "scripts" / "_placeholder_hashes.json"
SIZE = (1920, 1080)
BACKGROUND = "#101522"
PANEL = "#172033"
PANEL_2 = "#0f1728"
ACCENT = "#00cec9"
SUCCESS = "#00b894"
WARN = "#fdcb6e"
TEXT = "#f5f6fa"
MUTED = "#b2bec3"

SLOTS = [
    {
        "filename": "01-claude-desktop-quality-gate.png",
        "title": "Quality Gate Review",
        "subtitle": "project_quality_gate · PASS · fixture: pass_sensor_node",
        "client": "Claude Desktop",
        "lines": [
            "PASS schematic_quality_gate · 0 blocking findings",
            "PASS pcb_readability · labels, zones, and board outline verified",
            "PASS manufacturing_preflight · export remains human-gated",
            "Evidence: DRC/ERC JSON, release manifest, checksum report",
        ],
    },
    {
        "filename": "02-cursor-schematic-build.png",
        "title": "Schematic Authoring",
        "subtitle": "sch_build_circuit · collision-safe labels · no star-routing shorts",
        "client": "Cursor",
        "lines": [
            "Generated terminal stubs on 2.54 mm grid",
            "Power rails annotated with design-intent metadata",
            "Connectivity warnings are structured and fix-queue ready",
            "Next step: run schematic_quality_gate and round-trip validation",
        ],
    },
    {
        "filename": "03-vscode-pcb-inspection.png",
        "title": "PCB Inspection",
        "subtitle": "pcb_get_board_state · readonly · KiCad 10.0.6 baseline",
        "client": "VS Code MCP",
        "lines": [
            "Board summary: footprints, nets, tracks, zones, vias",
            "Design rules and net classes loaded from project state",
            "IPC unavailable paths degrade to file-backed inspection",
            "No private board data shown; fixture-only screenshot evidence",
        ],
    },
    {
        "filename": "04-tools-reference.png",
        "title": "Tool Reference Catalog",
        "subtitle": "Generated MCP tool contracts · readOnly/destructive/openWorld hints",
        "client": "Docs Browser",
        "lines": [
            "300+ tools grouped by agent profile and capability domain",
            "Contract lint verifies annotations, profile routing, and parity",
            "Generated docs are checked in CI for drift-free releases",
            "MCP manifest uses io.github.oaslananka/kicad-mcp-pro",
        ],
    },
    {
        "filename": "05-export-manufacturing.png",
        "title": "Manufacturing Export Gate",
        "subtitle": "export_manufacturing_package · evidence-linked human approval",
        "client": "Claude Desktop",
        "lines": [
            "Release bundle: Gerber, drill, IPC-2581, BOM, CPL/PnP",
            "Quality gate must PASS before release artifacts are emitted",
            "Checksums, SBOM, and provenance are attached by release workflow",
            "Human sign-off remains required for fab-final handoff",
        ],
    },
]


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int, *, bold: bool = False, fill: str = TEXT) -> None:
    draw.text(xy, text, fill=fill, font=_font(size, bold=bold))


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None, width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=24, fill=fill, outline=outline, width=width)


def _render(slot: dict[str, object], icon: Image.Image) -> Path:
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)

    # Top product chrome.
    _rounded(draw, (96, 72, 1824, 1008), PANEL, outline="#24324d")
    draw.rectangle((96, 72, 1824, 152), fill="#111827")
    for i, color in enumerate(("#ff7675", "#fdcb6e", "#00b894")):
        draw.ellipse((132 + i * 34, 104, 152 + i * 34, 124), fill=color)
    _text(draw, (256, 101), f"KiCad MCP Pro · {slot['client']}", 28, fill=MUTED)

    # Left agent transcript.
    _rounded(draw, (136, 196, 900, 880), PANEL_2, outline="#2f3b57")
    icon_small = icon.resize((86, 86))
    image.paste(icon_small, (174, 226), icon_small)
    _text(draw, (284, 220), str(slot["title"]), 56, bold=True)
    _text(draw, (286, 292), str(slot["subtitle"]), 26, fill=MUTED)

    y = 390
    for idx, line in enumerate(slot["lines"]):
        color = SUCCESS if idx < 2 else (WARN if idx == 2 else ACCENT)
        draw.rounded_rectangle((184, y - 6, 218, y + 28), radius=8, fill=color)
        _text(draw, (238, y - 12), str(line), 27)
        y += 88

    _rounded(draw, (184, 770, 852, 838), "#0b1020", outline="#2f3b57")
    _text(draw, (214, 788), "Verification: metadata · manifest · parity · tool contracts", 24, fill=MUTED)

    # Right design surface.
    _rounded(draw, (962, 196, 1784, 880), "#0b1020", outline="#2f3b57")
    _text(draw, (1006, 232), "Release-safe evidence surface", 34, bold=True)
    _text(draw, (1008, 284), "Fixture-only board, no private paths, no secrets", 24, fill=MUTED)

    # Stylized PCB evidence.
    board = (1040, 354, 1710, 790)
    _rounded(draw, board, "#063b3c", outline="#00cec9", width=4)
    # Board grid and traces.
    for x in range(1090, 1680, 90):
        draw.line((x, 382, x, 760), fill="#0a585a", width=2)
    for y in range(400, 760, 70):
        draw.line((1068, y, 1680, y), fill="#0a585a", width=2)
    for x1, y1, x2, y2 in ((1100, 430, 1450, 430), (1450, 430, 1450, 620), (1160, 620, 1620, 620), (1260, 500, 1260, 700)):
        draw.line((x1, y1, x2, y2), fill="#fdcb6e", width=8)
    for x, y in ((1100, 430), (1450, 430), (1450, 620), (1160, 620), (1620, 620), (1260, 500), (1260, 700)):
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill=ACCENT, outline=TEXT, width=3)
    for x, y, label in ((1168, 478, "U1"), (1520, 516, "J1"), (1330, 682, "PWR")):
        _rounded(draw, (x, y, x + 130, y + 70), "#172033", outline="#dfe6e9")
        _text(draw, (x + 34, y + 19), label, 26, bold=True)

    _text(draw, (1044, 916), "Generated from repository-owned fixtures for public listing review", 24, fill=MUTED)

    target = SCREENSHOT_DIR / str(slot["filename"])
    image.save(target, format="PNG", compress_level=9)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-placeholder-hashes", action="store_true", help="overwrite placeholder hash baselines; do not use for production media")
    args = parser.parse_args()

    if not ICON_PATH.is_file():
        print(f"missing icon asset: {ICON_PATH.relative_to(ROOT)}")
        return 1
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(ICON_PATH) as icon_source:
        icon = icon_source.convert("RGBA")

    hashes: dict[str, str] = {}
    for slot in SLOTS:
        target = _render(slot, icon)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        hashes[target.name] = digest
        print(f"wrote {target.relative_to(ROOT)} sha256:{digest}")

    if args.update_placeholder_hashes:
        HASH_PATH.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"updated placeholder hash baseline: {HASH_PATH.relative_to(ROOT)}")
    else:
        print("left placeholder hash baseline unchanged for final-submission stale-media detection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
