from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool

from kicad_mcp.project.reporting import DesignReportPayload
from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.project_reporting import ProjectReportingDependencies, register


class FakeReportingService:
    def __init__(self) -> None:
        self.trend_calls: list[tuple[str, int]] = []
        self.report_calls = 0

    def gate_trend(self, gate_name: str, last_n: int = 10) -> str:
        self.trend_calls.append((gate_name, last_n))
        return "trend-result"

    def design_report(self) -> DesignReportPayload:
        self.report_calls += 1
        return DesignReportPayload(text="report-result", gate_status="PASS")


def _descriptor(tool: Tool) -> dict[str, object]:
    metadata = get_tool_metadata(tool.name)
    annotations = tool.annotations.model_dump(mode="json") if tool.annotations is not None else None
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
        "output_schema": tool.output_schema,
        "annotations": annotations,
        "meta": tool.meta,
        "headless_compatible": None if metadata is None else metadata.headless_compatible,
    }


EXPECTED_DESCRIPTORS = [
    {
        "name": "project_gate_trend",
        "description": "Return persisted quality-gate trend history for one gate.",
        "parameters": {
            "properties": {
                "gate_name": {"title": "Gate Name", "type": "string"},
                "last_n": {"default": 10, "title": "Last N", "type": "integer"},
            },
            "required": ["gate_name"],
            "title": "project_gate_trendArguments",
            "type": "object",
        },
        "output_schema": {
            "properties": {"result": {"title": "Result", "type": "string"}},
            "required": ["result"],
            "title": "project_gate_trendOutput",
            "type": "object",
        },
        "annotations": None,
        "meta": None,
        "headless_compatible": True,
    },
    {
        "name": "project_design_report",
        "description": (
            "Generate a comprehensive design-status report.\n\n"
            "Combines intent summary, v2 spec richness, project gate evaluation, and\n"
            "a prioritised list of next steps into a single structured report.\n"
            "This is the recommended first call after opening a project to understand\n"
            "its current state.\n"
        ),
        "parameters": {
            "properties": {},
            "title": "project_design_reportArguments",
            "type": "object",
        },
        "output_schema": {
            "description": (
                "Comprehensive design-status report combining intent, gates, and "
                "recommended actions."
            ),
            "properties": {
                "compliance_count": {
                    "default": 0,
                    "title": "Compliance Count",
                    "type": "integer",
                },
                "gate_status": {"title": "Gate Status", "type": "string"},
                "has_mechanical_constraint": {
                    "default": False,
                    "title": "Has Mechanical Constraint",
                    "type": "boolean",
                },
                "intent_source": {
                    "default": "none",
                    "enum": ["project_spec", "legacy_design_intent", "none"],
                    "title": "Intent Source",
                    "type": "string",
                },
                "interfaces_count": {
                    "default": 0,
                    "title": "Interfaces Count",
                    "type": "integer",
                },
                "next_tool": {"default": "", "title": "Next Tool", "type": "string"},
                "power_rails_count": {
                    "default": 0,
                    "title": "Power Rails Count",
                    "type": "integer",
                },
                "text": {"title": "Text", "type": "string"},
            },
            "required": ["text", "gate_status"],
            "title": "DesignReportPayload",
            "type": "object",
        },
        "annotations": None,
        "meta": None,
        "headless_compatible": True,
    },
]


def _registered() -> tuple[FastMCP, FakeReportingService]:
    mcp = FastMCP("project-reporting-test")
    service = FakeReportingService()
    register(mcp, ProjectReportingDependencies(service=service))
    return mcp, service


def test_registration_preserves_exact_bare_contract_and_local_order() -> None:
    mcp, _service = _registered()
    tools = mcp._tool_manager.list_tools()

    assert [_descriptor(tool) for tool in tools] == EXPECTED_DESCRIPTORS


def test_registration_delegates_trend_arguments_exactly() -> None:
    mcp, service = _registered()
    trend = mcp._tool_manager.list_tools()[0]

    assert trend.fn("Placement", 7) == "trend-result"
    assert service.trend_calls == [("Placement", 7)]


def test_registration_delegates_design_report_without_arguments() -> None:
    mcp, service = _registered()
    report = mcp._tool_manager.list_tools()[1]

    result = report.fn()

    assert isinstance(result, DesignReportPayload)
    assert result.text == "report-result"
    assert service.report_calls == 1
