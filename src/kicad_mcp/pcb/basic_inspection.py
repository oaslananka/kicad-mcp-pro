"""FastMCP-free basic PCB collection inspection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, cast

from .board_access import (
    BoardAccessError,
    board_footprints,
    board_nets_filtered,
    board_pads,
    board_shapes,
    board_zones,
)
from .pad_mapping import map_pads_to_footprints


class LimitItems(Protocol):
    """Apply the configured response item limit while preserving total count."""

    def __call__[T](self, items: Iterable[T]) -> tuple[list[T], int]: ...


class BasicInspectionBoard(Protocol):
    """Live-board methods required by basic inspection."""

    def get_nets(self, *, netclass_filter: object | None) -> Iterable[object]: ...

    def get_zones(self) -> Iterable[object]: ...

    def get_shapes(self) -> Iterable[object]: ...

    def get_pads(self) -> Iterable[object]: ...

    def get_footprints(self) -> Iterable[object]: ...

    def get_enabled_layers(self) -> Iterable[int]: ...


class ZoneLayerLike(Protocol):
    @property
    def layer(self) -> int: ...


class ZoneLayersLike(Protocol):
    @property
    def layers(self) -> Iterable[int]: ...


class TextValueLike(Protocol):
    @property
    def value(self) -> str: ...


class TextLike(Protocol):
    @property
    def text(self) -> TextValueLike: ...


class NetLike(Protocol):
    @property
    def name(self) -> str: ...


class PadLike(Protocol):
    @property
    def number(self) -> str | int: ...

    @property
    def net(self) -> NetLike: ...

    @property
    def position(self) -> object: ...


type GetBoard = Callable[[], object]
type FileFallback = Callable[[BaseException], str]
type WithDiagnostics = Callable[[str], str]
type LayerName = Callable[[int], str]
type CoordNm = Callable[[object, str], int]
type NmToMm = Callable[[int], float]
type ConnectionErrors = tuple[type[Exception], ...]


@dataclass(frozen=True)
class PcbBasicInspectionService:
    """Inspect common PCB collections through live and file-backed dependencies."""

    get_board: GetBoard
    limit_items: LimitItems
    file_backed_nets: FileFallback
    file_backed_zones: FileFallback
    file_backed_layers: FileFallback
    with_pcb_diagnostics: WithDiagnostics
    layer_name: LayerName
    undefined_layer: int
    coord_nm: CoordNm
    nm_to_mm: NmToMm
    connection_errors: ConnectionErrors

    @property
    def access_errors(self) -> ConnectionErrors:
        return (BoardAccessError, *self.connection_errors)

    def _board(self) -> BasicInspectionBoard:
        return cast(BasicInspectionBoard, self.get_board())

    def get_nets(self) -> str:
        """List live nets or return the existing file-backed fallback."""
        try:
            nets, total = self.limit_items(board_nets_filtered(self._board(), netclass_filter=None))
        except self.access_errors as exc:
            return self.file_backed_nets(exc)
        if not nets:
            return self.with_pcb_diagnostics("No nets are present on the active board.")
        lines = [f"Nets ({total} total):", "- Source: live-gui"]
        lines.extend(f"- {getattr(net, 'name', None) or '(unnamed)'}" for net in nets)
        return "\n".join(lines)

    def get_zones(self) -> str:
        """List live copper zones or return the existing file-backed fallback."""
        try:
            zones, total = self.limit_items(board_zones(self._board()))
        except self.access_errors as exc:
            return self.file_backed_zones(exc)
        if not zones:
            return self.with_pcb_diagnostics("No zones are present on the active board.")

        lines = [f"Zones ({total} total):", "- Source: live-gui"]
        for index, zone in enumerate(zones, start=1):
            name = getattr(zone, "name", None) or "(unnamed)"
            net = getattr(zone, "net", None)
            net_name = getattr(net, "name", None) or "(none)"
            line = f"{index}. name={name} net={net_name}"
            if hasattr(zone, "layer"):
                layer_zone = cast(ZoneLayerLike, zone)
                line += f" layer={self.layer_name(int(layer_zone.layer))}"
            if hasattr(zone, "layers"):
                layered_zone = cast(ZoneLayersLike, zone)
                line += (
                    f" layers={','.join(self.layer_name(layer) for layer in layered_zone.layers)}"
                )
            lines.append(line)
        return "\n".join(lines)

    def get_shapes(self) -> str:
        """List live graphical board shapes."""
        shapes, total = self.limit_items(board_shapes(self._board()))
        if not shapes:
            return self.with_pcb_diagnostics("No graphic shapes are present on the active board.")
        lines = [f"Shapes ({total} total):"]
        for index, shape in enumerate(shapes, start=1):
            layer = int(getattr(shape, "layer", self.undefined_layer))
            lines.append(f"{index}. {type(shape).__name__} layer={self.layer_name(layer)}")
        return "\n".join(lines)

    def get_pads(self) -> str:
        """List live board pads with references, nets, and coordinates."""
        board = self._board()
        mapped = map_pads_to_footprints(board_pads(board), board_footprints(board))
        pads, total = self.limit_items(mapped)
        if not pads:
            return self.with_pcb_diagnostics("No pads are present on the active board.")
        lines = [f"Pads ({total} total):"]
        for index, mapped_pad in enumerate(pads, start=1):
            pad = cast(PadLike, mapped_pad.pad)
            reference = mapped_pad.reference or "(unmapped)"
            number = pad.number
            net_name = pad.net.name or "(none)"
            x_mm = self.nm_to_mm(self.coord_nm(pad.position, "x"))
            y_mm = self.nm_to_mm(self.coord_nm(pad.position, "y"))
            lines.append(
                f"{index}. {reference}:{number} net={net_name} @ ({x_mm:.2f}, {y_mm:.2f}) mm"
            )
        return "\n".join(lines)

    def get_layers(self) -> str:
        """List enabled live layers or return the existing file-backed fallback."""
        try:
            layers = self._board().get_enabled_layers()
        except self.connection_errors as exc:
            return self.file_backed_layers(exc)
        names = [self.layer_name(layer) for layer in layers]
        return "Enabled layers:\n- Source: live-gui\n" + "\n".join(f"- {name}" for name in names)
