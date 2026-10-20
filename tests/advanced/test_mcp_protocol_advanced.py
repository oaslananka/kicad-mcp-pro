"""Advanced MCP Protocol Compliance & Validation tests.

Validates FastMCP schema contracts, parameter validation, error responses,
and execution surface confinement.
"""

from __future__ import annotations

import pytest

from kicad_mcp.server import KiCadFastMCP


@pytest.mark.anyio
async def test_mcp_protocol_tool_schema_and_invocation() -> None:
    """Validate standard FastMCP tool registration and schema metadata."""
    server = KiCadFastMCP(name="test-protocol-server")

    @server.tool(name="sample_query", description="A sample query tool for protocol testing")
    def sample_query(target: str, limit: int = 10) -> dict[str, object]:
        return {"target": target, "limit": limit, "status": "ok"}

    # 1. Verify tool registration metadata
    tools = server.list_tools_sync()
    matching = [t for t in tools if t.name == "sample_query"]
    assert len(matching) == 1
    tool_def = matching[0]
    assert "A sample query tool for protocol testing" in (tool_def.description or "")
    assert tool_def.input_schema is not None

    # 2. Invoke tool successfully with valid parameters
    result = await server.call_tool("sample_query", {"target": "U1", "limit": 5})
    assert result.is_error is False
    assert len(result.content) > 0


@pytest.mark.anyio
async def test_mcp_protocol_missing_required_parameter() -> None:
    """Tool invocation with missing required argument must return error response."""
    server = KiCadFastMCP(name="test-protocol-server")

    @server.tool(name="strict_tool")
    def strict_tool(required_arg: str) -> str:
        return f"received:{required_arg}"

    result = await server.call_tool("strict_tool", {})
    assert result.is_error is True
    assert any(
        "required_arg" in block.text or "validation" in block.text.lower()
        for block in result.content
    )


@pytest.mark.anyio
async def test_mcp_protocol_invalid_parameter_type() -> None:
    """Tool invocation with invalid types must return validation error."""
    server = KiCadFastMCP(name="test-protocol-server")

    @server.tool(name="typed_tool")
    def typed_tool(count: int) -> int:
        return count * 2

    # Pass non-integer string
    result = await server.call_tool("typed_tool", {"count": "not-an-int"})
    assert result.is_error is True
    assert any(
        "count" in block.text.lower() or "int" in block.text.lower() for block in result.content
    )


@pytest.mark.anyio
async def test_mcp_protocol_unknown_tool_invocation() -> None:
    """Calling an unregistered tool must return error without crashing server."""
    server = KiCadFastMCP(name="test-protocol-server")

    result = await server.call_tool("non_existent_tool_xyz", {})
    assert result.is_error is True
    assert any(
        "not found" in block.text.lower() or "unknown" in block.text.lower()
        for block in result.content
    )


@pytest.mark.anyio
async def test_mcp_protocol_exception_containment() -> None:
    """Exceptions raised in tools must be safely contained and serialized as errors."""
    server = KiCadFastMCP(name="test-protocol-server")

    @server.tool(name="faulty_tool")
    def faulty_tool() -> str:
        raise ValueError("Controlled fault in tool execution")

    result = await server.call_tool("faulty_tool", {})
    assert result.is_error is True
    assert any("Controlled fault in tool execution" in block.text for block in result.content)
