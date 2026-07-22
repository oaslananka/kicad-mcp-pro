"""Deterministic, FastMCP-free schematic inspection behavior."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

type SchematicData = Mapping[str, Any]
type ParseSchematic = Callable[[Path], SchematicData]
type WithDiagnostics = Callable[[str, Path], str]
type PopulationRecords = Callable[[str | None, str | None], list[dict[str, Any]]]
type SymbolAvailableUnits = Callable[[str, str], set[int]]
type PinPositions = Callable[[str, str, float, float, int, int], dict[str, tuple[float, float]]]


@dataclass(frozen=True)
class SchematicInspectionService:
    """Format read-only schematic inspection results from injected dependencies."""

    parse_schematic: ParseSchematic
    with_diagnostics: WithDiagnostics
    population_records: PopulationRecords
    symbol_available_units: SymbolAvailableUnits
    pin_positions_lookup: PinPositions

    def symbols(self, schematic_file: Path) -> str:
        """Return the legacy public symbol listing for ``schematic_file``."""
        data = self.parse_schematic(schematic_file)
        symbols = [*data["symbols"], *data["power_symbols"]]
        if not symbols:
            return self.with_diagnostics(
                "The active schematic contains no symbols.",
                schematic_file,
            )

        lines = [f"Symbols ({len(symbols)} total):"]
        for symbol in data["symbols"]:
            suffix = f" footprint={symbol['footprint']}" if symbol["footprint"] else ""
            lines.append(
                f"- {symbol['reference']} {symbol['value']} {symbol['lib_id']} @ "
                f"({symbol['x']:.2f}, {symbol['y']:.2f}) rot={symbol['rotation']} "
                f"unit={symbol['unit']}{suffix}"
            )
        if data["power_symbols"]:
            lines.append("Power symbols:")
            for symbol in data["power_symbols"]:
                lines.append(
                    f"- {symbol['reference']} {symbol['value']} @ "
                    f"({symbol['x']:.2f}, {symbol['y']:.2f}) unit={symbol['unit']}"
                )
        return "\n".join(lines)

    def wires(self, schematic_file: Path) -> str:
        """Return the legacy public wire listing for ``schematic_file``."""
        wires = self.parse_schematic(schematic_file)["wires"]
        if not wires:
            return self.with_diagnostics(
                "The active schematic contains no wires.",
                schematic_file,
            )
        lines = [f"Wires ({len(wires)} total):"]
        for wire in wires:
            identifier = f"{wire['uuid']} " if wire.get("uuid") else ""
            lines.append(
                f"- {identifier}({wire['x1']}, {wire['y1']}) -> ({wire['x2']}, {wire['y2']})"
            )
        return "\n".join(lines)

    def labels(self, schematic_file: Path) -> str:
        """Return the legacy public label listing for ``schematic_file``."""
        labels = self.parse_schematic(schematic_file)["labels"]
        if not labels:
            return self.with_diagnostics(
                "The active schematic contains no labels.",
                schematic_file,
            )
        lines = [f"Labels ({len(labels)} total):"]
        lines.extend(
            f"- {label['name']} @ ({label['x']}, {label['y']}) "
            f"rot={label['rotation']} justify={label.get('justify') or 'center'}"
            for label in labels
        )
        return "\n".join(lines)

    def net_names(self, schematic_file: Path) -> str:
        """Return unique named nets using the legacy public format."""
        labels = self.parse_schematic(schematic_file)["labels"]
        names = sorted({label["name"] for label in labels})
        if not names:
            return self.with_diagnostics(
                "No named nets were found in the schematic.",
                schematic_file,
            )
        return "Named nets:\n" + "\n".join(f"- {name}" for name in names)

    def population_status(
        self,
        reference: str | None = None,
        sheet: str | None = None,
    ) -> str:
        """Return native Populate/DNP records using the legacy JSON shape."""
        records = self.population_records(reference, sheet)
        if reference and not records:
            scope = f" in sheet '{sheet}'" if sheet else ""
            raise ValueError(f"Reference '{reference}' was not found{scope}.")
        return json.dumps({"count": len(records), "components": records}, indent=2)

    def pin_positions(
        self,
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        rotation: int = 0,
        unit: int = 1,
    ) -> str:
        """Return absolute symbol pin positions using the legacy public format."""
        available_units = self.symbol_available_units(library, symbol_name)
        if available_units and unit not in available_units:
            units = ", ".join(str(value) for value in sorted(available_units))
            return (
                f"{library}:{symbol_name} does not support unit {unit}. Available units: {units}."
            )

        positions = self.pin_positions_lookup(
            library,
            symbol_name,
            x_mm,
            y_mm,
            rotation,
            unit,
        )
        if not positions:
            return f"Could not calculate pin positions for {library}:{symbol_name}."
        lines = [f"{library}:{symbol_name} @ ({x_mm}, {y_mm}) rot={rotation} unit={unit}:"]
        for pin, coordinates in sorted(positions.items()):
            lines.append(f"- Pin {pin}: ({coordinates[0]:.4f}, {coordinates[1]:.4f}) mm")
        return "\n".join(lines)

    def power_flags(self, schematic_file: Path) -> str:
        """Return the legacy missing-power-flag advisory."""
        data = self.parse_schematic(schematic_file)
        named_power = {
            label["name"]
            for label in data["labels"]
            if label["name"].upper() in {"GND", "VCC", "+3V3", "+5V", "+12V"}
        }
        power_symbols = {symbol["value"].upper() for symbol in data["power_symbols"]}
        missing = sorted(name for name in named_power if name.upper() not in power_symbols)
        if not missing:
            return self.with_diagnostics(
                "No obvious missing power flags were detected.",
                schematic_file,
            )
        return "Potential missing power flags:\n" + "\n".join(f"- {name}" for name in missing)
