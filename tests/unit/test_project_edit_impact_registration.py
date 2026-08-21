from __future__ import annotations

from mcp.server.fastmcp import FastMCP


class FakeEditImpactService:
    def __init__(self) -> None:
        self.assess_calls: list[str] = []
        self.revalidate_calls: list[tuple[str, str, str]] = []

    def assess(self, baseline_spec_json: str = "") -> str:
        self.assess_calls.append(baseline_spec_json)
        return "impact-result"

    def revalidate(
        self,
        baseline_spec_json: str = "",
        manufacturer: str = "",
        tier: str = "",
    ) -> str:
        self.revalidate_calls.append((baseline_spec_json, manufacturer, tier))
        return "revalidate-result"


def test_edit_impact_registration_preserves_contract_and_delegates() -> None:
    from kicad_mcp.tools.project_edit_impact import ProjectEditImpactDependencies, register

    mcp = FastMCP("project-edit-impact-test")
    service = FakeEditImpactService()
    register(mcp, ProjectEditImpactDependencies(service=service))

    tools = mcp._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["project_assess_edit_impact"]
    tool = tools[0]
    assert tool.fn() == "impact-result"
    assert tool.fn('{"manufacturer":"ACME"}') == "impact-result"
    assert service.assess_calls == ["", '{"manufacturer":"ACME"}']
    baseline = tool.parameters["properties"]["baseline_spec_json"]
    assert baseline["default"] == ""
    assert tool.parameters.get("required") is None
    assert tool.description == (
        "Scope re-validation after an edit: semantic-diff the design intent and report\n"
        "which gates must re-run.\n\n"
        "Compares a baseline design spec — the declared/saved intent, or an explicit\n"
        "baseline passed as ``baseline_spec_json`` — against the intent inferred from the\n"
        "current board, then maps each change to the gates it can invalidate. Re-run only\n"
        "the impacted gates and keep the rest as already-proven. Use after editing an\n"
        "existing project so a small change does not force a full re-validation."
    )


def test_edit_revalidation_registration_preserves_contract_and_delegates() -> None:
    from kicad_mcp.tools.project_edit_revalidation import (
        ProjectEditRevalidationDependencies,
        register,
    )

    mcp = FastMCP("project-edit-revalidation-test")
    service = FakeEditImpactService()
    register(mcp, ProjectEditRevalidationDependencies(service=service))

    tools = mcp._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["project_revalidate_after_edit"]
    tool = tools[0]
    assert tool.fn() == "revalidate-result"
    assert tool.fn("{}", "JLCPCB", "standard") == "revalidate-result"
    assert service.revalidate_calls == [("", "", ""), ("{}", "JLCPCB", "standard")]
    properties = tool.parameters["properties"]
    assert properties["baseline_spec_json"]["default"] == ""
    assert properties["manufacturer"]["default"] == ""
    assert properties["tier"]["default"] == ""
    assert tool.parameters.get("required") is None
    assert tool.description == (
        "Re-run only the gates an edit could have invalidated; prove the rest preserved.\n\n"
        "Computes the semantic intent diff (like ``project_assess_edit_impact``), then\n"
        "actually re-runs only the impacted project gates -- skipping unaffected ones -- so\n"
        "a small edit does not force a full re-validation. Impacted analysis categories that\n"
        "the sign-off gate does not cover (signal integrity, power, thermal, EMC) are listed\n"
        "with the tool to re-run for each."
    )
