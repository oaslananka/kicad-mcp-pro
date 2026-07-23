# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_template_instantiation import (
    SchematicTemplateInstantiationDependencies,
    register,
)


class FakeTemplateInstantiationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def instantiate(
        self,
        template_name: str,
        prefix: str = "",
        params: dict[str, object] | None = None,
    ) -> str:
        self.calls.append((template_name, prefix, params))
        return "plan"


def _registered() -> tuple[FastMCP, FakeTemplateInstantiationService]:
    server = FastMCP("schematic-template-instantiation-test")
    service = FakeTemplateInstantiationService()
    register(server, SchematicTemplateInstantiationDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_name_description_and_schema() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"sch_instantiate_template"}
    tool = tools["sch_instantiate_template"]
    assert tool.description == (
        "Instantiate a subcircuit template — returns a structured action plan.\n\n"
        "This tool returns a structured plan describing the symbols, connections,\n"
        "and part-search steps needed to add the subcircuit to the schematic.\n"
        "It does NOT directly edit the schematic (use the plan as a guide for\n"
        "calling sch_add_symbol, sch_add_wire, lib_recommend_part, etc.).\n\n"
        "Args:\n"
        "    template_name: Template name (from sch_list_templates()).\n"
        '    prefix: Reference prefix applied to all template refs (e.g. ``"PWR_"``\n'
        "        produces ``PWR_U1``, ``PWR_L1``, etc.).\n"
        '    params: Dict of parameter overrides (e.g. ``{"vout_v": 5.0}``).\n\n'
        "Returns:\n"
        "    Step-by-step instantiation plan in markdown format.\n"
    )
    assert tool.parameters == {
        "properties": {
            "template_name": {"title": "Template Name", "type": "string"},
            "prefix": {"default": "", "title": "Prefix", "type": "string"},
            "params": {
                "anyOf": [
                    {"additionalProperties": True, "type": "object"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Params",
            },
        },
        "required": ["template_name"],
        "title": "sch_instantiate_templateArguments",
        "type": "object",
    }


def test_registration_preserves_headless_metadata_and_annotations() -> None:
    server, _service = _registered()
    tool = server._tool_manager.list_tools()[0]
    metadata = get_tool_metadata(tool.name)

    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
    assert tool.annotations is None


def test_registration_delegates_defaults_and_arguments() -> None:
    server, service = _registered()
    tool = server._tool_manager.list_tools()[0]

    assert tool.fn(template_name="minimal") == "plan"
    assert (
        tool.fn(
            template_name="buzzer_nmos_driver",
            prefix="AUD_",
            params={"supply_v": 5.0},
        )
        == "plan"
    )
    assert service.calls == [
        ("minimal", "", None),
        ("buzzer_nmos_driver", "AUD_", {"supply_v": 5.0}),
    ]
