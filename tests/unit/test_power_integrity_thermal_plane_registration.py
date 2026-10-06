from __future__ import annotations

import importlib
import inspect
from typing import Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.power_integrity import ThermalPlaneSpreadInput
from kicad_mcp.models.verdict import VerdictReport


class FakeService:
    def __init__(self) -> None:
        self.payloads: list[ThermalPlaneSpreadInput] = []

    def analyze(self, payload: ThermalPlaneSpreadInput) -> VerdictReport:
        self.payloads.append(payload)
        return VerdictReport.from_text_verdict(
            text="thermal-result",
            summary="thermal-summary",
            verdict="PASS",
            source="thermal_simulate_plane_spreading",
            metadata={"domain": "thermal"},
        )


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_thermal_plane")
    server = FastMCP("pi-thermal-plane-registration")
    service = FakeService()

    adapter.register(server, cast(Any, service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["thermal_simulate_plane_spreading"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(power_w: 'float', plane_width_mm: 'float', plane_height_mm: 'float', "
        "source_width_mm: 'float' = 5.0, source_height_mm: 'float' = 5.0, "
        "copper_oz: 'float' = 1.0, ambient_c: 'float' = 25.0, "
        "film_coefficient_w_per_m2_k: 'float' = 20.0, "
        "max_temp_rise_c: 'float' = 40.0) -> 'VerdictReport'"
    )
    assert inspect.getdoc(tool.fn) == (
        "Solve copper-plane heat spreading with a 2-D finite-difference thermal solver.\n\n"
        "Models a hot source dissipating ``power_w`` into a copper plane that loses heat to\n"
        "ambient through both faces (``film_coefficient_w_per_m2_k`` is the combined\n"
        "top+bottom film coefficient). Returns the peak and average temperature rise from a\n"
        "genuine distributed steady-state solve, with a PASS/WARN/FAIL verdict against\n"
        "``max_temp_rise_c``. This is a 2-D spreading solve, not a 3-D FEA with airflow."
    )

    result = tool.fn(1.0, 50.0, 40.0)
    assert result.text == "thermal-result"
    assert len(service.payloads) == 1
    payload = service.payloads[0]
    assert payload.power_w == 1.0
    assert payload.plane_width_mm == 50.0
    assert payload.plane_height_mm == 40.0
    assert payload.source_width_mm == 5.0
    assert payload.source_height_mm == 5.0
    assert payload.copper_oz == 1.0
    assert payload.ambient_c == 25.0
    assert payload.film_coefficient_w_per_m2_k == 20.0
    assert payload.max_temp_rise_c == 40.0
