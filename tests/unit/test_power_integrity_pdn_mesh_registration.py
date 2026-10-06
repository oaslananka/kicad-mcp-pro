from __future__ import annotations

import importlib
import inspect
from typing import Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.verdict import VerdictReport


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def analyze(self, **kwargs: object) -> VerdictReport:
        self.calls.append(kwargs)
        return VerdictReport.from_text_verdict(
            text="pdn-result",
            summary="pdn-summary",
            verdict="PASS",
            source="check_power_integrity",
            metadata={"domain": "power_integrity"},
        )


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_pdn_mesh")
    server = FastMCP("pi-pdn-mesh-registration")
    service = FakeService()
    adapter.register(server, cast(Any, service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["check_power_integrity"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_name: 'str', source_ref: 'str', load_refs: 'list[str]', trace_width_mm: 'float', "
        "load_current_a: 'float' = 0.1, trace_length_mm: 'float' = 100.0, "
        "copper_weight_oz: 'float' = 1.0, nominal_voltage_v: 'float' = 3.3, "
        "frequency_points_hz: 'list[float] | None' = None, "
        "decoupling_caps_uf: 'list[float] | None' = None, "
        "target_impedance_ohm: 'float | None' = None, decoupling_esr_mohm: 'float' = 20.0, "
        "decoupling_esl_nh: 'float' = 1.0) -> 'VerdictReport'"
    )
    assert tool.fn.__doc__ == "Run a lightweight PDN mesh voltage-drop check for a power net."

    result = tool.fn("3V3", "U_REG", ["U1"], 0.25)
    assert result.text == "pdn-result"
    assert service.calls == [
        {
            "net_name": "3V3",
            "source_ref": "U_REG",
            "load_refs": ["U1"],
            "trace_width_mm": 0.25,
            "load_current_a": 0.1,
            "trace_length_mm": 100.0,
            "copper_weight_oz": 1.0,
            "nominal_voltage_v": 3.3,
            "frequency_points_hz": None,
            "decoupling_caps_uf": None,
            "target_impedance_ohm": None,
            "decoupling_esr_mohm": 20.0,
            "decoupling_esl_nh": 1.0,
        }
    ]
