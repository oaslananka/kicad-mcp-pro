"""Advanced and experimental routing helpers."""

from __future__ import annotations

from typing import Any, Protocol, cast

from kipy.board_types import Net, Track
from kipy.geometry import Vector2
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import board_transaction, get_board
from ..models.pcb import AddTrackInput
from ..utils.layers import resolve_layer
from ..utils.units import mm_to_nm, nm_to_mm


class _PositionLike(Protocol):
    x_nm: int
    y_nm: int


class _TextValueLike(Protocol):
    value: str


class _TextFieldLike(Protocol):
    text: _TextValueLike


class _FootprintLike(Protocol):
    reference_field: _TextFieldLike


class _NetLike(Protocol):
    name: str


class _PadLike(Protocol):
    parent: _FootprintLike
    number: str | int
    position: _PositionLike
    net: _NetLike


def _coord_nm(point: object, axis: str) -> int:
    attr_name = f"{axis}_nm"
    value = getattr(point, attr_name) if hasattr(point, attr_name) else getattr(point, axis)
    return int(value)


def _find_pad(reference: str, pad_number: str) -> _PadLike | None:
    for pad in cast(list[_PadLike], get_board().get_pads()):
        if pad.parent.reference_field.text.value == reference and str(pad.number) == str(
            pad_number
        ):
            return pad
    return None


def _experimental_message(name: str) -> str:
    if not get_config().enable_experimental_tools:
        return f"{name} is experimental. Enable experimental tools to use it."
    return (
        f"{name} is not exposed as a stable KiCad 10.x IPC workflow yet. "
        "This tool is present so clients can discover the capability boundary."
    )


def register(mcp: FastMCP) -> None:
    """Register routing tools."""

    @mcp.tool()
    def route_single_track(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        """Route a single straight track segment."""
        payload = AddTrackInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
            net_name=net_name,
        )
        track = Track()
        track.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
        track.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
        track.layer = cast(Any, resolve_layer(payload.layer))
        track.width = mm_to_nm(payload.width_mm)
        if payload.net_name:
            net = Net()
            net.name = payload.net_name
            track.net = net
        with board_transaction() as board:
            board.create_items([track])
        return "Single track routed."

    @mcp.tool()
    def route_from_pad_to_pad(
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
    ) -> str:
        """Create a simple orthogonal route between two pads."""
        start_pad = _find_pad(ref1, pad1)
        end_pad = _find_pad(ref2, pad2)
        if start_pad is None or end_pad is None:
            return "One or both pads were not found on the active board."

        start_x = nm_to_mm(_coord_nm(start_pad.position, "x"))
        start_y = nm_to_mm(_coord_nm(start_pad.position, "y"))
        end_x = nm_to_mm(_coord_nm(end_pad.position, "x"))
        end_y = nm_to_mm(_coord_nm(end_pad.position, "y"))
        payloads = [
            AddTrackInput(
                x1_mm=start_x,
                y1_mm=start_y,
                x2_mm=end_x,
                y2_mm=start_y,
                layer=layer,
                width_mm=width_mm,
                net_name=start_pad.net.name or end_pad.net.name or "",
            ),
            AddTrackInput(
                x1_mm=end_x,
                y1_mm=start_y,
                x2_mm=end_x,
                y2_mm=end_y,
                layer=layer,
                width_mm=width_mm,
                net_name=start_pad.net.name or end_pad.net.name or "",
            ),
        ]
        tracks: list[Track] = []
        for payload in payloads:
            track = Track()
            track.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
            track.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
            track.layer = cast(Any, resolve_layer(payload.layer))
            track.width = mm_to_nm(payload.width_mm)
            if payload.net_name:
                net = Net()
                net.name = payload.net_name
                track.net = net
            tracks.append(track)
        with board_transaction() as board:
            board.create_items(tracks)
        return (
            f"Created an orthogonal two-segment route from {ref1}:{pad1} to {ref2}:{pad2}. "
            "Run DRC to verify the path."
        )

    @mcp.tool()
    def route_differential_pair(
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.2,
        gap_mm: float = 0.2,
    ) -> str:
        """[EXPERIMENTAL] Describe the current differential pair routing boundary."""
        _ = (ref1, pad1, ref2, pad2, layer, width_mm, gap_mm)
        return _experimental_message("Differential pair routing")

    @mcp.tool()
    def tune_track_length(net_name: str, target_length_mm: float) -> str:
        """[EXPERIMENTAL] Describe the current capability boundary for length tuning."""
        _ = (net_name, target_length_mm)
        return _experimental_message("Track length tuning")

    @mcp.tool()
    def tune_diff_pair_length(net_name_p: str, net_name_n: str, target_length_mm: float) -> str:
        """[EXPERIMENTAL] Describe the current differential pair length tuning boundary."""
        _ = (net_name_p, net_name_n, target_length_mm)
        return _experimental_message("Differential pair length tuning")
