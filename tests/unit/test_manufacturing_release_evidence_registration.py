from __future__ import annotations

import importlib
import importlib.util
import json
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.manufacturing_release_evidence")
    assert spec is not None, "Manufacturing release-evidence adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.manufacturing_release_evidence")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def create(self, context: object, **kwargs: object) -> str:
        self.calls.append((context, kwargs))
        return json.dumps({"verdict": "release_approved", "evidence_path": None})


def test_registration_preserves_public_release_evidence_descriptor() -> None:
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
    tool = tools[0]
    assert list(tool.parameters["properties"]) == [
        "output_path",
        "product_domain",
        "voltage_v",
        "waive_missing_artifacts",
        "dry_run",
    ]
    assert tool.parameters["properties"]["product_domain"]["default"] == "selv"
    assert tool.parameters["properties"]["dry_run"]["default"] is False
    metadata = get_tool_metadata("mfg_create_release_evidence")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_delegates_all_public_arguments_without_schema_change() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-release-evidence-delegation")
    service = FakeService()
    context = object()
    adapter.register(
        server,
        adapter.ManufacturingReleaseEvidenceDependencies(
            service=service,
            context_provider=lambda: context,
        ),
    )
    tool = server._tool_manager.list_tools()[0]

    result = tool.fn(
        output_path="ignored-by-existing-contract",
        product_domain="hazardous_mains",
        voltage_v=230.0,
        waive_missing_artifacts=True,
        dry_run=True,
    )

    assert json.loads(result)["verdict"] == "release_approved"
    assert service.calls == [
        (
            context,
            {
                "output_path": "ignored-by-existing-contract",
                "product_domain": "hazardous_mains",
                "voltage_v": 230.0,
                "waive_missing_artifacts": True,
                "dry_run": True,
            },
        )
    ]
