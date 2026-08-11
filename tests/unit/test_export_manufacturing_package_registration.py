from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Awaitable, Callable
from types import ModuleType

import pytest
from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_manufacturing_package")
    assert spec is not None, "Manufacturing package adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_manufacturing_package")


class FakeManufacturingPackageService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[object], str]] = []

    async def export(
        self,
        *,
        variant: str,
        approval_evidence_path: str,
        evaluate_project_gate: Callable[[], list[object]],
        render_gate_report: Callable[[list[object], str], str],
        report_progress: Callable[[int, int, str], Awaitable[None]],
    ) -> str:
        outcomes = evaluate_project_gate()
        rendered = render_gate_report(outcomes, "adapter-summary")
        await report_progress(5, 100, "adapter-progress")
        self.calls.append((variant, approval_evidence_path, outcomes, rendered))
        return "package-result"


def _registered() -> tuple[
    FastMCP, FakeManufacturingPackageService, list[tuple[object, int, int, str]]
]:
    adapter = _adapter()
    server = FastMCP("export-manufacturing-package-test")
    service = FakeManufacturingPackageService()
    progress_calls: list[tuple[object, int, int, str]] = []

    async def report_progress(ctx: object, current: int, total: int, message: str) -> None:
        progress_calls.append((ctx, current, total, message))

    adapter.register(
        server,
        adapter.ExportManufacturingPackageDependencies(
            service=service,
            report_progress=report_progress,
        ),
    )
    return server, service, progress_calls


def test_registration_preserves_exact_schema_description_and_metadata() -> None:
    server, _service, _progress = _registered()
    tools = server._tool_manager.list_tools()

    assert [tool.name for tool in tools] == ["export_manufacturing_package"]
    tool = tools[0]
    assert tool.description == "Generate the gated manufacturing release package."
    assert tool.parameters == {
        "properties": {
            "variant": {"default": "", "title": "Variant", "type": "string"},
            "approval_evidence_path": {
                "default": "",
                "title": "Approval Evidence Path",
                "type": "string",
            },
        },
        "title": "export_manufacturing_packageArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("export_manufacturing_package")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


@pytest.mark.anyio
async def test_registration_binds_validation_and_context_progress(monkeypatch) -> None:
    from kicad_mcp.tools import validation

    gate_values = [object()]
    monkeypatch.setattr(validation, "_evaluate_project_gate", lambda **_kwargs: gate_values)
    monkeypatch.setattr(
        validation,
        "_render_project_gate_report",
        lambda outcomes, *, summary=None: f"rendered::{len(outcomes)}::{summary}",
    )

    server, service, progress_calls = _registered()
    tool = server._tool_manager.list_tools()[0]
    result = await tool.fn(
        variant=" lite ",
        approval_evidence_path="approval.json",
        ctx=None,
    )

    assert result == "package-result"
    assert service.calls == [
        (" lite ", "approval.json", gate_values, "rendered::1::adapter-summary")
    ]
    assert progress_calls == [(None, 5, 100, "adapter-progress")]


def test_export_composition_root_preserves_final_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-manufacturing-package-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]

    assert names[-3:] == [
        "get_board_stats",
        "export_manufacturing_package",
        "pcb_export_stats",
    ]
