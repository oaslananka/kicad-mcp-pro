"""PCB read/write tools backed by KiCad IPC."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, TypeVar, cast

import structlog
from kipy.board_types import (
    BoardCircle,
    BoardItem,
    BoardRectangle,
    BoardSegment,
    BoardText,
    Net,
    Track,
    Via,
)
from kipy.geometry import Angle, Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer, ViaType
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import board_transaction, get_board
from ..models.pcb import (
    AddCircleInput,
    AddRectangleInput,
    AddSegmentInput,
    AddTextInput,
    AddTrackInput,
    AddViaInput,
    BulkTrackItem,
    SetBoardOutlineInput,
)
from ..utils.layers import resolve_layer
from ..utils.units import mm_to_nm, nm_to_mm

logger = structlog.get_logger(__name__)
T = TypeVar("T")


class _PositionLike(Protocol):
    x_nm: int
    y_nm: int


class _TextValueLike(Protocol):
    value: str


class _TextFieldLike(Protocol):
    text: _TextValueLike


class _NetLike(Protocol):
    name: str


class _FootprintLike(Protocol):
    reference_field: _TextFieldLike
    value_field: _TextFieldLike
    position: Any
    layer: int


class _PadLike(Protocol):
    parent: _FootprintLike
    number: str | int
    net: _NetLike
    position: Any


def _coord_nm(point: object, axis: str) -> int:
    attr_name = f"{axis}_nm"
    value = getattr(point, attr_name) if hasattr(point, attr_name) else getattr(point, axis)
    return int(value)


def _limit(items: Iterable[T]) -> tuple[list[T], int]:
    cfg = get_config()
    collected = list(items)
    return collected[: cfg.max_items_per_response], len(collected)


def _find_net(name: str) -> Net:
    net = Net()
    net.name = name
    return net


def _find_footprint_by_reference(reference: str) -> _FootprintLike | None:
    board = get_board()
    for footprint in cast(Iterable[_FootprintLike], board.get_footprints()):
        if footprint.reference_field.text.value == reference:
            return footprint
    return None


def _format_selection_id(item: object) -> str:
    item_id = getattr(getattr(item, "id", None), "value", "")
    return str(item_id)[:8] + ("..." if item_id else "")


def register(mcp: FastMCP) -> None:
    """Register PCB tools."""

    @mcp.tool()
    def pcb_get_board_summary() -> str:
        """Summarize the current board."""
        board = get_board()
        tracks = board.get_tracks()
        footprints = board.get_footprints()
        vias = board.get_vias()
        zones = board.get_zones()
        nets = board.get_nets(netclass_filter=None)
        shapes = board.get_shapes()
        return "\n".join(
            [
                "Board summary:",
                f"- Tracks: {len(tracks)}",
                f"- Vias: {len(vias)}",
                f"- Footprints: {len(footprints)}",
                f"- Zones: {len(zones)}",
                f"- Nets: {len(nets)}",
                f"- Shapes: {len(shapes)}",
            ]
        )

    @mcp.tool()
    def pcb_get_tracks() -> str:
        """List board tracks."""
        tracks, total = _limit(cast(Iterable[Track], get_board().get_tracks()))
        if not tracks:
            return "No tracks are present on the active board."

        lines = [f"Tracks ({total} total):"]
        for index, track in enumerate(tracks, start=1):
            lines.append(
                f"{index}. "
                f"({nm_to_mm(_coord_nm(track.start, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(track.start, 'y')):.2f}) -> "
                f"({nm_to_mm(_coord_nm(track.end, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(track.end, 'y')):.2f}) mm "
                f"layer={BoardLayer.Name(track.layer)} "
                f"width={nm_to_mm(track.width):.3f} mm "
                f"net={track.net.name or '(none)'} id={_format_selection_id(track)}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_vias() -> str:
        """List board vias."""
        vias, total = _limit(cast(Iterable[Via], get_board().get_vias()))
        if not vias:
            return "No vias are present on the active board."

        lines = [f"Vias ({total} total):"]
        for index, via in enumerate(vias, start=1):
            lines.append(
                f"{index}. "
                f"({nm_to_mm(_coord_nm(via.position, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(via.position, 'y')):.2f}) mm "
                f"diameter={nm_to_mm(via.diameter):.3f} mm "
                f"drill={nm_to_mm(via.drill_diameter):.3f} mm "
                f"net={via.net.name or '(none)'} type={ViaType.Name(via.type)}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_footprints() -> str:
        """List board footprints."""
        footprints, total = _limit(cast(Iterable[_FootprintLike], get_board().get_footprints()))
        if not footprints:
            return "No footprints are present on the active board."

        lines = [f"Footprints ({total} total):"]
        for footprint in footprints:
            lines.append(
                f"- {footprint.reference_field.text.value} "
                f"({footprint.value_field.text.value}) "
                f"@ ({nm_to_mm(_coord_nm(footprint.position, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(footprint.position, 'y')):.2f}) mm "
                f"layer={BoardLayer.Name(footprint.layer)} "
                f"id={_format_selection_id(footprint)}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_nets() -> str:
        """List all board nets."""
        nets, total = _limit(cast(Iterable[Net], get_board().get_nets(netclass_filter=None)))
        if not nets:
            return "No nets are present on the active board."
        lines = [f"Nets ({total} total):"]
        lines.extend(f"- {net.name or '(unnamed)'}" for net in nets)
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_zones() -> str:
        """List all board copper zones."""
        zones, total = _limit(cast(Iterable[Any], get_board().get_zones()))
        if not zones:
            return "No zones are present on the active board."

        lines = [f"Zones ({total} total):"]
        for index, zone in enumerate(zones, start=1):
            line = f"{index}. name={zone.name or '(unnamed)'} net={zone.net.name or '(none)'}"
            if hasattr(zone, "layer"):
                line += f" layer={BoardLayer.Name(zone.layer)}"
            if hasattr(zone, "layers"):
                line += f" layers={','.join(BoardLayer.Name(layer) for layer in zone.layers)}"
            lines.append(line)
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_shapes() -> str:
        """List graphical board shapes."""
        shapes, total = _limit(cast(Iterable[Any], get_board().get_shapes()))
        if not shapes:
            return "No graphic shapes are present on the active board."
        lines = [f"Shapes ({total} total):"]
        for index, shape in enumerate(shapes, start=1):
            layer = getattr(shape, "layer", BoardLayer.BL_UNDEFINED)
            lines.append(f"{index}. {type(shape).__name__} layer={BoardLayer.Name(layer)}")
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_pads() -> str:
        """List board pads."""
        pads, total = _limit(cast(Iterable[_PadLike], get_board().get_pads()))
        if not pads:
            return "No pads are present on the active board."
        lines = [f"Pads ({total} total):"]
        for index, pad in enumerate(pads, start=1):
            lines.append(
                f"{index}. {pad.parent.reference_field.text.value}:{pad.number} "
                f"net={pad.net.name or '(none)'} "
                f"@ ({nm_to_mm(_coord_nm(pad.position, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(pad.position, 'y')):.2f}) mm"
            )
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_layers() -> str:
        """List enabled board layers."""
        layers = get_board().get_enabled_layers()
        names = [BoardLayer.Name(layer) for layer in layers]
        return "Enabled layers:\n" + "\n".join(f"- {name}" for name in names)

    @mcp.tool()
    def pcb_get_stackup() -> str:
        """Show the current stackup."""
        stackup = get_board().get_stackup()
        lines = ["Board stackup:"]
        for layer in stackup.layers:
            material = getattr(layer, "material_name", "") or "-"
            lines.append(
                f"- {BoardLayer.Name(layer.layer)} "
                f"thickness={layer.thickness} nm "
                f"material={material}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_selection() -> str:
        """List currently selected items in the PCB editor."""
        items = list(get_board().get_selection())
        if not items:
            return "No PCB items are currently selected."
        lines = [f"Selected items ({len(items)} total):"]
        for index, item in enumerate(items, start=1):
            lines.append(f"{index}. {type(item).__name__} id={_format_selection_id(item)}")
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_board_as_string() -> str:
        """Return the current board as a bounded S-expression string."""
        cfg = get_config()
        data = get_board().get_as_string()
        if len(data) > cfg.max_text_response_chars:
            return f"{data[: cfg.max_text_response_chars]}\n... [truncated]"
        return data

    @mcp.tool()
    def pcb_get_ratsnest() -> str:
        """Report currently unconnected board items using the latest DRC view."""
        board = get_board()
        nets = board.get_nets(netclass_filter=None)
        if not nets:
            return "The active board has no nets to analyze."
        return (
            "Live ratsnest extraction is not exposed by KiCad 10.x IPC. "
            "Run `get_unconnected_nets()` or `run_drc()` for an actionable list."
        )

    @mcp.tool()
    def pcb_get_design_rules() -> str:
        """Read the active board design rules file when available."""
        cfg = get_config()
        if cfg.project_dir is None:
            return "No active project is configured."

        matches = sorted(cfg.project_dir.glob("*.kicad_dru"))
        if not matches:
            return "No .kicad_dru design rules file was found in the active project."

        content = matches[0].read_text(encoding="utf-8", errors="ignore")
        if len(content) > cfg.max_text_response_chars:
            content = f"{content[: cfg.max_text_response_chars]}\n... [truncated]"
        return content

    @mcp.tool()
    def pcb_add_track(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        """Add a single track segment."""
        payload = AddTrackInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
            net_name=net_name,
        )
        with board_transaction() as board:
            track = Track()
            track.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
            track.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
            track.layer = cast(Any, resolve_layer(payload.layer))
            track.width = mm_to_nm(payload.width_mm)
            if payload.net_name:
                track.net = _find_net(payload.net_name)
            board.create_items([track])
        return "Track added successfully."

    @mcp.tool()
    def pcb_add_tracks_bulk(tracks: list[BulkTrackItem]) -> str:
        """Add multiple tracks in a single operation."""
        validated = [BulkTrackItem.model_validate(track) for track in tracks]
        created: list[Track] = []
        for track_input in validated:
            track = Track()
            track.start = Vector2.from_xy_mm(track_input.x1, track_input.y1)
            track.end = Vector2.from_xy_mm(track_input.x2, track_input.y2)
            track.layer = cast(Any, resolve_layer(track_input.layer))
            track.width = mm_to_nm(track_input.width)
            if track_input.net:
                track.net = _find_net(track_input.net)
            created.append(track)
        with board_transaction() as board:
            board.create_items(created)
        return f"Added {len(created)} tracks."

    @mcp.tool()
    def pcb_add_via(
        x_mm: float,
        y_mm: float,
        diameter_mm: float = 0.8,
        drill_mm: float = 0.4,
        net_name: str = "",
        via_type: str = "through",
    ) -> str:
        """Add a via."""
        payload = AddViaInput(
            x_mm=x_mm,
            y_mm=y_mm,
            diameter_mm=diameter_mm,
            drill_mm=drill_mm,
            net_name=net_name,
            via_type=via_type,
        )
        type_map = {
            "through": ViaType.VT_THROUGH,
            "blind": ViaType.VT_BLIND_BURIED,
            "micro": ViaType.VT_MICRO,
        }
        via = Via()
        via.position = Vector2.from_xy_mm(payload.x_mm, payload.y_mm)
        via.diameter = mm_to_nm(payload.diameter_mm)
        via.drill_diameter = mm_to_nm(payload.drill_mm)
        via.type = cast(Any, type_map[payload.via_type])
        if payload.net_name:
            via.net = _find_net(payload.net_name)
        with board_transaction() as board:
            board.create_items([via])
        return "Via added successfully."

    @mcp.tool()
    def pcb_add_segment(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "Edge_Cuts",
        width_mm: float = 0.05,
    ) -> str:
        """Add a board graphic segment."""
        payload = AddSegmentInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
        )
        segment = BoardSegment()
        segment.layer = cast(Any, resolve_layer(payload.layer))
        segment.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
        segment.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
        segment.attributes.stroke.width = mm_to_nm(payload.width_mm)
        with board_transaction() as board:
            board.create_items([segment])
        return "Graphic segment added successfully."

    @mcp.tool()
    def pcb_add_circle(
        cx_mm: float,
        cy_mm: float,
        radius_mm: float,
        layer: str = "Edge_Cuts",
        width_mm: float = 0.05,
    ) -> str:
        """Add a board graphic circle."""
        payload = AddCircleInput(
            cx_mm=cx_mm,
            cy_mm=cy_mm,
            radius_mm=radius_mm,
            layer=layer,
            width_mm=width_mm,
        )
        circle = BoardCircle()
        circle.layer = cast(Any, resolve_layer(payload.layer))
        circle.center = Vector2.from_xy_mm(payload.cx_mm, payload.cy_mm)
        circle.radius_point = Vector2.from_xy_mm(payload.cx_mm + payload.radius_mm, payload.cy_mm)
        circle.attributes.stroke.width = mm_to_nm(payload.width_mm)
        with board_transaction() as board:
            board.create_items([circle])
        return "Graphic circle added successfully."

    @mcp.tool()
    def pcb_add_rectangle(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "Edge_Cuts",
        width_mm: float = 0.05,
    ) -> str:
        """Add a board graphic rectangle."""
        payload = AddRectangleInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
        )
        rectangle = BoardRectangle()
        rectangle.layer = cast(Any, resolve_layer(payload.layer))
        rectangle.top_left = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
        rectangle.bottom_right = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
        rectangle.attributes.stroke.width = mm_to_nm(payload.width_mm)
        with board_transaction() as board:
            board.create_items([rectangle])
        return "Graphic rectangle added successfully."

    @mcp.tool()
    def pcb_set_board_outline(
        width_mm: float,
        height_mm: float,
        origin_x_mm: float = 0.0,
        origin_y_mm: float = 0.0,
    ) -> str:
        """Draw a rectangular board outline on Edge.Cuts."""
        payload = SetBoardOutlineInput(
            width_mm=width_mm,
            height_mm=height_mm,
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
        )
        rectangle = BoardRectangle()
        rectangle.layer = BoardLayer.BL_Edge_Cuts
        rectangle.top_left = Vector2.from_xy_mm(payload.origin_x_mm, payload.origin_y_mm)
        rectangle.bottom_right = Vector2.from_xy_mm(
            payload.origin_x_mm + payload.width_mm,
            payload.origin_y_mm + payload.height_mm,
        )
        rectangle.attributes.stroke.width = mm_to_nm(0.05)
        with board_transaction() as board:
            board.create_items([rectangle])
        return "Board outline added successfully."

    @mcp.tool()
    def pcb_add_text(
        text: str,
        x_mm: float,
        y_mm: float,
        layer: str = "F_SilkS",
        size_mm: float = 1.0,
        rotation_deg: float = 0.0,
        bold: bool = False,
        italic: bool = False,
    ) -> str:
        """Add board text."""
        payload = AddTextInput(
            text=text,
            x_mm=x_mm,
            y_mm=y_mm,
            layer=layer,
            size_mm=size_mm,
            rotation_deg=rotation_deg,
            bold=bold,
            italic=italic,
        )
        text_item = BoardText()
        text_item.layer = cast(Any, resolve_layer(payload.layer))
        text_item.position = Vector2.from_xy_mm(payload.x_mm, payload.y_mm)
        text_item.value = payload.text
        text_item.attributes.size = Vector2.from_xy_mm(payload.size_mm, payload.size_mm)
        text_item.attributes.bold = payload.bold
        text_item.attributes.italic = payload.italic
        try:
            text_item.attributes.angle = payload.rotation_deg
        except Exception as exc:
            logger.debug("board_text_angle_not_supported", error=str(exc))
        with board_transaction() as board:
            board.create_items([text_item])
        return "Board text added successfully."

    @mcp.tool()
    def pcb_delete_items(item_ids: list[str]) -> str:
        """Delete items by UUID."""
        from kipy.proto.common.types import KIID

        if not item_ids:
            return "No item IDs were supplied."
        kiids = []
        for item_id in item_ids:
            kiid = KIID()
            kiid.value = item_id
            kiids.append(kiid)
        with board_transaction() as board:
            board.remove_items_by_id(kiids)
        return f"Deleted {len(kiids)} item(s)."

    @mcp.tool()
    def pcb_save() -> str:
        """Save the active board."""
        save = cast(Callable[[], None], get_board().save)
        save()
        return "Board saved."

    @mcp.tool()
    def pcb_refill_zones() -> str:
        """Refill all copper zones."""
        get_board().refill_zones(block=True, max_poll_seconds=60.0)
        return "Zones refilled."

    @mcp.tool()
    def pcb_highlight_net(net_name: str) -> str:
        """Attempt to highlight a net in the GUI when supported."""
        if not get_config().enable_experimental_tools:
            return "Net highlighting is experimental. Enable experimental tools to try it."
        return (
            "Net highlighting is not exposed as a stable KiCad 10.x IPC operation. "
            "Use `pcb_get_nets()` to confirm "
            f"the net '{net_name}' exists and highlight it in the GUI."
        )

    @mcp.tool()
    def pcb_set_net_class(net_name: str, class_name: str) -> str:
        """Assign a net class when the runtime supports it."""
        if not get_config().enable_experimental_tools:
            return "Net class assignment is experimental. Enable experimental tools to try it."
        return (
            "Direct net class assignment is not exposed as a stable KiCad 10.x IPC operation. "
            f"Update the project rules for net '{net_name}' to use class '{class_name}'."
        )

    @mcp.tool()
    def pcb_move_footprint(
        reference: str, x_mm: float, y_mm: float, rotation_deg: float = 0.0
    ) -> str:
        """Move a footprint to an absolute location."""
        footprint = _find_footprint_by_reference(reference)
        if footprint is None:
            return f"Footprint '{reference}' was not found on the active board."

        footprint.position = Vector2.from_xy_mm(x_mm, y_mm)
        if hasattr(footprint, "angle"):
            try:
                footprint.angle = Angle.from_degrees(rotation_deg)
            except Exception as exc:
                logger.debug("footprint_angle_not_supported", error=str(exc))
        elif hasattr(footprint, "orientation"):
            try:
                footprint.orientation = rotation_deg
            except Exception as exc:
                logger.debug("footprint_orientation_not_supported", error=str(exc))
        with board_transaction() as board:
            board.update_items([cast(BoardItem, footprint)])
        return f"Moved footprint '{reference}' to ({x_mm}, {y_mm}) mm."

    @mcp.tool()
    def pcb_set_footprint_layer(reference: str, layer: str) -> str:
        """Set the footprint copper side."""
        footprint = _find_footprint_by_reference(reference)
        if footprint is None:
            return f"Footprint '{reference}' was not found on the active board."
        footprint.layer = cast(Any, resolve_layer(layer))
        with board_transaction() as board:
            board.update_items([cast(BoardItem, footprint)])
        return f"Updated footprint '{reference}' to layer '{layer}'."
