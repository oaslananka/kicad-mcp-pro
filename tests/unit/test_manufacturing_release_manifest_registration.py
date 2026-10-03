from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType, SimpleNamespace

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.manufacturing_release_manifest")
    assert spec is not None, "Manufacturing release-manifest adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.manufacturing_release_manifest")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, str]] = []

    def create_manifest(self, *, intent: object, context: object, output_path: str = "") -> str:
        self.calls.append((intent, context, output_path))
        return "manifest-result"


def test_registration_preserves_manifest_tool_contract() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-release-manifest-registration")
    service = FakeService()
    intent = SimpleNamespace(name="intent")
    context = SimpleNamespace(name="context")
    adapter.register(
        server,
        adapter.ManufacturingReleaseManifestDependencies(
            service=service,
            intent_provider=lambda: intent,
            context_provider=lambda: context,
        ),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["mfg_generate_release_manifest"]
    tool = tools[0]
    assert tool.fn(output_path="custom") == "manifest-result"
    assert service.calls == [(intent, context, "custom")]

    metadata = get_tool_metadata("mfg_generate_release_manifest")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_preserves_default_output_path() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-release-manifest-default")
    service = FakeService()
    adapter.register(
        server,
        adapter.ManufacturingReleaseManifestDependencies(
            service=service,
            intent_provider=lambda: object(),
            context_provider=lambda: object(),
        ),
    )

    tool = server._tool_manager.list_tools()[0]
    assert tool.fn() == "manifest-result"
    assert service.calls[0][2] == ""


def test_registration_formats_prerequisite_errors_without_changing_public_behavior() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-release-manifest-error")

    class FailingService:
        def create_manifest(self, **_kwargs: object) -> str:
            raise adapter.ReleaseManifestPrerequisiteError("missing release inputs")

    adapter.register(
        server,
        adapter.ManufacturingReleaseManifestDependencies(
            service=FailingService(),
            intent_provider=lambda: object(),
            context_provider=lambda: object(),
        ),
    )

    tool = server._tool_manager.list_tools()[0]
    assert tool.fn() == "missing release inputs"
