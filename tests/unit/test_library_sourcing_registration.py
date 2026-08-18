from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.models.verdict import VerdictReport
from kicad_mcp.tools.metadata import get_tool_metadata

NAMES = [
    "lib_search_components",
    "lib_get_component_details",
    "lib_check_sourcing_policy",
    "lib_assign_lcsc_to_symbol",
    "lib_get_bom_with_pricing",
    "lib_check_stock_availability",
    "lib_find_alternative_parts",
]


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.library_sourcing")
    assert spec is not None, "Library sourcing adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.library_sourcing")


class FakeSourcingService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def search_components(
        self,
        query: str | None = None,
        keyword: str | None = None,
        package: str = "",
        only_basic: bool = True,
        source: str = "jlcsearch",
        min_stock: int = 10,
        sort_by: str = "price",
        rohs_compliant: bool | None = None,
        lifecycle: str = "",
    ) -> str:
        self.calls.append(
            (
                "search",
                query,
                keyword,
                package,
                only_basic,
                source,
                min_stock,
                sort_by,
                rohs_compliant,
                lifecycle,
            )
        )
        return "search"

    def get_component_details(self, lcsc_code_or_mpn: str, source: str = "jlcsearch") -> str:
        self.calls.append(("details", lcsc_code_or_mpn, source))
        return "details"

    def check_sourcing_policy(
        self,
        lcsc_code_or_mpn: str,
        source: str = "jlcsearch",
        min_stock: int = 10,
        max_unit_price: float | None = None,
        allowed_lifecycle: list[str] | None = None,
        require_rohs: bool = False,
        approved_manufacturers: list[str] | None = None,
    ) -> VerdictReport:
        self.calls.append(
            (
                "policy",
                lcsc_code_or_mpn,
                source,
                min_stock,
                max_unit_price,
                allowed_lifecycle,
                require_rohs,
                approved_manufacturers,
            )
        )
        return VerdictReport.from_text_verdict(
            text="policy", summary="policy", verdict="PASS", source="test"
        )

    def assign_lcsc_to_symbol(self, reference: str, lcsc_code: str) -> str:
        self.calls.append(("assign", reference, lcsc_code))
        return "assign"

    def get_bom_with_pricing(self, quantity: int = 1, source: str = "jlcsearch") -> str:
        self.calls.append(("bom", quantity, source))
        return "bom"

    def check_stock_availability(
        self,
        refs: list[str] | None = None,
        source: str = "jlcsearch",
        mpns: list[str] | None = None,
    ) -> str:
        self.calls.append(("stock", refs, source, mpns))
        return "stock"

    def find_alternative_parts(
        self, lcsc_code: str, tolerance_percent: float = 10.0, source: str = "jlcsearch"
    ) -> str:
        self.calls.append(("alternatives", lcsc_code, tolerance_percent, source))
        return "alternatives"


def _registered() -> tuple[FastMCP, FakeSourcingService]:
    adapter = _adapter()
    server = FastMCP("library-sourcing-test")
    service = FakeSourcingService()
    adapter.register(server, adapter.LibrarySourcingDependencies(service=service))
    return server, service


def test_registration_preserves_names_order_and_headless_metadata() -> None:
    server, _service = _registered()
    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == NAMES
    for name in NAMES:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_registration_preserves_defaults_and_delegation() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["lib_search_components"].fn(keyword="LDO") == "search"
    assert tools["lib_get_component_details"].fn("C123") == "details"
    assert tools["lib_check_sourcing_policy"].fn("C123").verdict == "PASS"
    assert tools["lib_assign_lcsc_to_symbol"].fn("R1", "C123") == "assign"
    assert tools["lib_get_bom_with_pricing"].fn() == "bom"
    assert tools["lib_check_stock_availability"].fn() == "stock"
    assert tools["lib_find_alternative_parts"].fn("C123") == "alternatives"

    assert service.calls == [
        ("search", None, "LDO", "", True, "jlcsearch", 10, "price", None, ""),
        ("details", "C123", "jlcsearch"),
        ("policy", "C123", "jlcsearch", 10, None, None, False, None),
        ("assign", "R1", "C123"),
        ("bom", 1, "jlcsearch"),
        ("stock", None, "jlcsearch", None),
        ("alternatives", "C123", 10.0, "jlcsearch"),
    ]
