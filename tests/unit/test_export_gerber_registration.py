from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

import pytest
from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_gerber")
    assert spec is not None, "Gerber export adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_gerber")


class FakeGerberService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None, str | None]] = []

    def export(
        self,
        output_subdir: str = "gerber",
        layers: list[str] | None = None,
        variant_name: str | None = None,
    ) -> str:
        self.calls.append((output_subdir, layers, variant_name))
        return "raw:gerber"


async def _registered():
    adapter = _adapter()
    server = FastMCP("export-gerber-test")
    service = FakeGerberService()
    progress_calls: list[tuple[object, float, float, str]] = []

    async def report_progress(ctx: object, progress: float, total: float, message: str) -> None:
        progress_calls.append((ctx, progress, total, message))

    adapter.register(
        server,
        adapter.ExportGerberDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
            report_progress=report_progress,
        ),
    )
    return server, service, progress_calls


@pytest.mark.anyio
async def test_registration_preserves_exact_name_schema_description_and_metadata() -> None:
    server, _service, _progress = await _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_gerber"]
    assert tools["export_gerber"].description == "Export Gerber manufacturing files."
    assert tools["export_gerber"].parameters == {
        "properties": {
            "output_subdir": {"default": "gerber", "title": "Output Subdir", "type": "string"},
            "layers": {
                "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
                "default": None,
                "title": "Layers",
            },
        },
        "title": "export_gerberArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("export_gerber")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


@pytest.mark.anyio
async def test_registration_preserves_notice_progress_and_public_delegation() -> None:
    server, service, progress_calls = await _registered()
    tool = server._tool_manager.list_tools()[0]
    ctx = object()

    result = await tool.fn(output_subdir="fab", layers=["F.Cu"], ctx=ctx)

    assert result == "notice::raw:gerber"
    assert service.calls == [("fab", ["F.Cu"], None)]
    assert progress_calls == [
        (ctx, 5, 100, "Starting Gerber export..."),
        (ctx, 100, 100, "Gerber export complete."),
    ]


def test_export_composition_root_preserves_gerber_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-gerber-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [name for name in names if name in {"export_gerber", "export_drill", "export_bom"}]
    assert relevant == ["export_gerber", "export_drill", "export_bom"]
