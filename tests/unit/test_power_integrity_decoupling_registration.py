from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
from typing import Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.power_integrity import DecouplingRecommendationInput


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def recommend(
        self,
        *,
        payload: DecouplingRecommendationInput,
        references: list[str],
        recommendation_mm: float,
        nearby_by_ref: dict[str, list[tuple[str, float, str]]],
    ) -> str:
        self.calls.append((payload, references, recommendation_mm, nearby_by_ref))
        return "decoupling-result"


def test_registration_preserves_signature_docstring_and_delegation(monkeypatch) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_decoupling")
    server = FastMCP("pi-decoupling-registration")
    service = FakeService()
    calls: list[tuple[object, ...]] = []

    snapshot = [object()]

    def footprints() -> list[object]:
        calls.append(("footprints",))
        return snapshot

    def nearest(reference: str, footprint_snapshot: list[object]) -> list[tuple[str, float, str]]:
        calls.append(("nearest", reference, footprint_snapshot is snapshot))
        return [(f"C-{reference}", 1.0, "100n")]

    monkeypatch.setattr(adapter, "_nearest_capacitors", nearest)

    def recommended(freq_mhz: float) -> float:
        calls.append(("recommended", freq_mhz))
        return 2.5

    def max_items() -> int:
        calls.append(("max_items",))
        return 2

    adapter.register(
        server,
        adapter.PowerIntegrityDecouplingDependencies(
            service=cast(Any, service),
            footprints_provider=cast(Any, footprints),
            recommended_distance_provider=recommended,
            max_items_provider=max_items,
        ),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["pdn_recommend_decoupling_caps"]

    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(ic_refs: 'list[str]', vcc_net: 'str', supply_voltage_v: 'float', "
        "target_ripple_mv: 'float' = 20.0) -> 'str'"
    )
    assert tool.fn.__doc__ == "Recommend local and bulk decoupling from a simple PDN heuristic."

    assert tool.fn(["U1", "U2"], "3V3", 3.3) == "decoupling-result"
    assert calls == [
        ("max_items",),
        ("recommended", 200.0),
        ("footprints",),
        ("nearest", "U1", True),
        ("nearest", "U2", True),
    ]
    assert len(service.calls) == 1
    payload, references, recommendation_mm, nearby_by_ref = service.calls[0]
    assert isinstance(payload, DecouplingRecommendationInput)
    assert payload.ic_refs == ["U1", "U2"]
    assert payload.vcc_net == "3V3"
    assert payload.supply_voltage_v == 3.3
    assert payload.target_ripple_mv == 20.0
    assert references == ["U1", "U2"]
    assert recommendation_mm == 2.5
    assert nearby_by_ref == {
        "U1": [("C-U1", 1.0, "100n")],
        "U2": [("C-U2", 1.0, "100n")],
    }


def test_default_dependencies_resolve_helpers_and_config_late(monkeypatch) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_decoupling")
    deps = adapter._default_dependencies()
    board = object()
    footprints = [object()]
    calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(adapter, "get_board", lambda: calls.append(("board",)) or board)
    monkeypatch.setattr(
        adapter,
        "board_footprints",
        lambda value: calls.append(("footprints", value is board)) or footprints,
    )
    monkeypatch.setattr(adapter, "recommended_decoupling_distance_mm", lambda freq: freq / 100.0)
    monkeypatch.setattr(adapter, "get_config", lambda: SimpleNamespace(max_items_per_response=7))

    assert deps.footprints_provider() == footprints
    assert calls == [("board",), ("footprints", True)]
    assert deps.recommended_distance_provider(200.0) == 2.0
    assert deps.max_items_provider() == 7


def test_nearest_capacitors_filters_and_sorts(monkeypatch) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_decoupling")

    def footprint(reference: str, value: str, position: str) -> SimpleNamespace:
        return SimpleNamespace(
            reference_field=SimpleNamespace(text=SimpleNamespace(value=reference)),
            value_field=SimpleNamespace(text=SimpleNamespace(value=value)),
            position=position,
        )

    footprints = [
        footprint("U1", "MCU", "u"),
        footprint("R1", "10k", "r"),
        footprint("C2", "1u", "c2"),
        footprint("C1", "100n", "c1"),
    ]
    coords = {"u": (0.0, 0.0), "r": (0.5, 0.0), "c2": (2.0, 0.0), "c1": (1.0, 0.0)}
    monkeypatch.setattr(adapter, "point_xy_mm", lambda pos: coords[pos])

    assert adapter._nearest_capacitors("U1", cast(Any, footprints)) == [
        ("C1", 1.0, "100n"),
        ("C2", 2.0, "1u"),
    ]
    assert adapter._nearest_capacitors("U404", cast(Any, footprints)) == []
