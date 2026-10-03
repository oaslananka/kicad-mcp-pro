from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType, SimpleNamespace

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.manufacturing_test_plan")
    assert spec is not None, "Manufacturing test-plan adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.manufacturing_test_plan")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, bool]] = []

    def create(
        self, intent: object, *, output_path: str = "", confirm_overwrite: bool = False
    ) -> str:
        self.calls.append((intent, output_path, confirm_overwrite))
        return "generated-test-plan"


def test_registration_preserves_public_signature_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-test-plan-registration")
    service = FakeService()
    intent = SimpleNamespace()

    adapter.register(
        server,
        adapter.ManufacturingTestPlanDependencies(
            service=service,
            load_design_intent=lambda: intent,
        ),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["mfg_generate_test_plan"]
    tool = tools[0]
    assert (
        str(inspect.signature(tool.fn))
        == "(output_path: 'str' = '', confirm_overwrite: 'bool' = False) -> 'str'"
    )
    assert "Generate a bring-up test plan from the project design intent." in (
        tool.fn.__doc__ or ""
    )

    metadata = get_tool_metadata("mfg_generate_test_plan")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    result = tool.fn(output_path="bringup/test_plan.md", confirm_overwrite=True)
    assert result == "generated-test-plan"
    assert service.calls == [(intent, "bringup/test_plan.md", True)]
