# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_semantic_ir import (
    SchematicSemanticIRDependencies,
    register,
)
from kicad_mcp.utils.cache import clear_ttl_cache


class FakeSemanticIRService:
    def __init__(self) -> None:
        self.calls = 0

    def get_summary(self) -> str:
        self.calls += 1
        return f"summary-{self.calls}"


def _registered() -> tuple[FastMCP, FakeSemanticIRService]:
    clear_ttl_cache()
    server = FastMCP("schematic-semantic-ir-test")
    service = FakeSemanticIRService()
    register(server, SchematicSemanticIRDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_name_description_and_schema() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"sch_get_circuit_ir"}
    tool = tools["sch_get_circuit_ir"]
    assert tool.description == (
        "Return the semantic circuit IR for the active schematic.\n\n"
        "The IR decouples 'what the circuit is' (components, nets, pin\n"
        "roles, power domains, interfaces) from 'how KiCad stores it'\n"
        "(geometry, UUIDs, file format).  Wiring is expressed in terms\n"
        "of pin names and roles, not coordinates.\n\n"
        "The output is a structured text summary of the IR.\n"
    )
    assert tool.parameters == {
        "properties": {},
        "title": "sch_get_circuit_irArguments",
        "type": "object",
    }


def test_registration_preserves_headless_metadata() -> None:
    server, _service = _registered()
    tool = server._tool_manager.list_tools()[0]
    metadata = get_tool_metadata(tool.name)

    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
    assert tool.annotations is None


def test_registration_delegates_and_preserves_ten_second_cache() -> None:
    server, service = _registered()
    tool = server._tool_manager.list_tools()[0]

    assert tool.fn() == "summary-1"
    assert tool.fn() == "summary-1"
    assert service.calls == 1
