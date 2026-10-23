"""FastMCP-independent schematic connectivity authoring orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..errors import SchematicRoutingUnsafeError
from ..models.schematic import RouteWireBetweenPinsInput
from ..utils.schematic_router import point_on_segment, segments_merge
from .references import power_reference_from_uuid


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


def _no_module_boundaries(_content: str) -> list[BoundingBoxLike]:
    """No drawn boundaries to clear -- the default for callers predating the rule."""
    return []


def _wire_network_at_pin(point: tuple[float, float], data: ParsedSchematic) -> list[WireSegment]:
    """Reach all KiCad-joined wire segments, but not bare crossovers."""
    segments: list[WireSegment] = [
        (float(w["x1"]), float(w["y1"]), float(w["x2"]), float(w["y2"]))
        for w in data.get("wires", [])
    ]
    reached = {index for index, wire in enumerate(segments) if point_on_segment(point, wire)}
    frontier = list(reached)
    while frontier:
        current = segments[frontier.pop()]
        for index, wire in enumerate(segments):
            if index not in reached and segments_merge(current, wire):
                reached.add(index)
                frontier.append(index)
    return [segments[index] for index in reached]


def _named_nets_at_pin(point: tuple[float, float], data: ParsedSchematic) -> set[str]:
    """Identify labels on the complete pre-existing wire network at a pin."""
    selected = _wire_network_at_pin(point, data)

    def on_net(other_point: tuple[float, float]) -> bool:
        return (
            abs(other_point[0] - point[0]) <= 1e-6 and abs(other_point[1] - point[1]) <= 1e-6
        ) or any(point_on_segment(other_point, wire) for wire in selected)

    names: set[str] = set()
    for label in data.get("labels", []):
        position = (float(label["x"]), float(label["y"]))
        if on_net(position):
            names.add(str(label["name"]))
    for symbol in data.get("power_symbols", []):
        position = (float(symbol["x"]), float(symbol["y"]))
        if on_net(position):
            names.add(str(symbol.get("value") or symbol.get("name") or ""))
    return {name for name in names if name}


def _assert_named_net_separation(
    start: tuple[float, float],
    end: tuple[float, float],
    data: ParsedSchematic,
    payload: RouteWireBetweenPinsInput,
) -> None:
    first_names = _named_nets_at_pin(start, data)
    second_names = _named_nets_at_pin(end, data)
    if first_names and second_names and first_names.isdisjoint(second_names):
        raise SchematicRoutingUnsafeError(
            f"Route refused between {payload.ref1}:{payload.pin1} and "
            f"{payload.ref2}:{payload.pin2}: conflicting_named_nets "
            f"({sorted(first_names)} != {sorted(second_names)}). "
            "No schematic changes were made."
        )


def _assert_route_geometry_safe(
    segments: list[WireSegment],
    occupied: list[WireSegment],
    routing_warning: str | None,
    crossings: int,
    payload: RouteWireBetweenPinsInput,
) -> None:
    """Reject planner fallbacks and independently detect cross-net unions."""
    reason: str | None = None
    if routing_warning and routing_warning != "WARNING: net_crossing_unavoidable":
        reason = routing_warning
    elif any(segments_merge(segment, other) for segment in segments for other in occupied):
        reason = "net_isolation_failed"
    elif routing_warning == "WARNING: net_crossing_unavoidable" and not crossings:
        reason = "unverified_crossing_fallback"
    if reason:
        raise SchematicRoutingUnsafeError(
            f"Route refused between {payload.ref1}:{payload.pin1} and "
            f"{payload.ref2}:{payload.pin2}: {reason}. "
            "No schematic changes were made."
        )


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
    foreign_wire_segments: Callable[
        [str, list[tuple[float, float]]],
        list[WireSegment],
    ]
    count_net_crossings: Callable[
        [list[WireSegment], list[WireSegment]],
        int,
    ]
    route_avoiding_obstacles: Callable[
        [
            tuple[float, float],
            tuple[float, float],
            list[BoundingBoxLike],
            bool,
            list[WireSegment] | None,
            tuple[float, float] | None,
            tuple[float, float] | None,
            list[BoundingBoxLike] | None,
        ],
        tuple[list[WireSegment], str | None],
    ]
    get_pin_outward_normals: Callable[
        [str, str, int, int],
        dict[str, tuple[float, float]],
    ]
    run_auto_add_missing_junctions: Callable[[], str]
    snap_tolerance_mm: float
    #: Drawn rectangles a route must not travel alongside -- hierarchical sheets
    #: and bare rectangles around a self-contained block.  Not solid: a wire still
    #: has to cross one to reach a pin inside it.  Defaults to none so a caller
    #: that predates the rule keeps working; only wire routing consults it.
    get_module_boundaries: Callable[[str], list[BoundingBoxLike]] = _no_module_boundaries

    def _init_placed_maps(
        self, data: dict[str, Any]
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
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
        return placed, placed_kind

    def _resolve_connection_candidates(
        self, blocks: list[dict[str, Any]], wanted_unit: object
    ) -> list[dict[str, Any]]:
        if wanted_unit is None:
            return blocks
        try:
            wanted_unit_number = int(str(wanted_unit))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unit must be an integer, got {wanted_unit!r}") from exc
        return [block for block in blocks if int(block.get("unit", 1) or 1) == wanted_unit_number]

    def _find_pin_in_candidates(
        self, candidates: list[dict[str, Any]], pin: str, ref: str
    ) -> tuple[
        dict[str, Any], tuple[float, float] | None, PinPositions, str, str, bool, str | None
    ]:
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
        return sym, point, pin_positions, library, symbol_name, is_power_symbol, unresolved_lib_id

    def _resolve_pin_point(
        self,
        *,
        point: tuple[float, float] | None,
        pin_positions: PinPositions,
        sym: dict[str, Any],
        pin: str,
        ref: str,
        ox: float,
        oy: float,
        is_power_symbol_ref: bool,
        unresolved_lib_id: str | None,
    ) -> tuple[tuple[float, float] | None, PinPositions, str | None]:
        if point is not None:
            return point, pin_positions, None

        lib_id = str(sym.get("lib_id", ""))
        if ":" not in lib_id:
            return (
                None,
                pin_positions,
                (
                    f"{ref}.{pin}: symbol type not supported: "
                    f"unresolved lib_id '{unresolved_lib_id or lib_id}'"
                ),
            )
        sym_library, sym_name = lib_id.split(":", 1)
        sym_is_power = sym_library == "power" or ref.startswith("#PWR")

        if is_power_symbol_ref:
            if pin != "1":
                return (
                    None,
                    pin_positions,
                    f"{ref}.{pin}: symbol type not supported for pin '{pin}'",
                )
            return (ox, oy), {"1": (ox, oy)}, None

        if (
            sym_is_power
            and pin == "1"
            and self.is_origin_pin_power_symbol(sym_name, str(sym.get("value", "")))
        ):
            pt = (round(ox, 4), round(oy, 4))
            return pt, {"1": pt}, None

        if sym_is_power and not pin_positions:
            return (
                None,
                pin_positions,
                (
                    f"{ref}.{pin}: symbol type not supported: "
                    f"{sym.get('lib_id', '')} has no resolvable pin geometry"
                ),
            )

        return None, pin_positions, f"{ref}.{pin}: pin not found"

    def _compute_staggered_terminal(
        self,
        px: float,
        py: float,
        ux: float,
        uy: float,
        stub_mm: float,
        occupied_terminals: list[tuple[float, float]],
        terminal_clearance_mm: float,
        stagger_step_mm: float,
        max_stagger_steps: int,
    ) -> tuple[float, float, int]:
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
        return ex, ey, stagger_steps

    def _emit_terminal_block(
        self,
        *,
        conn: dict[str, Any],
        net: str,
        ex: float,
        ey: float,
        ux: float,
        uy: float,
        ref: str,
        pin: str,
        suffix: str,
        block_kind: str,
        project_name: str,
        root_uuid: str,
        power_lib_defs: dict[str, str],
    ) -> tuple[str, str, str | None]:
        if self.is_power_net(net):
            if net not in power_lib_defs:
                lib_def = self.load_lib_symbol("power", net)
                if lib_def is None:
                    return "", "", f"{ref}.{pin}: power symbol '{net}' was not found"
                power_lib_defs[net] = lib_def
            block = self.place_symbol_block(
                lib_id=f"power:{net}",
                x=ex,
                y=ey,
                reference=power_reference_from_uuid(self.new_uuid()),
                value=net,
                rotation=self.power_symbol_rotation_from_vector(ux, uy),
                project_name=project_name,
                root_uuid=root_uuid,
            )
            msg = f"{ref}.{pin} -> {net} (power) @ ({ex}, {ey}){suffix}"
            return block, msg, None

        rotation = self.terminal_rotation_from_vector(ux, uy)
        shape = conn.get("shape")
        if shape is not None and (not isinstance(shape, str) or shape not in LABEL_SHAPES):
            raise ValueError(f"shape must be one of {sorted(LABEL_SHAPES)}, got {shape!r}")
        block = self.label_block(
            net,
            ex,
            ey,
            rotation,
            kind=block_kind,
            shape=shape,
        )
        msg = f"{ref}.{pin} -> {net} @ ({ex}, {ey}){suffix}"
        return block, msg, None

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
        if label_kind is not None:
            block_kind = LABEL_KIND_TO_BLOCK_KIND[label_kind]
        elif global_labels:
            block_kind = "global_label"
        else:
            block_kind = "label"
        target = self.resolve_target(sheet, sheet_file)
        data = self.parse_schematic(target.path)
        placed, placed_kind = self._init_placed_maps(data)

        project_name = self.project_name()
        root_uuid = str(data.get("uuid") or self.new_uuid())
        wire_blocks: list[str] = []
        terminal_blocks: list[str] = []
        power_lib_defs: dict[str, str] = {}
        occupied_terminals: list[tuple[float, float]] = []
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
            candidates = self._resolve_connection_candidates(blocks, conn.get("unit"))
            if not candidates:
                results.append(f"{ref}.{pin}: unit {conn.get('unit')} not found")
                continue

            (
                sym,
                point,
                pin_positions,
                _library,
                _symbol_name,
                _is_power_symbol,
                unresolved_lib_id,
            ) = self._find_pin_in_candidates(candidates, pin, ref)
            ox, oy = float(sym.get("x", 0.0)), float(sym.get("y", 0.0))
            point, pin_positions, err = self._resolve_pin_point(
                point=point,
                pin_positions=pin_positions,
                sym=sym,
                pin=pin,
                ref=ref,
                ox=ox,
                oy=oy,
                is_power_symbol_ref=(placed_kind.get(ref) == "power_symbol"),
                unresolved_lib_id=unresolved_lib_id,
            )
            if err is not None or point is None:
                results.append(err or f"{ref}.{pin}: pin not found")
                continue

            px, py = point
            stack_key = (round(px, 4), round(py, 4), net)
            shared_terminal = stacked_terminals.get(stack_key)
            if shared_terminal is not None:
                sx, sy = shared_terminal
                results.append(f"{ref}.{pin} -> {net} (stacked on shared terminal @ ({sx}, {sy}))")
                continue

            ux, uy = self.pin_label_stub_direction(point, (ox, oy), pin_positions.values())
            ex, ey, stagger_steps = self._compute_staggered_terminal(
                px,
                py,
                ux,
                uy,
                stub_mm,
                occupied_terminals,
                terminal_clearance_mm,
                stagger_step_mm,
                max_stagger_steps,
            )
            occupied_terminals.append((ex, ey))
            wire_blocks.append(self.wire_block(px, py, ex, ey))
            suffix = f"; staggered {stagger_steps} step(s)" if stagger_steps else ""

            block, msg, block_err = self._emit_terminal_block(
                conn=conn,
                net=net,
                ex=ex,
                ey=ey,
                ux=ux,
                uy=uy,
                ref=ref,
                pin=pin,
                suffix=suffix,
                block_kind=block_kind,
                project_name=project_name,
                root_uuid=root_uuid,
                power_lib_defs=power_lib_defs,
            )
            if block_err is not None:
                results.append(block_err)
                wire_blocks.pop()
                occupied_terminals.pop()
                continue

            terminal_blocks.append(block)
            stacked_terminals[stack_key] = (ex, ey)
            results.append(msg)

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
        # Read once before parsing: all pin positions, net classes and route
        # geometry must be derived from the same source revision.
        source_path = self.active_schematic_file()
        source_bytes = source_path.read_bytes()
        data = self.parse_schematic(source_path)
        if source_path.read_bytes() != source_bytes:
            raise SchematicRoutingUnsafeError(
                "Route refused: schematic changed during parsing. No schematic changes were made."
            )
        content = source_bytes.decode("utf-8")
        # Power symbols are addressable routing endpoints too.  They live in a
        # separate list because they are excluded from BOM/annotation/placement,
        # not because they cannot carry a wire -- and a pin's own ground stub is
        # usually the only way to reach its net on a sheet.  The sibling tools
        # (move/delete/modify_property) already resolve ``#PWR`` references, so
        # the router not seeing them was an inconsistency, not a guard.
        symbols = {
            symbol["reference"]: symbol for symbol in [*data["symbols"], *data["power_symbols"]]
        }
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

        # The direction each wire must leave and reach its pin in.  Without this
        # the search may leave a pin sideways for free, which turns at the pin
        # and lets two same-length candidates tie on cost.
        start_normal = self.get_pin_outward_normals(
            first_library, first_symbol, int(first["rotation"]), int(first["unit"])
        ).get(payload.pin1)
        end_normal = self.get_pin_outward_normals(
            second_library, second_symbol, int(second["rotation"]), int(second["unit"])
        ).get(payload.pin2)

        _assert_named_net_separation(start, end, data, payload)

        obstacles = self.get_symbol_bboxes(content)
        boundaries = self.get_module_boundaries(content)
        # Wires that already belong to another net are what this route must not
        # merge with; the pins' own net is exempt so a partly drawn net can be
        # extended to its remaining pins.
        occupied = self.foreign_wire_segments(content, [start, end])
        segments, routing_warning = self.route_avoiding_obstacles(
            start,
            end,
            obstacles,
            payload.snap_to_grid,
            occupied,
            start_normal,
            end_normal,
            boundaries,
        )
        crossings = self.count_net_crossings(segments, occupied)
        if not segments:
            return (
                f"{payload.ref1}:{payload.pin1} and {payload.ref2}:{payload.pin2} already overlap."
            )
        _assert_route_geometry_safe(segments, occupied, routing_warning, crossings, payload)

        def mutator(current: str) -> str:
            # A plan derived from stale topology must not write into a schematic
            # that another MCP tool or KiCad editor changed in the meantime.
            if source_path.read_bytes() != source_bytes or current.replace(
                "\r\n", "\n"
            ) != content.replace("\r\n", "\n"):
                raise SchematicRoutingUnsafeError(
                    "Route refused: schematic changed during planning. "
                    "No schematic changes were made."
                )
            updated = current
            for segment in segments:
                updated = self.append_before_sheet_instances(
                    updated,
                    self.wire_block(*segment),
                )
            return updated

        self.transactional_write(mutator, None)
        result = self.reload_schematic()
        # A crossing is legal in KiCad -- no junction is placed -- so it is worth
        # stating plainly rather than leaving the reader to squint at the render.
        crossing_note = (
            f"Note: the route crosses {crossings} other net(s) without connecting."
            if crossings
            else ""
        )
        return (
            f"{result}\nRouted {len(segments)} wire segment(s) between "
            f"{payload.ref1}:{payload.pin1} and {payload.ref2}:{payload.pin2}."
            + (f"\n{routing_warning}" if routing_warning else "")
            + (f"\n{crossing_note}" if crossing_note else "")
        )

    def add_missing_junctions(self) -> str:
        """Repair T-intersection junctions and reload the active schematic."""
        summary = self.run_auto_add_missing_junctions()
        result = self.reload_schematic()
        return f"{result}\n{summary}"
