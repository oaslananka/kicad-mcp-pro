"""Property-based tests for critical utility logic using Hypothesis."""

from __future__ import annotations

import pytest

try:
    from hypothesis import given
    from hypothesis import strategies as st

    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")


@given(st.text(min_size=0, max_size=200))
def test_tool_result_failure_message_stored(message: str) -> None:
    """ToolResult.failure always stores the error message."""
    from kicad_mcp.models.tool_result import ToolResult

    result = ToolResult.failure("test_tool", message)

    assert message in result.errors
    assert result.ok is False


@given(st.lists(st.text(min_size=1, max_size=50), max_size=20))
def test_tool_result_warnings_list(warnings: list[str]) -> None:
    """ToolResult warnings list is always preserved."""
    from kicad_mcp.models.tool_result import ToolResult

    result = ToolResult(ok=True, warnings=warnings)

    assert result.warnings == warnings
