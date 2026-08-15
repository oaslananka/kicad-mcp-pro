"""FastMCP-independent schematic connectivity authoring orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..models.schematic import RouteWireBetweenPinsInput


class SchematicTargetLike(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def description(self) -> str: ...


class LabelBlockEmitter(Protocol):
    def __call__(
        self,
        name: str,
        x: float,
        y: float,
        rotation: int = 0,
        global_label: bool = False,
        shape: str | None = None,
        kind: str | None = None,
        justify: str | None = None,
    ) -> str: ...


class BoundingBoxLike(Protocol):
    """Obstacle bounds consumed by the injected router."""

    @property
    def x_min(self) -> float: ...

    @property
    def y_min(self) -> float: ...

    @property
    def x_max(self) -> float: ...

    @property
    def y_max(self) -> float: ...


ParsedSchematic = dict[str, Any]
Mutator = Callable[[str], str]
PinPositions = dict[str, tuple[float, float]]
WireSegment = tuple[float, float, float, float]

#: Maps the public ``label_kind`` values to the ``kind`` accepted by ``label_block``.
LABEL_SHAPES = frozenset({"input", "output", "bidirectional", "tri_state", "passive"})

LABEL_KIND_TO_BLOCK_KIND: dict[str, str] = {
    "local": "label",
    "global": "global_label",
    "hierarchical": "hierarchical_label",
}


@dataclass(frozen=True)
class SchematicConnectivityAuthoringService:
    """Author and repair schematic connectivity without depending on FastMCP."""

    resolve_target: Callable[[str | None, str | None], SchematicTargetLike]
    parse_schematic: Callable[[Path], ParsedSchematic]
    project_name: Callable[[], str]
    new_uuid: Callable[[], str]
    get_pin_positions: Callable[[str, str, float, float, int, int], PinPositions]
    get_pin_alias_positions: Callable[[str, str, float, float, int, int], PinPositions]
    pin_label_stub_direction: Callable[
        [tuple[float, float], tuple[float, float], Iterable[tuple[float, float]]],
        tuple[float, float],
    ]
    is_origin_pin_power_symbol: Callable[[str, str], bool]
    is_power_net: Callable[[str], bool]
    load_lib_symbol: Callable[[str, str], str | None]
    wire_block: Callable[[float, float, float, float], str]
    power_symbol_rotation_from_vector: Callable[[float, float], int]
    place_symbol_block: Callable[..., str]
    terminal_rotation_from_vector: Callable[[float, float], int]
    label_block: LabelBlockEmitter
    append_before_sheet_instances: Callable[[str, str], str]
    transactional_write: Callable[[Mutator, Path | None], str]
    reload_schematic: Callable[[], str]
    format_target_detail: Callable[[SchematicTargetLike], str]
    active_schematic_file: Callable[[], Path]
    split_lib_id: Callable[[str], tuple[str, str]]
    get_symbol_bboxes: Callable[[str], list[BoundingBoxLike]]
    route_avoiding_obstacles: Callable[
        [
            tuple[float, float],
            tuple[float, float],
            list[BoundingBoxLike],
            bool,
        ],
        tuple[list[WireSegment], str | None],
    ]
    run_auto_add_missing_junctions: Callable[[], str]
    snap_tolerance_mm: float

    def add_pin_labels(
        self,
        connections: list[dict[str, Any]],
        stub_mm: float = 5.08,
        global_labels: bool = True,
        sheet: str | None = None,
        sheet_file: str | None = None,
        label_kind: str | None = None,
    ) -> str:
        """Add outward pin stubs plus labels or power terminals.

        ``label_kind`` (``"local"`` | ``"global"`` | ``"hierarchical"``) selects the
        emitted label type and, when provided, takes precedence over the legacy
        ``global_labels`` boolean. Hierarchical connections may carry an optional
        per-connection ``"shape"`` (``input``/``output``/``bidirectional``/...).
        """
        if label_kind is not None and label_kind not in LABEL_KIND_TO_BLOCK_KIND:
            raise ValueError(
                f"label_kind must be one of {sorted(LABEL_KIND_TO_BLOCK_KIND)}, got {label_kind!r}"
            )
        block_kind = (
            LABEL_KIND_TO_BLOCK_KIND[label_kind]
            if label_kind is not None
            else ("global_label" if global_labels else "label")
        )
        target = self.resolve_target(sheet, sheet_file)
        data = self.parse_schematic(target.path)
        # A reference may map to several placed blocks (multi-unit symbols share a
        # reference across their units), so track every block per reference and
        # resolve pins across all of them instead of only the last one placed.
        placed: dict[str, list[dict[str, Any]]] = {}
        placed_kind: dict[str, str] = {}
        for sym in data.get("symbols", []):
            ref = str(sym.get("reference", ""))
            if ref:
                placed.setdefault(ref, []).append(sym)
                placed_kind[ref] = "symbol"
        for sym in data.get("power_symbols", []):
            ref = str(sym.get("reference", ""))
            if ref:
                placed.setdefault(ref, []).append(sym)
                placed_kind[ref] = "power_symbol"

        project_name = self.project_name()
        root_uuid = str(data.get("uuid") or self.new_uuid())
        wire_blocks: list[str] = []
        terminal_blocks: list[str] = []
        power_lib_defs: dict[str, str] = {}
        occupied_terminals: list[tuple[float, float]] = []
        #: Terminals already emitted for a resolved (pin coordinate, net) pair. Stacked
        #: pins (several named pins drawn at one coordinate, e.g. the paired GND/VBUS
        #: pins of a USB-C receptacle) share this key so they reuse the single stub
        #: instead of being staggered into orphaned symbols.
        stacked_terminals: dict[tuple[float, float, str], tuple[float, float]] = {}
        dense_terminal_mode = len(connections) >= 12
        terminal_clearance_mm = self.snap_tolerance_mm if dense_terminal_mode else 6.0
        stagger_step_mm = 2.54
        max_stagger_steps = 12 if dense_terminal_mode else 5
        results: list[str] = []
        if dense_terminal_mode:
            results.append(
                "dense terminal mode: preserving each pin's natural row/column; "
                "only exact terminal-coordinate collisions are staggered"
            )

        for conn in connections:
            ref = str(conn.get("reference", ""))
            pin = str(conn.get("pin", ""))
            net = str(conn.get("net", conn.get("name", "")))
            if not (ref and pin and net):
                results.append(f"SKIP {conn}: needs reference, pin, net")
                continue
            blocks = placed.get(ref)
            if not blocks:
                results.append(f"{ref}.{pin}: reference not found")
                continue
            # An explicit ``unit`` in the connection disambiguates when two units
            # of the same reference expose an identically named pin.
            wanted_unit = conn.get("unit")
            candidates = blocks
            if wanted_unit is not None:
                try:
                    wanted_unit_number = int(wanted_unit)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"unit must be an integer, got {wanted_unit!r}") from exc
                candidates = [
                    block
                    for block in blocks
                    if int(block.get("unit", 1) or 1) == wanted_unit_number
                ]
                if not candidates:
                    results.append(f"{ref}.{pin}: unit {wanted_unit} not found")
                    continue
            is_power_symbol_ref = placed_kind.get(ref) == "power_symbol"

            # Resolve ``pin`` across every placed block sharing this reference so
            # multi-unit symbols work regardless of which unit was placed last.
            sym = candidates[0]
            point: tuple[float, float] | None = None
            pin_positions: PinPositions = {}
            library = ""
            symbol_name = ""
            is_power_symbol = False
            unresolved_lib_id: str | None = None
            for block in candidates:
                lib_id = str(block.get("lib_id", ""))
                if ":" not in lib_id:
                    unresolved_lib_id = lib_id
                    continue
                block_library, block_symbol_name = lib_id.split(":", 1)
                block_ox = float(block.get("x", 0.0))
                block_oy = float(block.get("y", 0.0))
                block_rot = int(block.get("rotation", 0) or 0)
                block_unit = int(block.get("unit", 1) or 1)
                block_positions = self.get_pin_positions(
                    block_library, block_symbol_name, block_ox, block_oy, block_rot, block_unit
                )
                candidate_point = block_positions.get(pin)
                if candidate_point is None:
                    aliases = self.get_pin_alias_positions(
                        block_library,
                        block_symbol_name,
                        block_ox,
                        block_oy,
                        block_rot,
                        block_unit,
                    )
                    candidate_point = aliases.get(pin) or aliases.get(pin.upper())
                if candidate_point is not None:
                    sym = block
                    point = candidate_point
                    pin_positions = block_positions
                    library = block_library
                    symbol_name = block_symbol_name
                    is_power_symbol = block_library == "power" or ref.startswith("#PWR")
                    break

            if point is None:
                # No block resolved the pin: fall back to the first block's geometry
                # for the power-symbol / lib_id error paths preserved below.
                lib_id = str(sym.get("lib_id", ""))
                if ":" not in lib_id:
                    results.append(
                        f"{ref}.{pin}: symbol type not supported: "
                        f"unresolved lib_id '{unresolved_lib_id or lib_id}'"
                    )
                    continue
                library, symbol_name = lib_id.split(":", 1)
                is_power_symbol = library == "power" or ref.startswith("#PWR")

            ox = float(sym.get("x", 0.0))
            oy = float(sym.get("y", 0.0))
            if point is None and is_power_symbol_ref:
                if pin != "1":
                    results.append(f"{ref}.{pin}: symbol type not supported for pin '{pin}'")
                    continue
                point = (ox, oy)
                pin_positions = {"1": point}
            if point is None:
                if (
                    is_power_symbol
                    and pin == "1"
                    and self.is_origin_pin_power_symbol(
                        symbol_name,
                        str(sym.get("value", "")),
                    )
                ):
                    point = (round(ox, 4), round(oy, 4))
                    pin_positions = {"1": point}
                elif is_power_symbol and not pin_positions:
                    results.append(
                        f"{ref}.{pin}: symbol type not supported: "
                        f"{sym.get('lib_id', '')} has no resolvable pin geometry"
                    )
                    continue
                else:
                    results.append(f"{ref}.{pin}: pin not found")
                    continue
            px, py = point
            stack_key = (round(px, 4), round(py, 4), net)
            shared_terminal = stacked_terminals.get(stack_key)
            if shared_terminal is not None:
                sx, sy = shared_terminal
                results.append(f"{ref}.{pin} -> {net} (stacked on shared terminal @ ({sx}, {sy}))")
                continue
            ux, uy = self.pin_label_stub_direction(point, (ox, oy), pin_positions.values())
            length = max(stub_mm, 10.16) if uy else stub_mm
            ex = round(px + ux * length, 4)
            ey = round(py + uy * length, 4)
            stagger_steps = 0
            while stagger_steps < max_stagger_steps and any(
                abs(ex - qx) < terminal_clearance_mm and abs(ey - qy) < terminal_clearance_mm
                for qx, qy in occupied_terminals
            ):
                length += stagger_step_mm
                ex = round(px + ux * length, 4)
                ey = round(py + uy * length, 4)
                stagger_steps += 1
            occupied_terminals.append((ex, ey))
            wire_blocks.append(self.wire_block(px, py, ex, ey))
            suffix = f"; staggered {stagger_steps} step(s)" if stagger_steps else ""

            if self.is_power_net(net):
                if net not in power_lib_defs:
                    lib_def = self.load_lib_symbol("power", net)
                    if lib_def is None:
                        results.append(f"{ref}.{pin}: power symbol '{net}' was not found")
                        wire_blocks.pop()
                        occupied_terminals.pop()
                        continue
                    power_lib_defs[net] = lib_def
                terminal_blocks.append(
                    self.place_symbol_block(
                        lib_id=f"power:{net}",
                        x=ex,
                        y=ey,
                        reference=f"#PWR{self.new_uuid()[:4]}",
                        value=net,
                        rotation=self.power_symbol_rotation_from_vector(ux, uy),
                        project_name=project_name,
                        root_uuid=root_uuid,
                    )
                )
                stacked_terminals[stack_key] = (ex, ey)
                results.append(f"{ref}.{pin} -> {net} (power) @ ({ex}, {ey}){suffix}")
            else:
                rotation = self.terminal_rotation_from_vector(ux, uy)
                shape = conn.get("shape")
                if shape is not None and (not isinstance(shape, str) or shape not in LABEL_SHAPES):
                    raise ValueError(f"shape must be one of {sorted(LABEL_SHAPES)}, got {shape!r}")
                terminal_blocks.append(
                    self.label_block(
                        net,
                        ex,
                        ey,
                        rotation,
                        kind=block_kind,
                        shape=shape,
                    )
                )
                stacked_terminals[stack_key] = (ex, ey)
                results.append(f"{ref}.{pin} -> {net} @ ({ex}, {ey}){suffix}")

        if not (wire_blocks or terminal_blocks):
            return "No pin labels were added.\n" + "\n".join(results)

        def mutator(current: str) -> str:
            updated = current
            for net_name, lib_def in power_lib_defs.items():
                lib_id = f"power:{net_name}"
                if f'(symbol "{lib_id}"' in updated:
                    continue
                if "(lib_symbols)" in updated:
                    updated = updated.replace(
                        "(lib_symbols)",
                        f"(lib_symbols\n\t{lib_def}\n\t)",
                        1,
                    )
                else:
                    updated = updated.replace(
                        "\t(lib_symbols\n",
                        f"\t(lib_symbols\n\t{lib_def}\n",
                        1,
                    )
            for block in (*wire_blocks, *terminal_blocks):
                updated = self.append_before_sheet_instances(updated, block)
            return updated

        self.transactional_write(mutator, target.path)
        return (
            f"{self.reload_schematic()}\n{self.format_target_detail(target)}\n"
            f"Added {len(wire_blocks)} pin terminal(s) with stubs:\n" + "\n".join(results)
        )

    def route_wire_between_pins(
        self,
        ref1: str,
        pin1: str,
        ref2: str,
        pin2: str,
        snap_to_grid: bool = True,
    ) -> str:
        """Route deterministic Manhattan segments between two symbol pins."""
        payload = RouteWireBetweenPinsInput(
            ref1=ref1,
            pin1=pin1,
            ref2=ref2,
            pin2=pin2,
            snap_to_grid=snap_to_grid,
        )
        data = self.parse_schematic(self.active_schematic_file())
        symbols = {symbol["reference"]: symbol for symbol in data["symbols"]}
        first = symbols.get(payload.ref1)
        second = symbols.get(payload.ref2)
        if first is None:
            return f"Reference '{payload.ref1}' was not found in the schematic."
        if second is None:
            return f"Reference '{payload.ref2}' was not found in the schematic."

        first_library, first_symbol = self.split_lib_id(str(first["lib_id"]))
        second_library, second_symbol = self.split_lib_id(str(second["lib_id"]))
        first_pins = self.get_pin_positions(
            first_library,
            first_symbol,
            float(first["x"]),
            float(first["y"]),
            int(first["rotation"]),
            int(first["unit"]),
        )
        second_pins = self.get_pin_positions(
            second_library,
            second_symbol,
            float(second["x"]),
            float(second["y"]),
            int(second["rotation"]),
            int(second["unit"]),
        )
        start = first_pins.get(payload.pin1)
        end = second_pins.get(payload.pin2)
        if start is None:
            return f"Pin {payload.pin1} was not found on {payload.ref1}."
        if end is None:
            return f"Pin {payload.pin2} was not found on {payload.ref2}."

        content = self.active_schematic_file().read_text(encoding="utf-8", errors="ignore")
        obstacles = self.get_symbol_bboxes(content)
        segments, routing_warning = self.route_avoiding_obstacles(
            start,
            end,
            obstacles,
            payload.snap_to_grid,
        )
        if not segments:
            return (
                f"{payload.ref1}:{payload.pin1} and {payload.ref2}:{payload.pin2} already overlap."
            )

        def mutator(current: str) -> str:
            updated = current
            for segment in segments:
                updated = self.append_before_sheet_instances(
                    updated,
                    self.wire_block(*segment),
                )
            return updated

        self.transactional_write(mutator, None)
        result = self.reload_schematic()
        return (
            f"{result}\nRouted {len(segments)} wire segment(s) between "
            f"{payload.ref1}:{payload.pin1} and {payload.ref2}:{payload.pin2}."
            + (f"\n{routing_warning}" if routing_warning else "")
        )

    def add_missing_junctions(self) -> str:
        """Repair T-intersection junctions and reload the active schematic."""
        summary = self.run_auto_add_missing_junctions()
        result = self.reload_schematic()
        return f"{result}\n{summary}"
