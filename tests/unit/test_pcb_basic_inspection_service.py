from __future__ import annotations

from collections.abc import Callable, Iterable
from types import SimpleNamespace

import pytest

from kicad_mcp.pcb.basic_inspection import PcbBasicInspectionService


class FakeConnectionError(Exception):
    pass


def _limit[T](items: Iterable[T]) -> tuple[list[T], int]:
    collected = list(items)
    return collected[:2], len(collected)


def _service(
    board: object,
    *,
    nets_fallback: Callable[[BaseException], str] | None = None,
    zones_fallback: Callable[[BaseException], str] | None = None,
    layers_fallback: Callable[[BaseException], str] | None = None,
) -> PcbBasicInspectionService:
    return PcbBasicInspectionService(
        get_board=lambda: board,
        limit_items=_limit,
        file_backed_nets=nets_fallback or (lambda _exc: "nets fallback"),
        file_backed_zones=zones_fallback or (lambda _exc: "zones fallback"),
        file_backed_layers=layers_fallback or (lambda _exc: "layers fallback"),
        with_pcb_diagnostics=lambda message: f"diag::{message}",
        layer_name=lambda layer: {0: "F_Cu", 1: "B_Cu", -1: "BL_UNDEFINED"}[layer],
        undefined_layer=-1,
        coord_nm=lambda point, axis: int(getattr(point, axis)),
        nm_to_mm=lambda value: value / 1_000_000,
        connection_errors=(FakeConnectionError, OSError),
    )


def test_nets_preserve_limit_total_names_empty_and_fallback() -> None:
    def get_nets(*, netclass_filter: object | None) -> list[object]:
        return [
            SimpleNamespace(name="GND"),
            SimpleNamespace(name=""),
            SimpleNamespace(name="VCC"),
        ]

    def no_nets(*, netclass_filter: object | None) -> list[object]:
        return []

    board = SimpleNamespace(get_nets=get_nets)
    assert _service(board).get_nets() == "\n".join(
        ["Nets (3 total):", "- Source: live-gui", "- GND", "- (unnamed)"]
    )
    assert _service(SimpleNamespace(get_nets=no_nets)).get_nets() == (
        "diag::No nets are present on the active board."
    )

    def fail() -> object:
        raise FakeConnectionError("offline")

    service = PcbBasicInspectionService(
        get_board=fail,
        limit_items=_limit,
        file_backed_nets=lambda exc: f"nets::{exc}",
        file_backed_zones=lambda _exc: "unused",
        file_backed_layers=lambda _exc: "unused",
        with_pcb_diagnostics=lambda message: message,
        layer_name=str,
        undefined_layer=-1,
        coord_nm=lambda _point, _axis: 0,
        nm_to_mm=lambda value: float(value),
        connection_errors=(FakeConnectionError, OSError),
    )
    assert service.get_nets() == "nets::offline"


def test_zones_preserve_layers_names_empty_and_fallback() -> None:
    def get_zones() -> list[object]:
        return [
            SimpleNamespace(name="Power", net=SimpleNamespace(name="GND"), layer=0),
            SimpleNamespace(name="", net=SimpleNamespace(name=""), layers=[0, 1]),
        ]

    def no_zones() -> list[object]:
        return []

    board = SimpleNamespace(get_zones=get_zones)
    assert _service(board).get_zones() == "\n".join(
        [
            "Zones (2 total):",
            "- Source: live-gui",
            "1. name=Power net=GND layer=F_Cu",
            "2. name=(unnamed) net=(none) layers=F_Cu,B_Cu",
        ]
    )
    assert _service(SimpleNamespace(get_zones=no_zones)).get_zones() == (
        "diag::No zones are present on the active board."
    )

    def fail() -> object:
        raise FakeConnectionError("offline")

    service = _service(SimpleNamespace(), zones_fallback=lambda exc: f"zones::{exc}")
    object.__setattr__(service, "get_board", fail)
    assert service.get_zones() == "zones::offline"


def test_shapes_preserve_types_layers_and_empty_diagnostics() -> None:
    def get_shapes() -> list[object]:
        return [SimpleNamespace(layer=0), SimpleNamespace()]

    def no_shapes() -> list[object]:
        return []

    board = SimpleNamespace(get_shapes=get_shapes)
    assert _service(board).get_shapes() == "\n".join(
        [
            "Shapes (2 total):",
            "1. SimpleNamespace layer=F_Cu",
            "2. SimpleNamespace layer=BL_UNDEFINED",
        ]
    )
    assert _service(SimpleNamespace(get_shapes=no_shapes)).get_shapes() == (
        "diag::No graphic shapes are present on the active board."
    )


def test_pads_preserve_reference_net_and_coordinate_formatting() -> None:
    pad = SimpleNamespace(
        parent=SimpleNamespace(reference_field=SimpleNamespace(text=SimpleNamespace(value="U1"))),
        number="7",
        net=SimpleNamespace(name="GND"),
        position=SimpleNamespace(x=1_250_000, y=-2_500_000),
    )

    def get_pads() -> list[object]:
        return [pad]

    def no_pads() -> list[object]:
        return []

    assert _service(SimpleNamespace(get_pads=get_pads)).get_pads() == "\n".join(
        ["Pads (1 total):", "1. U1:7 net=GND @ (1.25, -2.50) mm"]
    )
    assert _service(SimpleNamespace(get_pads=no_pads)).get_pads() == (
        "diag::No pads are present on the active board."
    )


def test_layers_preserve_live_names_and_file_fallback() -> None:
    assert _service(SimpleNamespace(get_enabled_layers=lambda: [0, 1])).get_layers() == (
        "Enabled layers:\n- Source: live-gui\n- F_Cu\n- B_Cu"
    )

    def fail() -> object:
        raise FakeConnectionError("offline")

    service = _service(SimpleNamespace(), layers_fallback=lambda exc: f"layers::{exc}")
    object.__setattr__(service, "get_board", fail)
    assert service.get_layers() == "layers::offline"


def test_unexpected_basic_inspection_errors_are_not_hidden() -> None:
    def fail() -> object:
        raise RuntimeError("bug")

    service = PcbBasicInspectionService(
        get_board=fail,
        limit_items=_limit,
        file_backed_nets=lambda _exc: "unused",
        file_backed_zones=lambda _exc: "unused",
        file_backed_layers=lambda _exc: "unused",
        with_pcb_diagnostics=lambda message: message,
        layer_name=str,
        undefined_layer=-1,
        coord_nm=lambda _point, _axis: 0,
        nm_to_mm=lambda value: float(value),
        connection_errors=(FakeConnectionError, OSError),
    )
    with pytest.raises(RuntimeError, match="bug"):
        service.get_nets()
