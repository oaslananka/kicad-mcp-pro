from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata

NAMES = [
    "lib_list_libraries",
    "lib_search_symbols",
    "lib_get_symbol_info",
    "lib_search_footprints",
    "lib_list_footprints",
    "lib_rebuild_index",
    "lib_get_footprint_info",
    "lib_get_footprint_3d_model",
]


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.library_catalog")
    assert spec is not None, "Library catalog adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.library_catalog")


class FakeCatalogService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def list_libraries(self) -> str:
        self.calls.append(("libraries",))
        return "libraries"

    def search_symbols(
        self, query: str, library_filter: str = "", page: int = 1, page_size: int = 50
    ) -> str:
        self.calls.append(("symbols", query, library_filter, page, page_size))
        return "symbols"

    def get_symbol_info(self, library: str, symbol_name: str) -> str:
        self.calls.append(("symbol", library, symbol_name))
        return "symbol"

    def search_footprints(
        self, query: str, library_filter: str = "", page: int = 1, page_size: int = 50
    ) -> str:
        self.calls.append(("footprints", query, library_filter, page, page_size))
        return "footprints"

    def list_footprints(self, library: str) -> str:
        self.calls.append(("footprint-list", library))
        return "footprint-list"

    def rebuild_index(self) -> str:
        self.calls.append(("rebuild",))
        return "rebuild"

    def get_footprint_info(self, library: str, footprint: str) -> str:
        self.calls.append(("footprint", library, footprint))
        return "footprint"

    def get_footprint_3d_model(self, library: str, footprint: str) -> str:
        self.calls.append(("model", library, footprint))
        return "model"


def _registered() -> tuple[FastMCP, FakeCatalogService]:
    adapter = _adapter()
    server = FastMCP("library-catalog-test")
    service = FakeCatalogService()
    adapter.register(server, adapter.LibraryCatalogDependencies(service=service))
    return server, service


def test_registration_preserves_exact_names_descriptions_schemas_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    assert list(tools) == NAMES
    assert (
        tools["lib_list_libraries"].description == "List configured symbol and footprint libraries."
    )
    assert tools["lib_search_symbols"].description == (
        "Search symbol libraries by name, description, or keywords.\n\n"
        "The query is split into whitespace-separated terms. A symbol matches when\n"
        "EVERY term is found (case-insensitive) in any of its name, description, or\n"
        "keywords (AND across terms, OR across fields). A single-term query behaves\n"
        "as a plain case-insensitive substring match.\n\n"
        "Parameters\n----------\nquery : str\n"
        "    Search terms. Multiple whitespace-separated terms are matched with AND\n"
        "    semantics; a single term is a case-insensitive substring match.\n"
        "library_filter : str\n    Optional library name to narrow the search.\n"
        "page : int\n    Page number (1-based). Default 1.\n"
        "page_size : int\n    Results per page. Default 50, max 500.\n"
    )
    assert tools["lib_search_symbols"].parameters == {
        "properties": {
            "query": {"title": "Query", "type": "string"},
            "library_filter": {"default": "", "title": "Library Filter", "type": "string"},
            "page": {"default": 1, "title": "Page", "type": "integer"},
            "page_size": {"default": 50, "title": "Page Size", "type": "integer"},
        },
        "required": ["query"],
        "title": "lib_search_symbolsArguments",
        "type": "object",
    }
    assert tools["lib_get_symbol_info"].parameters == {
        "properties": {
            "library": {"title": "Library", "type": "string"},
            "symbol_name": {"title": "Symbol Name", "type": "string"},
        },
        "required": ["library", "symbol_name"],
        "title": "lib_get_symbol_infoArguments",
        "type": "object",
    }
    assert tools["lib_search_footprints"].parameters["title"] == "lib_search_footprintsArguments"
    assert tools["lib_list_footprints"].parameters["title"] == "lib_list_footprintsArguments"
    assert tools["lib_rebuild_index"].parameters == {
        "properties": {},
        "title": "lib_rebuild_indexArguments",
        "type": "object",
    }
    for name in NAMES:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_registration_preserves_delegation_defaults_and_symbol_search_cache() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    assert tools["lib_list_libraries"].fn() == "libraries"
    assert tools["lib_search_symbols"].fn("R") == "symbols"
    assert tools["lib_search_symbols"].fn("R") == "symbols"
    assert tools["lib_get_symbol_info"].fn("Device", "R") == "symbol"
    assert tools["lib_search_footprints"].fn("0805") == "footprints"
    assert tools["lib_list_footprints"].fn("Resistor_SMD") == "footprint-list"
    assert tools["lib_rebuild_index"].fn() == "rebuild"
    assert tools["lib_get_footprint_info"].fn("Resistor_SMD", "R_0805") == "footprint"
    assert tools["lib_get_footprint_3d_model"].fn("Resistor_SMD", "R_0805") == "model"
    assert service.calls == [
        ("libraries",),
        ("symbols", "R", "", 1, 50),
        ("symbol", "Device", "R"),
        ("footprints", "0805", "", 1, 50),
        ("footprint-list", "Resistor_SMD"),
        ("rebuild",),
        ("footprint", "Resistor_SMD", "R_0805"),
        ("model", "Resistor_SMD", "R_0805"),
    ]


def test_library_root_preserves_catalog_registration_order() -> None:
    from kicad_mcp.tools.library import register

    server = FastMCP("library-catalog-order-test")
    register(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [name for name in names if name in {*NAMES, "lib_verify_component_contract"}]
    assert relevant == [*NAMES, "lib_verify_component_contract"]
