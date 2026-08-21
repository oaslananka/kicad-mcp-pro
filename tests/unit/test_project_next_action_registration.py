from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.project.next_action import ProjectNextActionPayload


class FakeNextActionService:
    def __init__(self) -> None:
        self.calls = 0

    def next_action(self) -> ProjectNextActionPayload:
        self.calls += 1
        return ProjectNextActionPayload(text="next", status="PASS")


def test_next_action_registration_preserves_contract_and_delegates() -> None:
    from kicad_mcp.tools.project_next_action import ProjectNextActionDependencies, register

    mcp = FastMCP("project-next-action-test")
    service = FakeNextActionService()
    register(mcp, ProjectNextActionDependencies(service=service))
    tools = mcp._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["project_get_next_action"]
    tool = tools[0]
    payload = tool.fn()
    assert payload.text == "next"
    assert service.calls == 1
    assert tool.parameters == {
        "properties": {},
        "title": "project_get_next_actionArguments",
        "type": "object",
    }
    assert (
        tool.description
        == "Return the next high-priority action derived from the current project gate."
    )
