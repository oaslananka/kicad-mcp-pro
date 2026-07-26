"""FastMCP-independent schematic lifecycle authoring orchestration."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from ..models.schematic import AnnotateInput

AnnotationOrder = Literal["alpha", "sheet", "existing", "left_to_right"]
Mutator = Callable[[str], str]


@dataclass(frozen=True)
class SchematicLifecycleAuthoringService:
    """Coordinate jumper placement, reference annotation, and reload behavior."""

    snap_point: Callable[[float, float, bool], tuple[float, float]]
    snap_notice: Callable[[tuple[float, float], tuple[float, float]], str]
    next_reference: Callable[[str], str]
    place_symbol_block: Callable[..., str]
    append_before_sheet_instances: Callable[[str, str], str]
    transactional_write: Callable[[Mutator], str]
    reload_schematic: Callable[[], str]
    active_schematic_file: Callable[[], Path]
    parse_schematic: Callable[[Path], dict[str, Any]]
    sort_symbols_for_annotation: Callable[[list[dict[str, Any]], str], None]

    def add_jumper(
        self,
        x_mm: float,
        y_mm: float,
        pins: int = 2,
        open_by_default: bool = True,
        snap_to_grid: bool = True,
    ) -> str:
        """Add a snapped two- or three-pin jumper and reload the schematic."""
        if pins < 2 or pins > 3:
            raise ValueError("Only 2-pin and 3-pin jumpers are supported.")
        target_x, target_y = self.snap_point(x_mm, y_mm, snap_to_grid)
        snap_note = self.snap_notice((x_mm, y_mm), (target_x, target_y))
        reference = self.next_reference("JP")
        value = f"Jumper_{pins}_{'Open' if open_by_default else 'Closed'}"
        lib_id = f"Jumper:{value}"
        self.transactional_write(
            lambda current: self.append_before_sheet_instances(
                current,
                self.place_symbol_block(
                    lib_id=lib_id,
                    x=target_x,
                    y=target_y,
                    reference=reference,
                    value=value,
                ),
            )
        )
        result = self.reload_schematic()
        detail = f"Added jumper '{reference}' ({value}) at ({target_x:.2f}, {target_y:.2f}) mm."
        return f"{detail}\n{result}\n{snap_note}" if snap_note else f"{detail}\n{result}"

    def annotate(self, start_number: int = 1, order: str = "alpha") -> str:
        """Renumber schematic references sequentially."""
        payload = AnnotateInput(start_number=start_number, order=cast(AnnotationOrder, order))
        data = self.parse_schematic(self.active_schematic_file())
        symbols = list(data["symbols"])
        self.sort_symbols_for_annotation(symbols, payload.order)

        counters: dict[str, int] = {}
        updates: list[tuple[str, str]] = []
        for symbol in symbols:
            prefix_match = re.match(r"([A-Za-z#]+)", symbol["reference"])
            prefix = prefix_match.group(1) if prefix_match else "U"
            counters.setdefault(prefix, payload.start_number)
            new_reference = f"{prefix}{counters[prefix]}"
            counters[prefix] += 1
            updates.append((symbol["reference"], new_reference))

        def mutator(current: str) -> str:
            updated = current
            for old_reference, new_reference in updates:
                updated = updated.replace(
                    f'(property "Reference" "{old_reference}"',
                    f'(property "Reference" "{new_reference}"',
                    1,
                )
            return updated

        self.transactional_write(mutator)
        return f"Annotated {len(updates)} symbol(s).\n{self.reload_schematic()}"

    def reload(self) -> str:
        """Reload the active schematic through the injected runtime helper."""
        return self.reload_schematic()
