from __future__ import annotations

from mcp.server.fastmcp import FastMCP


class FakeWorkflowService:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def render(self, completed_phases: list[str]) -> str:
        self.calls.append(completed_phases)
        return "workflow-result"


def test_registration_preserves_workflow_tool_contract_and_delegation() -> None:
    from kicad_mcp.tools.project_workflow import ProjectWorkflowDependencies, register

    mcp = FastMCP("project-workflow-test")
    service = FakeWorkflowService()

    register(mcp, ProjectWorkflowDependencies(service=service))

    tools = mcp._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["project_design_workflow"]
    tool = tools[0]
    assert tool.fn() == "workflow-result"
    assert service.calls == [[]]
    assert tool.fn(["requirements_review"]) == "workflow-result"
    assert service.calls == [[], ["requirements_review"]]
    completed = tool.parameters["properties"]["completed_phases"]
    assert completed["default"] is None
    assert tool.parameters.get("required") is None
    assert tool.description == (
        "Return the professional PCB design workflow as a typed phase state machine.\n\n"
        "Lays out the canonical Planner -> Builder -> Verifier -> Fixer -> Release\n"
        "sequence, with the high-level tool and the quality gates each phase must pass.\n"
        "Pass the phases already finished in ``completed_phases``; the tool marks them\n"
        "COMPLETE, reports the first remaining phase as READY (the current step) with\n"
        "its next action and gates, and flags when a human gate is required. Read-only\n"
        "and headless — use it to drive an autonomous design run step by step."
    )
