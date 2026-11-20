"""Regression: repeated schematic references denote distinct units, not one layout slot."""

from __future__ import annotations

from kicad_mcp.tools import schematic as sch


def _symbols() -> list[dict[str, object]]:
    return [
        {"lib_id": "Comparator:LM393", "reference": "U1", "unit": unit, "value": "LM393"}
        for unit in (1, 2, 3)
    ] + [{"lib_id": "Device:R", "reference": "R1", "value": "10k"}]


def _layout(symbols: list[dict[str, object]]):
    return sch._apply_netlist_auto_layout(
        symbols,
        [{"name": "+5V"}],
        [{"name": "SENSOR_IN"}],
        [
            {"name": "+5V", "connections": [{"reference": "U1", "pin": "8"}]},
            {
                "name": "SENSOR_IN",
                "connections": [{"reference": "U1", "pin": "3"}, {"reference": "R1", "pin": "1"}],
            },
        ],
        paper="A4",
        max_paper="A4",
    )


def _point(symbol: dict[str, object]) -> tuple[float, float]:
    return float(symbol["x_mm"]), float(symbol["y_mm"])


def test_auto_layout_allocates_one_slot_per_unit_not_per_reference() -> None:
    symbols, _, _, paper = _layout(_symbols())
    u1 = [symbol for symbol in symbols if symbol["reference"] == "U1"]

    assert paper == "A4"
    assert [symbol["unit"] for symbol in u1] == [1, 2, 3]
    assert len({_point(symbol) for symbol in u1}) == 3
    assert len({_point(symbol) for symbol in symbols}) == len(symbols)


def test_auto_layout_preserves_explicit_unit_and_avoids_its_slot() -> None:
    symbols = _symbols()
    symbols[1]["x_mm"] = 101.6
    symbols[1]["y_mm"] = 101.6
    laid_out, _, _, _ = _layout(symbols)

    assert _point(laid_out[1]) == (101.6, 101.6)
    assert len({_point(symbol) for symbol in laid_out}) == len(laid_out)


def test_repeated_reference_keeps_label_and_power_anchors() -> None:
    laid_out, powers, labels, _ = _layout(_symbols())
    assert len(laid_out) == 4
    assert len(powers) == 1
    assert len(labels) == 1
    assert "x_mm" in powers[0] and "y_mm" in powers[0]
    assert "x_mm" in labels[0] and "y_mm" in labels[0]
