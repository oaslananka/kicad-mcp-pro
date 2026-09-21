from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.project.design_spec import (
    ProjectImportDesignSpecPayload,
    ProjectSpecPayload,
    ProjectSpecValidationPayload,
)
from kicad_mcp.tools.design_intent_state import ProjectDesignIntent
from kicad_mcp.tools.metadata import get_tool_metadata

NAMES = [
    "project_set_design_intent",
    "project_import_design_spec",
    "project_get_design_intent",
    "project_get_design_spec",
    "project_infer_design_spec",
    "project_validate_design_spec",
    "project_generate_design_prompt",
]


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.project_design_spec")
    assert spec is not None, "Project design spec FastMCP adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.project_design_spec")


class FakeProjectDesignSpecService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def set_design_intent(self, **kwargs: object) -> str:
        self.calls.append(("set_design_intent", kwargs))
        return "set-intent-result"

    def import_design_spec(
        self,
        path: str | None = None,
        markdown: str | None = None,
        strict: bool = True,
        dry_run: bool = True,
    ) -> ProjectImportDesignSpecPayload:
        self.calls.append(("import_design_spec", (path, markdown, strict, dry_run)))
        return ProjectImportDesignSpecPayload(
            text="import-result",
            written=False,
            path="",
            parsed=ProjectDesignIntent(),
        )

    def get_design_intent(self) -> str:
        self.calls.append(("get_design_intent", ()))
        return "get-intent-result"

    def get_design_spec(self) -> ProjectSpecPayload:
        self.calls.append(("get_design_spec", ()))
        return ProjectSpecPayload(text="spec-result")

    def infer_design_spec(self) -> ProjectSpecPayload:
        self.calls.append(("infer_design_spec", ()))
        return ProjectSpecPayload(text="infer-result")

    def validate_design_spec(self) -> ProjectSpecValidationPayload:
        self.calls.append(("validate_design_spec", ()))
        return ProjectSpecValidationPayload(text="validate-result", valid=True)

    def generate_design_prompt(
        self,
        circuit_description: str = "",
        target_fab: str = "",
    ) -> str:
        self.calls.append(("generate_design_prompt", (circuit_description, target_fab)))
        return "prompt-result"


def test_registration_preserves_names_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("project-design-spec-test")
    service = FakeProjectDesignSpecService()
    adapter.register(server, adapter.ProjectDesignSpecDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == NAMES
    by_name = {tool.name: tool for tool in tools}

    assert by_name["project_get_design_intent"].fn() == "get-intent-result"
    assert by_name["project_get_design_spec"].fn().text == "spec-result"
    assert by_name["project_infer_design_spec"].fn().text == "infer-result"
    assert by_name["project_validate_design_spec"].fn().text == "validate-result"

    for name in NAMES:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
