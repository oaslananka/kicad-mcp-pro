"""FastMCP-free orchestration for schematic settings and swap intents."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

type ProjectFile = Callable[[], Path | None]
type SymbolByReference = Callable[[str], Mapping[str, Any]]
type SplitLibId = Callable[[str], tuple[str, str]]
type PinAliasPositions = Callable[
    [str, str, float, float, int, int],
    Mapping[str, tuple[float, float]],
]
type SymbolLibraryFile = Callable[[str], Path | None]
type CollectSymbolBlocks = Callable[[str, str], list[str]]
type AvailableUnitsFromBlocks = Callable[[list[str]], set[int]]
type LoadState = Callable[[str, dict[str, Any]], dict[str, Any]]
type SaveState = Callable[[str, dict[str, Any]], Path]


@dataclass(frozen=True)
class SchematicBackAnnotationService:
    """Manage schematic project settings and deferred swap intents."""

    project_file: ProjectFile
    symbol_by_reference: SymbolByReference
    split_lib_id: SplitLibId
    pin_alias_positions: PinAliasPositions
    symbol_library_file: SymbolLibraryFile
    collect_symbol_blocks: CollectSymbolBlocks
    available_units_from_blocks: AvailableUnitsFromBlocks
    load_state: LoadState
    save_state: SaveState

    def set_hop_over(self, enabled: bool = True) -> str:
        """Toggle KiCad 10 hop-over display in the active project settings."""
        project_file = self.project_file()
        if project_file is None or not project_file.exists():
            raise ValueError(
                "No project file is configured. Call kicad_set_project() before changing "
                "schematic display settings."
            )
        try:
            raw_project_payload = json.loads(project_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Project file '{project_file}' does not contain valid JSON.") from exc
        if not isinstance(raw_project_payload, dict):
            raise ValueError("The active project file must contain a JSON object.")
        project_payload = cast(dict[str, object], raw_project_payload)

        schematic_settings = cast(
            dict[str, object],
            project_payload.setdefault("schematic", {}),
        )
        schematic_settings["hop_over_display"] = bool(enabled)
        project_file.write_text(json.dumps(project_payload, indent=2), encoding="utf-8")
        state = "enabled" if enabled else "disabled"
        return f"Hop-over display set to {state} in {project_file}."

    def _swappable_payload(self, component_ref: str) -> dict[str, object]:
        symbol = self.symbol_by_reference(component_ref)
        library, symbol_name = self.split_lib_id(str(symbol.get("lib_id", "")))
        aliases = self.pin_alias_positions(
            library,
            symbol_name,
            float(symbol.get("x", 0.0)),
            float(symbol.get("y", 0.0)),
            int(symbol.get("rotation", 0)),
            int(symbol.get("unit", 1)),
        )
        pins = sorted(
            {alias for alias in aliases if alias and alias.isdigit()},
            key=int,
        )

        units: list[int] = []
        symbol_file = self.symbol_library_file(library)
        if symbol_file is not None:
            content = symbol_file.read_text(encoding="utf-8", errors="ignore")
            blocks = self.collect_symbol_blocks(content, symbol_name)
            units = sorted(self.available_units_from_blocks(blocks))

        return {
            "reference": component_ref,
            "pins": pins,
            "gates": units,
            "note": "Recorded swaps are stored as back-annotation intents in .kicad-mcp.",
        }

    def list_swappable_pins(self, component_ref: str) -> str:
        """List candidate pins and units that can participate in a swap workflow."""
        return json.dumps(self._swappable_payload(component_ref), indent=2)

    def swap_pins(self, component_ref: str, pin_a: str, pin_b: str) -> str:
        """Record a pin-swap back-annotation intent for a component."""
        payload = self._swappable_payload(component_ref)
        pins = cast(list[str], payload.get("pins", []))
        if pin_a not in pins or pin_b not in pins:
            return (
                f"Pins '{pin_a}' and/or '{pin_b}' are not swappable candidates "
                f"for '{component_ref}'."
            )

        state = self.load_state("pin_swaps.json", {"swaps": []})
        swaps = cast(list[dict[str, str]], state.setdefault("swaps", []))
        swaps.append(
            {
                "reference": component_ref,
                "pin_a": pin_a,
                "pin_b": pin_b,
            }
        )
        path = self.save_state("pin_swaps.json", state)
        return f"Recorded pin swap {component_ref}:{pin_a}<->{pin_b} in {path}."

    def swap_gates(self, component_ref: str, gate_a: int, gate_b: int) -> str:
        """Record a gate-swap back-annotation intent for a multi-unit component."""
        payload = self._swappable_payload(component_ref)
        gates = cast(list[int], payload.get("gates", []))
        if gate_a not in gates or gate_b not in gates:
            return f"Gates '{gate_a}' and/or '{gate_b}' are not available on '{component_ref}'."

        state = self.load_state("gate_swaps.json", {"swaps": []})
        swaps = cast(list[dict[str, object]], state.setdefault("swaps", []))
        swaps.append(
            {
                "reference": component_ref,
                "gate_a": gate_a,
                "gate_b": gate_b,
            }
        )
        path = self.save_state("gate_swaps.json", state)
        return f"Recorded gate swap {component_ref}:{gate_a}<->{gate_b} in {path}."
