# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_layout_automation import (
    SchematicLayoutAutomationDependencies,
    register,
)


class FakeLayoutAutomationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def auto_place_symbols(
        self,
        symbol_list: list[str] | None = None,
        strategy: str = "cluster",
    ) -> str:
        self.calls.append(
            (
                "auto_place_symbols",
                {"symbol_list": symbol_list, "strategy": strategy},
            )
        )
        return "symbols"

    def autoplace_fields(
        self,
        references: list[str] | None = None,
        dry_run: bool = False,
    ) -> str:
        self.calls.append(
            (
                "autoplace_fields",
                {"references": references, "dry_run": dry_run},
            )
        )
        return "fields"

    def fix_readability(self, max_passes: int = 3) -> str:
        self.calls.append(("fix_readability", {"max_passes": max_passes}))
        return "readability"

    def auto_place_functional(
        self,
        symbol_list: list[str] | None = None,
        anchor_ref: str | list[str] | None = None,
    ) -> str:
        self.calls.append(
            (
                "auto_place_functional",
                {"symbol_list": symbol_list, "anchor_ref": anchor_ref},
            )
        )
        return "functional"


def _registered() -> tuple[FastMCP, FakeLayoutAutomationService]:
    server = FastMCP("schematic-layout-automation-test")
    service = FakeLayoutAutomationService()
    register(server, SchematicLayoutAutomationDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_auto_place_symbols",
        "sch_autoplace_fields",
        "sch_fix_readability",
        "sch_auto_place_functional",
    }
    assert tools["sch_auto_place_symbols"].parameters == {
        "properties": {
            "symbol_list": {
                "anyOf": [
                    {"items": {"type": "string"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Symbol List",
            },
            "strategy": {"default": "cluster", "title": "Strategy", "type": "string"},
        },
        "title": "sch_auto_place_symbolsArguments",
        "type": "object",
    }
    assert tools["sch_autoplace_fields"].parameters["properties"]["dry_run"]["default"] is False
    assert tools["sch_fix_readability"].parameters == {
        "properties": {"max_passes": {"default": 3, "title": "Max Passes", "type": "integer"}},
        "title": "sch_fix_readabilityArguments",
        "type": "object",
    }
    assert tools["sch_auto_place_functional"].parameters["properties"]["anchor_ref"] == {
        "anyOf": [
            {"type": "string"},
            {"items": {"type": "string"}, "type": "array"},
            {"type": "null"},
        ],
        "default": None,
        "title": "Anchor Ref",
    }
    for name, tool in tools.items():
        assert tool.output_schema == {
            "properties": {"result": {"title": "Result", "type": "string"}},
            "required": ["result"],
            "title": f"{name}Output",
            "type": "object",
        }
        assert tool.annotations is None


def test_registration_preserves_descriptions() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_auto_place_symbols"].description == (
        "Place selected references with a deterministic cluster, linear, star, or grid layout.\n\n"
        "Unlike the legacy behaviour, this version reads all already-placed symbols\n"
        "first and avoids placing new symbols on top of them.  Fixed/already-placed\n"
        "symbols that are not in ``symbol_list`` are treated as immovable obstacles.\n"
    )
    assert "Mirrors KiCad's ``autoplace_fields``" in tools["sch_autoplace_fields"].description
    assert (
        "Iteratively fix schematic readability defects" in tools["sch_fix_readability"].description
    )
    assert "semantically meaningful zones" in tools["sch_auto_place_functional"].description


def test_registration_preserves_headless_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert get_tool_metadata("sch_auto_place_symbols") is None
    for name in ("sch_autoplace_fields", "sch_fix_readability", "sch_auto_place_functional"):
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False
        assert tools[name].annotations is None


def test_registration_delegates_exact_arguments() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_auto_place_symbols"].fn(symbol_list=["R1"], strategy="grid") == "symbols"
    assert tools["sch_autoplace_fields"].fn(references=["R1"], dry_run=True) == "fields"
    assert tools["sch_fix_readability"].fn(max_passes=4) == "readability"
    assert (
        tools["sch_auto_place_functional"].fn(symbol_list=["U1"], anchor_ref=["J1"]) == "functional"
    )

    assert service.calls == [
        ("auto_place_symbols", {"symbol_list": ["R1"], "strategy": "grid"}),
        ("autoplace_fields", {"references": ["R1"], "dry_run": True}),
        ("fix_readability", {"max_passes": 4}),
        ("auto_place_functional", {"symbol_list": ["U1"], "anchor_ref": ["J1"]}),
    ]
