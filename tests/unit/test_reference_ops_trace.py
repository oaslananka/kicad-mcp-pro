"""Strict tool call evidence and no-payload audit of reviewed MCP execution."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from mcp.server.context import ServerRequestContext
from mcp.types import CallToolResult

from kicad_mcp.config import reset_config
from kicad_mcp.evals.reference_ops_server import build_reference_ops_server
from kicad_mcp.evals.reference_ops_trace import (
    ReferenceOpsTrace,
    ReviewedOpsTraceMiddleware,
    configured_trace,
)


def _private_attempt(tmp_path: Path) -> Path:
    attempt = tmp_path / ".dev-tools/reference-agent-runs/stm32/v1/attempt-004"
    attempt.mkdir(parents=True, mode=0o700)
    attempt.chmod(0o700)
    return attempt


async def _run_reviewed_tool(path: Path) -> None:
    trace = ReferenceOpsTrace(path=path, attempt_id="attempt-004")
    try:
        server = build_reference_ops_server(phase_name="schematic")
        middleware = ReviewedOpsTraceMiddleware(trace)
        context = ServerRequestContext(
            session=None,
            lifespan_context=None,
            protocol_version="2026-07-28",
            method="tools/call",
            params={"name": "kicad_get_version", "arguments": {}},
        )

        async def invoke(_context: object) -> CallToolResult:
            return await server.call_tool("kicad_get_version", {})

        result = await middleware(context, invoke)
        assert result.is_error is False
    finally:
        trace.close()


def test_live_mcp_client_records_only_tool_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KICAD_MCP_PROFILE", "schematic_authoring")
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "write")
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "stdio")
    reset_config()
    try:
        path = _private_attempt(tmp_path) / "ops-mcp-trace.jsonl"
        asyncio.run(_run_reviewed_tool(path))
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [row["event_type"] for row in rows] == ["tool_call", "tool_result"]
        assert [row["sequence"] for row in rows] == [1, 2]
        assert [row["name"] for row in rows] == ["kicad_get_version"] * 2
        assert [row["status"] for row in rows] == ["started", "completed"]
        assert [row["details"]["request_id"] for row in rows] == [None, 1]
        assert "arguments" not in path.read_text()
        assert "content" not in path.read_text()
        if os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600
    finally:
        reset_config()


def test_trace_is_exclusive_and_never_overwrites_existing_attempt(tmp_path: Path) -> None:
    path = _private_attempt(tmp_path) / "ops-mcp-trace.jsonl"
    trace = ReferenceOpsTrace(path=path, attempt_id="attempt-004")
    trace.close()
    with pytest.raises(FileExistsError):
        ReferenceOpsTrace(path=path, attempt_id="attempt-004")


def test_trace_rejects_public_or_symlinked_storage(tmp_path: Path) -> None:
    path = _private_attempt(tmp_path) / "ops-mcp-trace.jsonl"
    if os.name != "nt":
        path.parent.chmod(0o755)
        with pytest.raises(ValueError, match="private"):
            ReferenceOpsTrace(path=path, attempt_id="attempt-004")
        path.parent.chmod(0o700)
    target = tmp_path / "external"
    target.write_text("must remain intact")
    try:
        path.symlink_to(target)
    except OSError:
        if os.name == "nt":
            pytest.skip("Windows runner does not allow symlink creation")
        raise
    with pytest.raises(ValueError, match="new absolute"):
        ReferenceOpsTrace(path=path, attempt_id="attempt-004")
    assert target.read_text() == "must remain intact"


def test_trace_configuration_is_opt_in_and_path_confined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("KICAD_MCP_REFERENCE_TRACE_PATH", raising=False)
    monkeypatch.delenv("KICAD_MCP_REFERENCE_ATTEMPT_ID", raising=False)
    assert configured_trace(checkout=tmp_path) is None

    monkeypatch.setenv("KICAD_MCP_REFERENCE_ATTEMPT_ID", "attempt-004")
    monkeypatch.setenv("KICAD_MCP_REFERENCE_TRACE_PATH", str(tmp_path / "other.jsonl"))
    with pytest.raises(ValueError, match="isolated"):
        configured_trace(checkout=tmp_path)

    path = _private_attempt(tmp_path) / "ops-mcp-trace.jsonl"
    monkeypatch.setenv("KICAD_MCP_REFERENCE_TRACE_PATH", str(path))
    trace = configured_trace(checkout=tmp_path)
    assert trace is not None
    trace.close()
    assert path.exists()


def test_invalid_attempt_id_does_not_create_file(tmp_path: Path) -> None:
    path = _private_attempt(tmp_path) / "ops-mcp-trace.jsonl"
    with pytest.raises(ValueError, match="identity"):
        ReferenceOpsTrace(path=path, attempt_id="../escaped")
    assert not path.exists()


def test_middleware_does_not_log_non_tool_messages(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = _private_attempt(tmp_path) / "ops-mcp-trace.jsonl"
        trace = ReferenceOpsTrace(path=path, attempt_id="attempt-004")
        try:
            middleware = ReviewedOpsTraceMiddleware(trace)
            context = ServerRequestContext(
                session=None,
                lifespan_context=None,
                protocol_version="2026-07-28",
                method="ping",
                params=None,
            )

            async def do_ping(_context: object) -> CallToolResult:
                return CallToolResult(content=[])

            await middleware(context, do_ping)
        finally:
            trace.close()
        assert path.read_text() == ""

    asyncio.run(scenario())


def test_tool_failure_is_recorded_without_payload(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = _private_attempt(tmp_path) / "ops-mcp-trace.jsonl"
        trace = ReferenceOpsTrace(path=path, attempt_id="attempt-004")
        try:
            middleware = ReviewedOpsTraceMiddleware(trace)
            context = ServerRequestContext(
                session=None,
                lifespan_context=None,
                protocol_version="2026-07-28",
                method="tools/call",
                params={
                    "name": "sch_add_symbol",
                    "arguments": {"payload": "no-payload-should-appear"},
                },
            )

            async def failed_call(_context: object) -> CallToolResult:
                return CallToolResult(content=[], is_error=True)

            result = await middleware(context, failed_call)
            assert result.is_error
        finally:
            trace.close()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert rows[-1]["status"] == "failed"
        assert "no-payload-should-appear" not in path.read_text()

    asyncio.run(scenario())


def test_missing_half_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("KICAD_MCP_REFERENCE_ATTEMPT_ID", "attempt-004")
    monkeypatch.delenv("KICAD_MCP_REFERENCE_TRACE_PATH", raising=False)
    with pytest.raises(ValueError, match="together"):
        configured_trace(checkout=tmp_path)


def test_wire_format_error_is_not_reported_as_success(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = _private_attempt(tmp_path) / "ops-mcp-trace.jsonl"
        trace = ReferenceOpsTrace(path=path, attempt_id="attempt-004")
        try:
            middleware = ReviewedOpsTraceMiddleware(trace)
            context = ServerRequestContext(
                session=None,
                lifespan_context=None,
                protocol_version="2026-07-28",
                method="tools/call",
                params={"name": "unreviewed_method", "arguments": {}},
            )

            async def rejected(_context: object) -> dict[str, object]:
                return {"isError": True, "content": []}

            assert (await middleware(context, rejected))["isError"] is True
        finally:
            trace.close()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [row["status"] for row in rows] == ["started", "failed"]

    asyncio.run(scenario())
