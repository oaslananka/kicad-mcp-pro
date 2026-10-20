"""Fault injection & Chaos resilience tests for KiCad MCP Pro.

Tests behavior under connection timeouts, IPC disconnections, disk failures,
corrupt s-expressions, and malformed inputs.
"""

from __future__ import annotations

import errno
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.errors import UnsafePathError
from kicad_mcp.ipc.command_queue import KiCadCommandQueue
from kicad_mcp.ipc.errors import KiCadIpcTimeoutError
from kicad_mcp.tools.schematic import _atomic_write_state
from kicad_mcp.utils.sexpr import _extract_block
from kicad_mcp.validation.drc_runner import classify_drc_report


def test_fault_injection_ipc_transient_retry_and_recovery() -> None:
    """Simulate transient socket timeout that recovers on subsequent retry."""
    queue = KiCadCommandQueue(max_retries=3, base_delay_s=0.001)
    call_attempts = 0

    def flaky_ipc_call() -> str:
        nonlocal call_attempts
        call_attempts += 1
        if call_attempts < 2:
            raise KiCadIpcTimeoutError("IPC socket read timed out")
        return "success_recovered"

    result = queue.execute("flaky_op", flaky_ipc_call, correlation_id="c-retry-1")
    assert result == "success_recovered"
    assert call_attempts == 2

    journal = queue.journal
    assert len(journal) == 1
    assert journal[0].status == "success"
    assert journal[0].attempts == 2


def test_fault_injection_ipc_non_retryable_fails_fast() -> None:
    """Non-retryable errors must fail immediately without repeated retries."""
    queue = KiCadCommandQueue(max_retries=3, base_delay_s=0.001)
    call_attempts = 0

    def fatal_call() -> None:
        nonlocal call_attempts
        call_attempts += 1
        raise UnsafePathError("Forbidden traversal path")

    with pytest.raises(UnsafePathError):
        queue.execute("fatal_op", fatal_call, correlation_id="c-fatal-1")

    # Must NOT retry
    assert call_attempts == 1
    journal = queue.journal
    assert len(journal) == 1
    assert journal[0].status == "failed"
    assert journal[0].attempts == 1


def test_fault_injection_ipc_retry_exhaustion() -> None:
    """When retries are exhausted, the last error must be raised and journaled."""
    queue = KiCadCommandQueue(max_retries=2, base_delay_s=0.001)
    call_attempts = 0

    def permanently_down_ipc() -> None:
        nonlocal call_attempts
        call_attempts += 1
        raise KiCadIpcTimeoutError("KiCad backend is frozen")

    with pytest.raises(KiCadIpcTimeoutError):
        queue.execute("down_op", permanently_down_ipc, correlation_id="c-down-1")

    # 1 initial try + 2 retries = 3 attempts
    assert call_attempts == 3
    journal = queue.journal
    assert len(journal) == 1
    assert journal[0].status == "failed"
    assert journal[0].attempts == 3


def test_fault_injection_atomic_write_disk_full_resilience() -> None:
    """Simulate ENOSPC (disk full) during state write; original file must remain untouched
    and temporary files must be cleaned up without leaking.
    """
    with tempfile.TemporaryDirectory() as td:
        target_file = Path(td) / "state.json"
        target_file.write_text('{"original": true}', encoding="utf-8")

        # Mock NamedTemporaryFile in schematic module to raise ENOSPC
        with patch("kicad_mcp.tools.schematic.NamedTemporaryFile") as mock_tmp:

            class FailingTempFile:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    self.name = str(Path(td) / "temp_file.tmp")
                    Path(self.name).touch()

                def __enter__(self) -> FailingTempFile:
                    return self

                def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
                    pass

                def write(self, _content: str) -> None:
                    raise OSError(errno.ENOSPC, "No space left on device")

            mock_tmp.side_effect = FailingTempFile

            with pytest.raises(OSError) as exc_info:
                _atomic_write_state(target_file, '{"corrupted": true}')

            assert exc_info.value.errno == errno.ENOSPC

        # Target file must still have original intact content
        assert target_file.read_text(encoding="utf-8") == '{"original": true}'
        # No orphan temp files should remain in directory
        remaining = list(Path(td).glob("*.tmp"))
        assert len(remaining) == 0


def test_fault_injection_corrupt_sexpr_handling() -> None:
    """Test parser behavior against truncated, unclosed, or invalid S-expressions."""
    # 1. Empty or whitespace
    block, consumed = _extract_block("", 0)
    assert block == ""
    assert consumed == 0

    # 2. Unclosed opening parenthesis
    block, consumed = _extract_block("(unterminated_expression with parameters", 0)
    # Parser should return empty or consume without infinite loop
    assert isinstance(block, str)
    assert consumed >= 0

    # 3. Mismatched parentheses
    corrupt_content = "(((inner) )) extra_closing)"
    block, consumed = _extract_block(corrupt_content, 0)
    assert isinstance(block, str)


def test_fault_injection_drc_malformed_payloads() -> None:
    """Classify DRC report behavior with broken or adversary inputs."""
    # 1. Non-dict input
    status, err = classify_drc_report(["not", "a", "dict"])
    assert status == "malformed"
    assert "JSON object" in (err or "")

    # 2. String input
    status, err = classify_drc_report("raw string error")
    assert status == "malformed"

    # 3. Dict with invalid violations type
    status, err = classify_drc_report({"violations": "not-a-list"})
    assert status == "malformed"

    # 4. Dict with invalid unconnected_items type
    status, err = classify_drc_report({"violations": [], "unconnected_items": "invalid"})
    assert status == "malformed"
