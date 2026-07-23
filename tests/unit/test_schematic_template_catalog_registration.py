# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_template_catalog import (
    SchematicTemplateCatalogDependencies,
    register,
)


class FakeTemplateCatalogService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def list_templates(self) -> str:
        self.calls.append(("list_templates", ()))
        return "listing"

    def template_info(self, template_name: str) -> str:
        self.calls.append(("template_info", (template_name,)))
        return "details"


def _registered() -> tuple[FastMCP, FakeTemplateCatalogService]:
    server = FastMCP("schematic-template-catalog-test")
    service = FakeTemplateCatalogService()
    register(server, SchematicTemplateCatalogDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"sch_list_templates", "sch_get_template_info"}
    assert tools["sch_list_templates"].description == (
        "List all available reference subcircuit templates.\n\n"
        "Templates are pre-wired subcircuit blueprints for common building blocks\n"
        "(buck converter, LDO, USB Type-C, MCU decoupling, Ethernet with magnetics).\n\n"
        "Call sch_get_template_info() for full parameter and placement details,\n"
        "then sch_instantiate_template() to add the subcircuit to the schematic.\n"
    )
    assert tools["sch_get_template_info"].description == (
        "Return full details for a subcircuit template.\n\n"
        "Args:\n"
        "    template_name: Template name as returned by sch_list_templates()\n"
        '        (e.g. ``"buck_converter_generic"``).\n\n'
        "Returns:\n"
        "    Structured template description including parameters, symbols,\n"
        "    nets, and placement hints.\n"
    )
    assert tools["sch_list_templates"].parameters == {
        "properties": {},
        "title": "sch_list_templatesArguments",
        "type": "object",
    }
    info_schema = tools["sch_get_template_info"].parameters
    assert info_schema["required"] == ["template_name"]
    assert info_schema["properties"] == {
        "template_name": {"title": "Template Name", "type": "string"}
    }


def test_registration_preserves_headless_metadata() -> None:
    server, _service = _registered()

    for tool in server._tool_manager.list_tools():
        metadata = get_tool_metadata(tool.name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False
        assert tool.annotations is None


def test_registration_delegates_all_calls() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_list_templates"].fn() == "listing"
    assert tools["sch_get_template_info"].fn(template_name="buck_converter_generic") == "details"
    assert service.calls == [
        ("list_templates", ()),
        ("template_info", ("buck_converter_generic",)),
    ]
