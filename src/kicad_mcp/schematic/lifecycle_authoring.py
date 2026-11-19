"""FastMCP-independent schematic lifecycle authoring orchestration."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from ..models.schematic import AnnotateInput
from .instance_paths import (
    InstancePathFor,
    instance_path_kwargs,
    no_instance_path,
    rewrite_placed_symbol_references,
)

AnnotationOrder = Literal["alpha", "sheet", "existing", "left_to_right"]
Mutator = Callable[[str], str]


def _allocate_project_symbol_reference(
    symbol: dict[str, Any],
    counters: dict[str, int],
    groups: dict[tuple[str, str], list[tuple[str, set[int]]]],
    start_number: int,
) -> str:
    """Reuse a reference for distinct units while separating same-unit parts."""
    old = str(symbol["reference"])
    prefix_match = re.match(r"([A-Za-z]+)", old)
    prefix = prefix_match.group(1) if prefix_match else "U"
    key = (old, str(symbol.get("lib_id", "")))
    try:
        unit = int(symbol.get("unit", 1))
    except (TypeError, ValueError):
        unit = 1
    matches = groups.setdefault(key, [])
    group = next((item for item in matches if unit not in item[1]), None)
    if group is not None:
        new_reference, used_units = group
        used_units.add(unit)
        return new_reference
    counters.setdefault(prefix, start_number)
    new_reference = f"{prefix}{counters[prefix]}"
    counters[prefix] += 1
    matches.append((new_reference, {unit}))
    return new_reference


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
    instance_path_for: InstancePathFor = no_instance_path
    project_name: Callable[[], str] = lambda: ""
    project_schematic_files: Callable[[], list[Path]] | None = None
    write_project_annotation: Callable[[dict[Path, list[tuple[str, str]]]], None] | None = None

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
        instance_path = self.instance_path_for(self.active_schematic_file()) or ""
        self.transactional_write(
            lambda current: self.append_before_sheet_instances(
                current,
                self.place_symbol_block(
                    lib_id=lib_id,
                    x=target_x,
                    y=target_y,
                    reference=reference,
                    value=value,
                    **instance_path_kwargs(instance_path),
                ),
            )
        )
        result = self.reload_schematic()
        detail = f"Added jumper '{reference}' ({value}) at ({target_x:.2f}, {target_y:.2f}) mm."
        return f"{detail}\n{result}\n{snap_note}" if snap_note else f"{detail}\n{result}"

    def annotate(self, start_number: int = 1, order: str = "alpha") -> str:
        """Renumber schematic references sequentially."""
        payload = AnnotateInput(start_number=start_number, order=cast(AnnotationOrder, order))
        if self.project_schematic_files is not None and self.write_project_annotation is not None:
            return self._annotate_project(payload)
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
            return rewrite_placed_symbol_references(current, updates, self.project_name())

        self.transactional_write(mutator)
        return f"Annotated {len(updates)} symbol(s).\n{self.reload_schematic()}"

    def _annotate_project(self, payload: AnnotateInput) -> str:
        """Allocate references across real sheets before writing any of them."""
        files = self.project_schematic_files
        write = self.write_project_annotation
        if files is None or write is None:
            raise RuntimeError("Project annotation dependencies are unavailable.")
        counters: dict[str, int] = {}
        # A multi-unit component may be split across sheets. Distinct unit
        # numbers with the same existing ref and library ID share one new ref;
        # duplicate unit numbers indicate separate parts and get distinct refs.
        groups: dict[tuple[str, str], list[tuple[str, set[int]]]] = {}
        updates_by_file: dict[Path, list[tuple[str, str]]] = {}
        count = 0
        for file in files():
            symbols = list(self.parse_schematic(file)["symbols"])
            self.sort_symbols_for_annotation(symbols, payload.order)
            updates: list[tuple[str, str]] = []
            for symbol in symbols:
                old = str(symbol["reference"])
                if not old or old.startswith("#"):
                    continue
                new_reference = _allocate_project_symbol_reference(
                    symbol, counters, groups, payload.start_number
                )
                updates.append((old, new_reference))
                count += 1
            if updates:
                updates_by_file[file] = updates
        write(updates_by_file)
        summary = f"Annotated {count} symbol(s)."
        if len(updates_by_file) > 1:
            summary += f" Covered {len(updates_by_file)} schematic sheets."
        return f"{summary}\n{self.reload_schematic()}"

    def reload(self) -> str:
        """Reload the active schematic through the injected runtime helper."""
        return self.reload_schematic()
