"""Benchmarks for the lightweight KiCad S-expression parsers."""

from __future__ import annotations

import pytest

from kicad_mcp.models.contract_verifier import (
    extract_lib_symbol_block,
    find_symbol_instance,
    parse_footprint,
    parse_symbol_pins,
)
from kicad_mcp.utils.dru import dump_dru, parse_dru
from tests.synthetic import generate_resistor_grid


def _mcu_symbol(pin_count: int) -> str:
    pins = "\n".join(
        f"    (pin bidirectional line (at {-20.32 if i % 2 else 20.32} {i * 2.54} 0)"
        f' (length 2.54) (name "PA{i}" (effects (font (size 1.27 1.27))))'
        f' (number "{i + 1}" (effects (font (size 1.27 1.27)))))'
        for i in range(pin_count)
    )
    return f'(symbol "MCU:Generic_{pin_count}"\n  (symbol "Generic_1_1"\n{pins}\n  )\n)'


def _qfp_footprint(pad_count: int) -> str:
    pads = "\n".join(
        f'  (pad "{i + 1}" smd roundrect (at {i * 0.5} 0) (size 0.3 1.5)'
        f' (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.25))'
        for i in range(pad_count)
    )
    return (
        f'(footprint "Package_QFP:LQFP-{pad_count}"\n'
        '  (fp_line (start -5 -5) (end 5 -5) (layer "F.SilkS"))\n'
        '  (fp_line (start -6 -6) (end 6 -6) (layer "F.CrtYd"))\n'
        '  (fp_line (start -4 -4) (end 4 -4) (layer "F.Fab"))\n'
        f"{pads}\n"
        '  (model "${KICAD9_3DMODEL_DIR}/Package_QFP.3dshapes/LQFP.wrl")\n'
        ")"
    )


def _dru_rules(rule_count: int) -> str:
    rules = "\n".join(
        f'(rule "Net class {i} clearance"\n'
        f"  (condition \"A.NetClass == 'CLASS_{i}'\")\n"
        f"  (constraint clearance (min {0.1 + i * 0.01:.2f}mm))\n"
        f"  (constraint track_width (min 0.15mm) (opt 0.2mm) (max 1mm))\n"
        "  (severity warning))"
        for i in range(rule_count)
    )
    return f"(version 1)\n(rules\n{rules}\n)\n"


@pytest.fixture(scope="module")
def mcu_symbol() -> str:
    return _mcu_symbol(144)


@pytest.fixture(scope="module")
def qfp_footprint() -> str:
    return _qfp_footprint(144)


@pytest.fixture(scope="module")
def dru_text() -> str:
    return _dru_rules(100)


@pytest.fixture(scope="module")
def large_schematic() -> str:
    return generate_resistor_grid(200)


def test_parse_symbol_pins(benchmark, mcu_symbol: str) -> None:
    pins = benchmark(parse_symbol_pins, mcu_symbol)
    assert len(pins) == 144


def test_parse_footprint(benchmark, qfp_footprint: str) -> None:
    shape = benchmark(parse_footprint, qfp_footprint)
    assert len(shape.connectable_pads) == 144


def test_find_symbol_instance(benchmark, large_schematic: str) -> None:
    found = benchmark(find_symbol_instance, large_schematic, "R200")
    assert found is not None


def test_extract_lib_symbol_block(benchmark, large_schematic: str) -> None:
    block = benchmark(extract_lib_symbol_block, large_schematic, "Device:R")
    assert block


def test_parse_dru(benchmark, dru_text: str) -> None:
    root, version = benchmark(parse_dru, dru_text)
    assert version == "1"
    assert len(root) == 101


def test_dump_dru(benchmark, dru_text: str) -> None:
    root, version = parse_dru(dru_text)
    text = benchmark(dump_dru, root, version)
    assert "(rule" in text
