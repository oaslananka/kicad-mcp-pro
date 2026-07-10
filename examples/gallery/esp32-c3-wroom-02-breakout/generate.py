#!/usr/bin/env python3
"""Regenerate the wired ESP32-C3-WROOM-02 breakout schematic via KiCad MCP Pro.

This is the reference implementation of the ``wired-subcircuit-design`` skill.
It drives the same tools an agent calls (``sch_build_circuit`` / ``run_erc``),
building the sheet in a SINGLE ``sch_build_circuit`` pass with explicit symbol
coordinates, explicit wires, labels and power symbols.

Why a single pass and not incremental ``sch_add_symbol`` calls: a fresh
schematic seeded on disk has no root UUID that the reader round-trips, so each
incremental add would stamp a different instance path and KiCad renders a blank
sheet. ``sch_build_circuit`` writes the whole file once with one consistent root
UUID, so every symbol lands on the root sheet.

Requirements: KiCad 10 system symbol libraries (RF_Module, Device, Switch,
Connector_Generic) and ``kicad-cli`` on PATH. Run from a checkout:

    KICAD_MCP_OPERATING_MODE=write python examples/gallery/esp32-c3-wroom-02-breakout/generate.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def find_symbol_dir() -> Path:
    for cand in (
        Path("/usr/share/kicad/symbols"),
        Path("/usr/local/share/kicad/symbols"),
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
        Path(os.environ.get("KICAD9_SYMBOL_DIR", "")),
        Path(os.environ.get("KICAD_SYMBOL_DIR", "")),
    ):
        if cand and cand.exists():
            return cand
    raise SystemExit("Could not locate KiCad system symbol libraries.")


SYSLIB = find_symbol_dir()
PROJECT = HERE
NAME = "esp32-c3-wroom-02-breakout"
GRID = 1.27
SYMS: list[dict] = []
WIRES: list[dict] = []
LABELS: list[dict] = []
POWERS: list[dict] = []
_pins = None

os.environ.setdefault("KICAD_MCP_OPERATING_MODE", "write")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))


def gg(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


def seed() -> None:
    (PROJECT / f"{NAME}.kicad_pro").write_text('{"meta":{"version":1}}', encoding="utf-8")
    (PROJECT / f"{NAME}.kicad_sch").write_text(
        "(kicad_sch\n\t(version 20250316)\n\t(generator \"kicad-mcp-pro\")\n"
        '\t(uuid "b2c3d4e5-0000-4000-8000-000000000001")\n\t(paper "A3")\n'
        "\t(lib_symbols)\n\t(sheet_instances\n\t\t(path \"/\" (page \"1\"))\n\t)\n"
        "\t(embedded_fonts no)\n)\n",
        encoding="utf-8",
    )
    libs = ["RF_Module", "Device", "Switch", "Connector_Generic"]
    entries = "\n".join(
        f'  (lib (name "{n}")(type "KiCad")(uri "{SYSLIB}/{n}.kicad_sym")(options "")(descr ""))'
        for n in libs
    )
    (PROJECT / "sym-lib-table").write_text(f"(sym_lib_table\n{entries}\n)\n", encoding="utf-8")


def PP(lib, name, x, y, rot=0):
    placed = _pins(lib, name, gg(x), gg(y), rot, 1)
    return {p: (round(px, 2), round(py, 2)) for p, (px, py) in placed.items()}


def sym(lib, name, x, y, ref, val, rot=0):
    x, y = gg(x), gg(y)
    SYMS.append({"library": lib, "symbol_name": name, "x_mm": x, "y_mm": y,
                 "reference": ref, "value": val, "rotation": rot})
    return PP(lib, name, x, y, rot)


def raw_sym(lib, name, x, y, ref, val, rot=0):
    SYMS.append({"library": lib, "symbol_name": name, "x_mm": gg(x), "y_mm": gg(y),
                 "reference": ref, "value": val, "rotation": rot})


def wire(x1, y1, x2, y2):
    WIRES.append({"x1_mm": gg(x1), "y1_mm": gg(y1), "x2_mm": gg(x2), "y2_mm": gg(y2)})


def pwr(name, x, y, rot=0):
    POWERS.append({"name": name, "x_mm": gg(x), "y_mm": gg(y), "rotation": rot})


def lbl(name, x, y, justify=None):
    d = {"name": name, "x_mm": gg(x), "y_mm": gg(y), "rotation": 0}
    if justify:
        d["justify"] = justify
    LABELS.append(d)


def stub_label(pin, origin_x, net, length=7.62):
    px, py = pin
    out = -1 if px < origin_x else 1
    ex = gg(px + out * length)
    wire(px, py, ex, py)
    lbl(net, ex, py, justify="right" if out < 0 else "left")


def two(d):
    return tuple(sorted(d.items(), key=lambda kv: kv[1][1]))


def build_plan():
    ux, uy = 185.0, 120.0
    U = sym("RF_Module", "ESP32-C3-WROOM-02", ux, uy, "U1", "ESP32-C3-WROOM-02")

    # single source of truth for the breakout bus (U1 pin -> net)
    BREAKOUT = [
        ("2", "EN"), ("18", "IO0"), ("17", "IO1"), ("16", "IO2"), ("15", "IO3"),
        ("3", "IO4"), ("4", "IO5"), ("5", "IO6"), ("6", "IO7"), ("7", "IO8"),
        ("8", "IO9"), ("10", "IO10"), ("13", "IO18"), ("14", "IO19"),
        ("11", "RXD"), ("12", "TXD"),
    ]
    for pin, net in BREAKOUT:
        stub_label(U[pin], ux, net)

    # header J1 — labels drawn from the SAME list, so sets match by construction
    j1x = 275.0
    J1 = sym("Connector_Generic", "Conn_01x16", j1x, uy, "J1", "GPIO")
    j1_sorted = [xy for _, xy in sorted(J1.items(), key=lambda kv: kv[1][1])]
    for (_pin, net), jxy in zip(BREAKOUT, j1_sorted, strict=True):
        stub_label(jxy, j1x, net)

    # power rails + decoupling, to the RIGHT of U1 (clear of the left stub fan)
    x3, y3 = U["1"]
    railY = gg(y3 - 12.7)
    railR = gg(ux + 45)
    wire(x3, y3, x3, railY)
    wire(x3, railY, railR, railY)
    pwr("+3V3", x3, railY)
    raw_sym("power", "PWR_FLAG", railR, railY, "#FLG01", "PWR_FLAG", rot=0)

    xg, yg = U["9"]
    gndY = gg(yg + 12.7)
    wire(xg, yg, xg, gndY)
    pwr("GND", xg, gndY)
    raw_sym("power", "PWR_FLAG", gg(xg - 22), gndY, "#FLG02", "PWR_FLAG", rot=0)
    wire(xg, gndY, gg(xg - 22), gndY)

    for ref, val, cx in [("C1", "10uF", gg(ux + 30)), ("C2", "100nF", gg(ux + 40))]:
        C = sym("Device", "C", cx, gg(railY + 10), ref, val)
        (_, tp), (_, bp) = two(C)
        wire(tp[0], tp[1], tp[0], railY)
        wire(bp[0], bp[1], bp[0], gg(bp[1] + 7.62))
        pwr("GND", bp[0], gg(bp[1] + 7.62))

    # support circuits below U1 — one x-column each, wired islands tapped by label
    baseY = 170.0
    R1 = sym("Device", "R", 150.0, baseY, "R1", "10k")
    (_, r1t), (_, r1b) = two(R1)
    wire(r1t[0], r1t[1], r1t[0], gg(r1t[1] - 7.62)); pwr("+3V3", r1t[0], gg(r1t[1] - 7.62))
    node = (r1b[0], gg(r1b[1] + 5.08)); wire(r1b[0], r1b[1], node[0], node[1])
    wire(node[0], node[1], gg(node[0] - 6.35), node[1])
    lbl("EN", gg(node[0] - 6.35), node[1], justify="right")
    C3 = sym("Device", "C", gg(150.0 + 13), gg(node[1] + 6), "C3", "100nF")
    (_, c3t), (_, c3b) = two(C3)
    wire(node[0], node[1], c3t[0], node[1]); wire(c3t[0], node[1], c3t[0], c3t[1])
    wire(c3b[0], c3b[1], c3b[0], gg(c3b[1] + 7.62)); pwr("GND", c3b[0], gg(c3b[1] + 7.62))
    SW1 = sym("Switch", "SW_Push", 150.0, gg(node[1] + 15), "SW1", "RESET", rot=90)
    (_, s1a), (_, s1b) = two(SW1)
    wire(node[0], node[1], s1a[0], s1a[1])
    wire(s1b[0], s1b[1], s1b[0], gg(s1b[1] + 7.62)); pwr("GND", s1b[0], gg(s1b[1] + 7.62))

    R2 = sym("Device", "R", 205.0, baseY, "R2", "10k")
    (_, r2t), (_, r2b) = two(R2)
    wire(r2t[0], r2t[1], r2t[0], gg(r2t[1] - 7.62)); pwr("+3V3", r2t[0], gg(r2t[1] - 7.62))
    bnode = (r2b[0], gg(r2b[1] + 5.08)); wire(r2b[0], r2b[1], bnode[0], bnode[1])
    wire(bnode[0], bnode[1], gg(bnode[0] - 6.35), bnode[1])
    lbl("IO9", gg(bnode[0] - 6.35), bnode[1], justify="right")
    SW2 = sym("Switch", "SW_Push", 205.0, gg(bnode[1] + 12), "SW2", "BOOT", rot=90)
    (_, s2a), (_, s2b) = two(SW2)
    wire(bnode[0], bnode[1], s2a[0], s2a[1])
    wire(s2b[0], s2b[1], s2b[0], gg(s2b[1] + 7.62)); pwr("GND", s2b[0], gg(s2b[1] + 7.62))

    R3 = sym("Device", "R", 258.0, baseY, "R3", "330")
    (_, r3t), (_, r3b) = two(R3)
    lbl("IO8", r3t[0], gg(r3t[1] - 7.62)); wire(r3t[0], gg(r3t[1] - 7.62), r3t[0], r3t[1])
    D1 = sym("Device", "LED", 258.0, gg(r3b[1] + 11), "D1", "LED", rot=270)
    da = D1["2"]; dk = D1["1"]
    wire(r3b[0], r3b[1], r3b[0], da[1]); wire(r3b[0], da[1], da[0], da[1])
    wire(dk[0], dk[1], dk[0], gg(dk[1] + 7.62)); pwr("GND", dk[0], gg(dk[1] + 7.62))


async def main() -> None:
    global _pins
    seed()
    from conftest import call_tool_text  # type: ignore

    from kicad_mcp.config import get_config
    from kicad_mcp.server import build_server
    from kicad_mcp.tools.schematic import get_pin_positions

    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(PROJECT)})
    get_config().symbol_library_dir = SYSLIB
    _pins = get_pin_positions

    build_plan()
    await call_tool_text(server, "sch_build_circuit", {
        "symbols": SYMS, "wires": WIRES, "labels": LABELS, "power_symbols": POWERS,
        "auto_layout": False, "snap_to_grid": True})
    await call_tool_text(server, "sch_set_title_block_info", {
        "title": "ESP32-C3-WROOM-02 Breakout", "rev": "A", "date": "2026-07-10",
        "company": "kicad-mcp-pro example gallery",
        "comment1": "Agent-generated wired reference schematic"})
    erc = await call_tool_text(server, "run_erc", {})
    print("ERC:", "PASS" if '"verdict": "PASS"' in erc else "FAIL\n" + erc)


if __name__ == "__main__":
    asyncio.run(main())
