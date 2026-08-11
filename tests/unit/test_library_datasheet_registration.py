from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata, infer_tool_annotations


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.library_datasheet")
    assert spec is not None, "Library datasheet adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.library_datasheet")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_datasheet_url(self, library: str, symbol_name: str) -> str:
        self.calls.append((library, symbol_name))
        return "https://example.com/x.pdf"


def test_registration_preserves_exact_contract_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("library-datasheet-test")
    service = FakeService()
    adapter.register(server, adapter.LibraryDatasheetDependencies(service=service))
    tools = server._tool_manager.list_tools()

    assert [tool.name for tool in tools] == ["lib_get_datasheet_url"]
    tool = tools[0]
    assert tool.description == "Return a datasheet URL from the symbol library when available."
    assert tool.parameters == {
        "properties": {
            "library": {"title": "Library", "type": "string"},
            "symbol_name": {"title": "Symbol Name", "type": "string"},
        },
        "required": ["library", "symbol_name"],
        "title": "lib_get_datasheet_urlArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("lib_get_datasheet_url")
    assert metadata is not None
    annotations = infer_tool_annotations("lib_get_datasheet_url")
    assert annotations.readOnlyHint is True
    assert annotations.idempotentHint is True
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
    assert tool.fn("Device", "R") == "https://example.com/x.pdf"
    assert service.calls == [("Device", "R")]


def test_library_root_preserves_datasheet_registration_order() -> None:
    from kicad_mcp.tools.library import register

    server = FastMCP("library-datasheet-order-test")
    register(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name
        in {
            "lib_assign_footprint",
            "lib_create_custom_symbol",
            "lib_get_datasheet_url",
            "lib_search_components",
        }
    ]
    assert relevant == [
        "lib_assign_footprint",
        "lib_create_custom_symbol",
        "lib_get_datasheet_url",
        "lib_search_components",
    ]
