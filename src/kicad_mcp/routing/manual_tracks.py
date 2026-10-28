"""FastMCP-independent manual-track routing service."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..models.common import _PadLike
from ..models.pcb import AddTrackInput
from ..pcb.geometry import point_xy_mm

PadProvider = Callable[[], Iterable[_PadLike]]


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


TrackWriter = Callable[[str, list[TrackSpec]], None]


def _find_pad(
    pads: Iterable[_PadLike],
    reference: str,
    pad_number: str,
) -> _PadLike | None:
    for pad in pads:
        if pad.parent.reference_field.text.value == reference and str(pad.number) == str(
            pad_number
        ):
            return pad
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
        start_pad = _find_pad(self.list_pads(), ref1, pad1)
        end_pad = _find_pad(self.list_pads(), ref2, pad2)
        if start_pad is None or end_pad is None:
            return "One or both pads were not found on the active board."

        start_x, start_y = point_xy_mm(start_pad.position)
        end_x, end_y = point_xy_mm(end_pad.position)
        net_name = start_pad.net.name or end_pad.net.name or ""
        specs = [
            _spec_from_payload(
                AddTrackInput(
                    x1_mm=start_x,
                    y1_mm=start_y,
                    x2_mm=end_x,
                    y2_mm=start_y,
                    layer=layer,
                    width_mm=width_mm,
                    net_name=net_name,
                )
            ),
            _spec_from_payload(
                AddTrackInput(
                    x1_mm=end_x,
                    y1_mm=start_y,
                    x2_mm=end_x,
                    y2_mm=end_y,
                    layer=layer,
                    width_mm=width_mm,
                    net_name=net_name,
                )
            ),
        ]
        self.write_tracks("route_from_pad_to_pad", specs)
        return (
            f"Orthogonal two-segment track write submitted for "
            f"{ref1}:{pad1} -> {ref2}:{pad2}. "
            "Board persistence and electrical connectivity UNVERIFIED; "
            "verify with DRC and project_quality_gate."
        )
