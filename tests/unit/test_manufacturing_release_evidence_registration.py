from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.manufacturing_release_evidence")
    assert spec is not None, "Manufacturing release-evidence adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.manufacturing_release_evidence")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create_evidence(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "evidence-result"


def test_registration_preserves_release_evidence_tool_contract() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-release-evidence-registration")
    service = FakeService()
    context = object()

    adapter.register(
        server,
        adapter.ManufacturingReleaseEvidenceDependencies(
            service=service,
            context_provider=lambda: context,
        ),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["mfg_create_release_evidence"]
    metadata = get_tool_metadata("mfg_create_release_evidence")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    result = tools[0].fn(
        output_path="ignored-for-compat",
        product_domain="hazardous_mains",
        voltage_v=230.0,
        waive_missing_artifacts=True,
        dry_run=True,
    )

    assert result == "evidence-result"
    assert service.calls == [
        {
            "context": context,
            "output_path": "ignored-for-compat",
            "product_domain": "hazardous_mains",
            "voltage_v": 230.0,
            "waive_missing_artifacts": True,
            "dry_run": True,
        }
    ]
