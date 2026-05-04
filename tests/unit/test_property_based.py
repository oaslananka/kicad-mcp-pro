"""Property-based tests for critical utility logic using Hypothesis."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

try:
    from hypothesis import assume, given
    from hypothesis import strategies as st

    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")


@given(st.text(min_size=1, max_size=100))
def test_schematic_state_path_stored(path_str: str) -> None:
    """SchematicState always stores the provided path string."""
    from kicad_mcp.models.state import SchematicState

    state = SchematicState(sch_path=path_str)

    assert state.sch_path == path_str


@given(st.integers(min_value=0, max_value=10000))
def test_verification_state_error_counts_non_negative(error_count: int) -> None:
    """VerificationState error counts preserve non-negative generated values."""
    from kicad_mcp.models.state import VerificationState

    state = VerificationState(erc_errors=error_count, drc_errors=error_count)

    assert state.erc_errors >= 0
    assert state.drc_errors >= 0


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


@given(st.binary(min_size=0, max_size=1024))
def test_schematic_state_hash_is_sha256_hex(content: bytes) -> None:
    """SchematicState.from_path always produces a SHA-256 hex string for files."""
    assume(len(content) > 0)
    from kicad_mcp.models.state import SchematicState

    with tempfile.TemporaryDirectory() as tmp_dir:
        target = Path(tmp_dir) / "test.kicad_sch"
        target.write_bytes(content)
        state = SchematicState.from_path(target)

    assert state.content_hash is not None
    assert len(state.content_hash) == 64
    assert all(char in "0123456789abcdef" for char in state.content_hash)
