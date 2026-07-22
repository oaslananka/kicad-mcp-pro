from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kicad_mcp.schematic.inspection import SchematicInspectionService


def _service(data: dict[str, Any] | None = None) -> SchematicInspectionService:
    schematic_data = data or {
        "symbols": [],
        "power_symbols": [],
        "wires": [],
        "labels": [],
    }
    return SchematicInspectionService(
        parse_schematic=lambda _path: schematic_data,
        with_diagnostics=lambda message, path: f"{message}\nDiagnostics: {path.name}",
        population_records=lambda reference, sheet: [],
        symbol_available_units=lambda _library, _symbol: set(),
        pin_positions_lookup=lambda _library, _symbol, _x, _y, _rotation, _unit: {},
    )


def test_symbols_preserves_legacy_order_and_formatting(tmp_path: Path) -> None:
    service = _service(
        {
            "symbols": [
                {
                    "reference": "R1",
                    "value": "10k",
                    "lib_id": "Device:R",
                    "x": 12.345,
                    "y": 67.891,
                    "rotation": 90,
                    "unit": 1,
                    "footprint": "Resistor_SMD:R_0603",
                },
                {
                    "reference": "C1",
                    "value": "100n",
                    "lib_id": "Device:C",
                    "x": 20.0,
                    "y": 30.0,
                    "rotation": 0,
                    "unit": 1,
                    "footprint": "",
                },
            ],
            "power_symbols": [
                {
                    "reference": "#PWR01",
                    "value": "GND",
                    "x": 5.0,
                    "y": 6.0,
                    "unit": 1,
                }
            ],
            "wires": [],
            "labels": [],
        }
    )

    assert service.symbols(tmp_path / "demo.kicad_sch") == (
        "Symbols (3 total):\n"
        "- R1 10k Device:R @ (12.35, 67.89) rot=90 unit=1 "
        "footprint=Resistor_SMD:R_0603\n"
        "- C1 100n Device:C @ (20.00, 30.00) rot=0 unit=1\n"
        "Power symbols:\n"
        "- #PWR01 GND @ (5.00, 6.00) unit=1"
    )


def test_empty_symbols_uses_existing_diagnostics(tmp_path: Path) -> None:
    path = tmp_path / "empty.kicad_sch"

    service = _service()
    assert service.symbols(path) == (
        "The active schematic contains no symbols.\nDiagnostics: empty.kicad_sch"
    )


def test_wires_labels_and_net_names_preserve_legacy_formatting(tmp_path: Path) -> None:
    path = tmp_path / "demo.kicad_sch"
    service = _service(
        {
            "symbols": [],
            "power_symbols": [],
            "wires": [
                {"uuid": "wire-1", "x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0},
                {"x1": 5.0, "y1": 6.0, "x2": 7.0, "y2": 8.0},
            ],
            "labels": [
                {"name": "SCL", "x": 10.0, "y": 11.0, "rotation": 0, "justify": "left"},
                {"name": "SDA", "x": 12.0, "y": 13.0, "rotation": 90, "justify": None},
                {"name": "SCL", "x": 14.0, "y": 15.0, "rotation": 0, "justify": None},
            ],
        }
    )

    assert service.wires(path) == (
        "Wires (2 total):\n- wire-1 (1.0, 2.0) -> (3.0, 4.0)\n- (5.0, 6.0) -> (7.0, 8.0)"
    )
    assert service.labels(path) == (
        "Labels (3 total):\n"
        "- SCL @ (10.0, 11.0) rot=0 justify=left\n"
        "- SDA @ (12.0, 13.0) rot=90 justify=center\n"
        "- SCL @ (14.0, 15.0) rot=0 justify=center"
    )
    assert service.net_names(path) == "Named nets:\n- SCL\n- SDA"


def test_population_status_preserves_json_and_missing_reference_error() -> None:
    records = [
        {
            "reference": "R1",
            "sheet": "root",
            "populated": False,
            "dnp": True,
            "in_bom": True,
            "reason": "prototype only",
        }
    ]
    service = SchematicInspectionService(
        parse_schematic=lambda _path: {},
        with_diagnostics=lambda message, _path: message,
        population_records=lambda reference, sheet: records if reference in {None, "R1"} else [],
        symbol_available_units=lambda _library, _symbol: set(),
        pin_positions_lookup=lambda _library, _symbol, _x, _y, _rotation, _unit: {},
    )

    assert json.loads(service.population_status(reference="R1", sheet="root")) == {
        "count": 1,
        "components": records,
    }
    with pytest.raises(ValueError, match="Reference 'R2' was not found in sheet 'root'"):
        service.population_status(reference="R2", sheet="root")


def test_pin_positions_preserves_unit_validation_and_sorted_output() -> None:
    service = SchematicInspectionService(
        parse_schematic=lambda _path: {},
        with_diagnostics=lambda message, _path: message,
        population_records=lambda _reference, _sheet: [],
        symbol_available_units=lambda _library, _symbol: {1, 2},
        pin_positions_lookup=lambda _library, _symbol, _x, _y, _rotation, _unit: {
            "2": (12.5, 20.0),
            "1": (10.0, 20.0),
        },
    )

    assert service.pin_positions("Amplifier_Operational", "LM358", 10.0, 20.0, 90, 3) == (
        "Amplifier_Operational:LM358 does not support unit 3. Available units: 1, 2."
    )
    assert service.pin_positions("Amplifier_Operational", "LM358", 10.0, 20.0, 90, 2) == (
        "Amplifier_Operational:LM358 @ (10.0, 20.0) rot=90 unit=2:\n"
        "- Pin 1: (10.0000, 20.0000) mm\n"
        "- Pin 2: (12.5000, 20.0000) mm"
    )


def test_power_flags_preserves_legacy_result(tmp_path: Path) -> None:
    path = tmp_path / "power.kicad_sch"
    service = _service(
        {
            "symbols": [],
            "power_symbols": [{"value": "GND"}, {"value": "+3V3"}],
            "wires": [],
            "labels": [
                {"name": "GND"},
                {"name": "+3V3"},
                {"name": "+5V"},
                {"name": "SIGNAL"},
            ],
        }
    )

    assert service.power_flags(path) == "Potential missing power flags:\n- +5V"
