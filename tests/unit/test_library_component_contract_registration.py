from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata

DESCRIPTION = """Verify a placed component's symbol, footprint, and pins actually match.

For the given schematic reference designator this checks, entirely from
local project files (no network access):

- symbol pin count vs footprint connectable pad count
- pin numbers vs pad numbers
- footprint courtyard / fabrication / silkscreen completeness
- 3D model presence (advisory)
- datasheet evidence (advisory; never auto-filled)

Returns a JSON object with a ``status`` of PASS / WARN / FAIL and a list
of per-check ``findings``. FAIL marks a structural contract violation,
WARN marks a quality/completeness smell, and INFO is advisory evidence
that never changes the overall status."""


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.library_component_contract")
    assert spec is not None, "Library component-contract adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.library_component_contract")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def verify(self, reference: str) -> str:
        self.calls.append(reference)
        return "verified"


def test_registration_preserves_exact_contract_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("library-component-contract-test")
    service = FakeService()
    adapter.register(server, adapter.LibraryComponentContractDependencies(service=service))
    tools = server._tool_manager.list_tools()

    assert [tool.name for tool in tools] == ["lib_verify_component_contract"]
    tool = tools[0]
    assert tool.description == DESCRIPTION
    assert tool.parameters == {
        "properties": {"reference": {"title": "Reference", "type": "string"}},
        "required": ["reference"],
        "title": "lib_verify_component_contractArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("lib_verify_component_contract")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
    assert tool.fn(" R1 ") == "verified"
    assert service.calls == [" R1 "]


def test_library_root_preserves_component_contract_registration_order() -> None:
    from kicad_mcp.tools.library import register

    server = FastMCP("library-component-contract-order-test")
    register(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name
        in {
            "lib_get_footprint_3d_model",
            "lib_verify_component_contract",
            "lib_assign_footprint",
        }
    ]
    assert relevant == [
        "lib_get_footprint_3d_model",
        "lib_verify_component_contract",
        "lib_assign_footprint",
    ]
