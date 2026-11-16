"""FastMCP-independent manual-track routing service."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast

from ..models.common import _PadLike
from ..models.pcb import AddTrackInput
from ..pcb.geometry import point_xy_mm
from ..pcb.pad_mapping import MappedPad

PadProvider = Callable[[], Iterable[MappedPad]]


@dataclass(frozen=True)
class TrackSpec:
    """Transport-neutral track description for live-board infrastructure."""

    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    layer: str
    width_mm: float
    net_name: str = ""


@dataclass(frozen=True)
class ViaSpec:
    """Single full-stack through-via candidate (never a blind/micro via)."""

    x_mm: float
    y_mm: float
    diameter_mm: float
    drill_mm: float
    net_name: str


TrackWriter = Callable[[str, list[TrackSpec]], None]
LayerValidator = Callable[[object, object, str], bool]


def _find_pad(
    pads: Iterable[MappedPad],
    reference: str,
    pad_number: str,
) -> MappedPad | None:
    for mapped in pads:
        if mapped.reference == reference and str(getattr(mapped.pad, "number", "")) == str(
            pad_number
        ):
            return mapped
    return None


def _spec_from_payload(payload: AddTrackInput) -> TrackSpec:
    return TrackSpec(
        x1_mm=payload.x1_mm,
        y1_mm=payload.y1_mm,
        x2_mm=payload.x2_mm,
        y2_mm=payload.y2_mm,
        layer=payload.layer,
        width_mm=payload.width_mm,
        net_name=payload.net_name,
    )


@dataclass(frozen=True)
class RoutingManualTrackService:
    """Create direct and pad-to-pad track specs through injected board infrastructure."""

    list_pads: PadProvider
    write_tracks: TrackWriter
    validate_layer: LayerValidator

    def route_single(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        payload = AddTrackInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
            net_name=net_name,
        )
        self.write_tracks("route_single_track", [_spec_from_payload(payload)])
        # A completed write call is not independent board read-back or DRC.
        # Do not claim the electrical route is complete from this operation.
        return (
            "Track segment write submitted. Board persistence and electrical connectivity "
            "UNVERIFIED; verify with DRC and project_quality_gate."
        )

    def route_pad_to_pad(
        self,
        ref1: str,
        pad1: str,
        ref2: str,
        pad2: str,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
    ) -> str:
        pads = list(self.list_pads())
        start = _find_pad(pads, ref1, pad1)
        end = _find_pad(pads, ref2, pad2)
        if start is None or end is None:
            return "One or both pads were not found on the active board."

        start_pad = cast(_PadLike, start.pad)
        end_pad = cast(_PadLike, end.pad)
        start_net = start_pad.net.name or ""
        end_net = end_pad.net.name or ""
        if not start_net or not end_net:
            return "Both pads must belong to a named net; no track created."
        if start_net != end_net:
            return f"Pads belong to different nets ({start_net}, {end_net}); no track created."
        if not self.validate_layer(start_pad, end_pad, layer):
            return (
                f"One or both pads do not support enabled copper layer {layer}; no track created."
            )

        start_x, start_y = point_xy_mm(start_pad.position)
        end_x, end_y = point_xy_mm(end_pad.position)
        if start_x == end_x and start_y == end_y:
            return "Pad endpoints overlap; no track created."

        specs: list[TrackSpec] = []
        if start_x != end_x:
            specs.append(
                _spec_from_payload(
                    AddTrackInput(
                        x1_mm=start_x,
                        y1_mm=start_y,
                        x2_mm=end_x,
                        y2_mm=start_y,
                        layer=layer,
                        width_mm=width_mm,
                        net_name=start_net,
                    )
                )
            )
        if start_y != end_y:
            specs.append(
                _spec_from_payload(
                    AddTrackInput(
                        x1_mm=end_x,
                        y1_mm=start_y,
                        x2_mm=end_x,
                        y2_mm=end_y,
                        layer=layer,
                        width_mm=width_mm,
                        net_name=start_net,
                    )
                )
            )
        self.write_tracks("route_from_pad_to_pad", specs)
        geometry = "single-segment" if len(specs) == 1 else "two-segment"
        return (
            f"Orthogonal {geometry} track write submitted for "
            f"{ref1}:{pad1} -> {ref2}:{pad2}. "
            "Board persistence and electrical connectivity UNVERIFIED; "
            "verify with DRC and project_quality_gate."
        )
