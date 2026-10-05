from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.signal_integrity import DifferentialPairSkewInput
from kicad_mcp.models.verdict import VerdictReport


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def analyze(
        self,
        payload: object,
        lengths: dict[str, float],
        skew_budget_ps: float,
        track_width_provider: object,
        dielectric_height_provider: object,
        budget_resolver: object,
    ) -> VerdictReport:
        self.calls.append(
            (
                payload,
                lengths,
                skew_budget_ps,
                track_width_provider,
                dielectric_height_provider,
                budget_resolver,
            )
        )
        return VerdictReport.from_text_verdict(
            text="skew-result",
            summary="skew-result",
            verdict="PASS",
            source="si_check_differential_pair_skew",
        )


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_differential_pair_skew")
    server = FastMCP("si-differential-pair-skew-registration")
    service = FakeService()

    def track_width(_net: str) -> float:
        return 0.2

    def dielectric_height() -> float:
        return 0.18

    def budget_resolver(_p: str, _n: str) -> tuple[float, str]:
        return 10.0, "fixture budget"

    adapter.register(
        server,
        adapter.SignalIntegrityDifferentialPairSkewDependencies(
            service=cast(Any, service),
            track_length_provider=lambda: {"P": 10.0, "N": 10.5},
            track_width_provider=track_width,
            dielectric_height_provider=dielectric_height,
            budget_resolver=budget_resolver,
        ),
    )

    tool_list = server._tool_manager.list_tools()
    assert [tool.name for tool in tool_list] == ["si_check_differential_pair_skew"]

    tool = tool_list[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_p: 'str', net_n: 'str', er: 'float' = 4.2, "
        "trace_type: 'str' = 'microstrip', skew_budget_ps: 'float' = 0.0) "
        "-> 'VerdictReport'"
    )
    assert tool.fn.__doc__ is not None
    assert tool.fn.__doc__.startswith(
        "Estimate differential-pair length skew and delay mismatch from board tracks."
    )

    result = tool.fn("P", "N", 4.0, "microstrip", 12.0)
    assert result.text == "skew-result"
    assert len(service.calls) == 1
    payload, lengths, budget, width_provider, height_provider, resolver = service.calls[0]
    assert isinstance(payload, DifferentialPairSkewInput)
    assert payload.net_p == "P"
    assert payload.net_n == "N"
    assert payload.er == 4.0
    assert payload.trace_type == "microstrip"
    assert lengths == {"P": 10.0, "N": 10.5}
    assert budget == 12.0
    assert width_provider is track_width
    assert height_provider is dielectric_height
    assert resolver is budget_resolver


def test_resolve_skew_budget_prefers_matching_interface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_differential_pair_skew")
    resolution = SimpleNamespace(
        resolved=SimpleNamespace(
            interfaces=[
                SimpleNamespace(diff_skew_max_ps=12.0, net_prefix="PCIE_"),
                SimpleNamespace(diff_skew_max_ps=8.0, net_prefix="USB_"),
                SimpleNamespace(diff_skew_max_ps=None, net_prefix=""),
            ]
        )
    )
    monkeypatch.setattr(adapter, "resolve_design_intent", lambda: resolution)

    assert adapter._resolve_skew_budget_ps("USB_DP", "USB_DN") == (
        8.0,
        "design-intent interface budget 8.0 ps",
    )


def test_resolve_skew_budget_uses_tightest_declared_when_prefix_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_differential_pair_skew")
    resolution = SimpleNamespace(
        resolved=SimpleNamespace(
            interfaces=[
                SimpleNamespace(diff_skew_max_ps=12.0, net_prefix="PCIE_"),
                SimpleNamespace(diff_skew_max_ps=7.0, net_prefix=""),
            ]
        )
    )
    monkeypatch.setattr(adapter, "resolve_design_intent", lambda: resolution)

    assert adapter._resolve_skew_budget_ps("USB_DP", "USB_DN") == (
        7.0,
        "tightest design-intent budget 7.0 ps (no net-prefix match)",
    )
