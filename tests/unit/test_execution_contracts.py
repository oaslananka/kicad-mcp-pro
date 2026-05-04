from __future__ import annotations

import pytest

from kicad_mcp.execution.contracts import tool_contract
from kicad_mcp.models.tool_result import ToolResult


@pytest.mark.anyio
async def test_tool_contract_preserves_tool_result() -> None:
    @tool_contract(human_gate=True)
    async def wrapped() -> ToolResult:
        return ToolResult.success("custom_name")

    result = await wrapped()

    assert result.ok is True
    assert result.tool_name == "wrapped"
    assert result.human_gate_required is True
    assert result.duration_ms is not None


@pytest.mark.anyio
async def test_tool_contract_wraps_dict_result() -> None:
    @tool_contract(tool_name="legacy_tool")
    async def wrapped() -> dict[str, object]:
        return {"ok": True, "changed": True, "payload": 1}

    result = await wrapped()

    assert result.ok is True
    assert result.changed is True
    assert result.tool_name == "legacy_tool"
    assert result.extra["payload"] == 1


@pytest.mark.anyio
async def test_tool_contract_wraps_raw_result_and_dry_run() -> None:
    @tool_contract(tool_name="raw_tool")
    async def wrapped(*, dry_run: bool = False) -> str:
        return "done"

    result = await wrapped(dry_run=True)

    assert result.ok is True
    assert result.changed is False
    assert result.dry_run is True
    assert result.extra["raw"] == "done"


@pytest.mark.anyio
async def test_tool_contract_captures_exception() -> None:
    @tool_contract(tool_name="failing_tool")
    async def wrapped() -> ToolResult:
        raise RuntimeError("boom")

    result = await wrapped()

    assert result.ok is False
    assert result.errors == ["boom"]
    assert result.tool_name == "failing_tool"


@pytest.mark.anyio
async def test_tool_contract_records_source_file_args(tmp_path) -> None:
    source = tmp_path / "demo.kicad_sch"
    source.write_text("content", encoding="utf-8")

    @tool_contract(writes_files=True, source_file_args=["sch_path"])
    async def wrapped(sch_path: str) -> dict[str, object]:
        return {"ok": True, "changed": True}

    result = await wrapped(str(source))

    assert result.extra["contract_source_files"] == [str(source)]
