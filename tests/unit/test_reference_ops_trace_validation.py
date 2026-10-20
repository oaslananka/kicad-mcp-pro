"""Deterministic adversarial validation of genuine server-observed tool traces."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from kicad_mcp.evals import reference_ops_trace_validation
from kicad_mcp.evals.reference_ops_trace import ReferenceOpsTrace
from kicad_mcp.evals.reference_ops_trace_validation import (
    ReferenceOpsTraceValidationError,
    validate_reference_ops_trace,
)


@pytest.fixture(autouse=True)
def _isolate_private_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        reference_ops_trace_validation,
        "_TRACE_ROOT",
        tmp_path / ".dev-tools" / "reference-agent-runs",
    )


def _good_trace(tmp_path: Path) -> Path:
    parent = tmp_path / ".dev-tools" / "reference-agent-runs" / "attempt-004"
    parent.mkdir(mode=0o700, parents=True)
    parent.chmod(0o700)
    path = parent / "ops-mcp-trace.jsonl"

    async def write_events() -> None:
        trace = ReferenceOpsTrace(path=path, attempt_id="attempt-004")
        try:
            call = await trace.emit(
                event_type="tool_call", name="kicad_get_version", status="started"
            )
            await trace.emit(
                event_type="tool_result",
                name="kicad_get_version",
                status="completed",
                request_id=call,
            )
            call = await trace.emit(
                event_type="tool_call", name="kicad_get_server_info", status="started"
            )
            await trace.emit(
                event_type="tool_result",
                name="kicad_get_server_info",
                status="failed",
                request_id=call,
            )
        finally:
            trace.close()

    asyncio.run(write_events())
    return path


def test_valid_real_emitted_trace_is_not_benchmark_success(tmp_path: Path) -> None:
    path = _good_trace(tmp_path)
    summary = validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")
    assert summary.tool_calls == 2
    assert summary.failed_calls == 1
    assert summary.digest.startswith("sha256:")
    assert summary.counts_as_task_success is False


@pytest.mark.skipif(os.name != "nt", reason="Windows CRT text-mode regression")
def test_windows_trace_open_preserves_byte_lengths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CRLF must not be converted to LF by Windows os.open/os.read."""
    path = _good_trace(tmp_path)
    real_open = os.open
    observed_flags: list[int] = []

    def record_open(filename: object, flags: int, *args: object, **kwargs: object) -> int:
        observed_flags.append(flags)
        return real_open(filename, flags, *args, **kwargs)

    monkeypatch.setattr(reference_ops_trace_validation.os, "open", record_open)
    summary = validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")
    assert summary.tool_calls == 2
    assert observed_flags
    assert all(flag & os.O_BINARY for flag in observed_flags)


@pytest.mark.parametrize(
    "change",
    [
        "missing-result",
        "duplicate-result",
        "out-of-sequence",
        "wrong-identity",
        "mismatched-name",
        "unreviewed-name",
        "unexpected-payload",
        "incorrect-request-id",
        "invalid-provenance",
        "empty-trace",
    ],
)
def test_fail_closed_on_tampered_events(tmp_path: Path, change: str) -> None:
    path = _good_trace(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "missing-result":
        rows.pop()
    elif change == "duplicate-result":
        rows.append(dict(rows[-1], sequence=5))
    elif change == "out-of-sequence":
        rows[2]["sequence"] = 50
    elif change == "wrong-identity":
        rows[1]["attempt_id"] = "attempt-999"
    elif change == "mismatched-name":
        rows[1]["name"] = "kicad_get_server_info"
    elif change == "unreviewed-name":
        rows[0]["name"] = "drc_rule_delete"
    elif change == "unexpected-payload":
        rows[1]["details"]["arguments"] = "not-a-safe-field"
    elif change == "incorrect-request-id":
        rows[3]["details"]["request_id"] = 101
    elif change == "invalid-provenance":
        rows[0]["details"]["provenance"] = "user_supplied"
    else:
        rows = []
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ReferenceOpsTraceValidationError):
        validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")


def test_public_or_symlinked_trace_is_rejected(tmp_path: Path) -> None:
    path = _good_trace(tmp_path)
    if os.name != "nt":
        path.chmod(0o644)
        with pytest.raises(ReferenceOpsTraceValidationError, match="private"):
            validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")
        path.chmod(0o600)
    link = tmp_path / "ops-mcp-trace.jsonl"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    with pytest.raises(ReferenceOpsTraceValidationError):
        validate_reference_ops_trace(link, attempt_id="attempt-004", phase_name="schematic")


def test_manufacturing_trace_cannot_be_accepted(tmp_path: Path) -> None:
    path = _good_trace(tmp_path)
    with pytest.raises(ReferenceOpsTraceValidationError, match="manufacturing"):
        validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="manufacturing")


@pytest.mark.parametrize(
    "mutation",
    [
        "truncated-last-line",
        "too-many-events",
        "timestamp-regression",
        "invalid-call-status",
        "non-tool-event",
        "malformed-json",
    ],
)
def test_other_incomplete_or_untrusted_trace_conditions_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    path = _good_trace(tmp_path)
    if mutation == "truncated-last-line":
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
    elif mutation == "too-many-events":
        path.write_bytes(b"{}\n" * 10001)
    elif mutation == "malformed-json":
        path.write_bytes(b"{not-json}\n")
    else:
        rows = [json.loads(row) for row in path.read_text().splitlines()]
        if mutation == "timestamp-regression":
            rows[2]["timestamp"] = "2000-01-01T00:00:00+00:00"
        elif mutation == "invalid-call-status":
            rows[0]["status"] = "completed"
        elif mutation == "non-tool-event":
            rows[0]["event_type"] = "agent"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ReferenceOpsTraceValidationError):
        validate_reference_ops_trace(path, attempt_id="attempt-004", phase_name="schematic")


def test_trace_outside_reserved_directory_is_rejected(tmp_path: Path) -> None:
    original = _good_trace(tmp_path)
    foreign = tmp_path / "elsewhere" / "ops-mcp-trace.jsonl"
    foreign.parent.mkdir()
    foreign.write_bytes(original.read_bytes())
    foreign.chmod(0o600)
    with pytest.raises(ReferenceOpsTraceValidationError, match="reserved"):
        validate_reference_ops_trace(foreign, attempt_id="attempt-004", phase_name="schematic")


@pytest.mark.parametrize("attempt_id", [".", "..", "../escape", "other-id"])
def test_attempt_identity_cannot_redirect_trace(tmp_path: Path, attempt_id: str) -> None:
    path = _good_trace(tmp_path)
    with pytest.raises(ReferenceOpsTraceValidationError):
        validate_reference_ops_trace(path, attempt_id=attempt_id, phase_name="schematic")


def test_open_rejects_symlink_created_after_path_approval(tmp_path: Path) -> None:
    """The read boundary must not follow a swapped-in symlink on POSIX."""
    if os.name == "nt":
        pytest.skip("O_NOFOLLOW/dir_fd unavailable on Windows")
    path = _good_trace(tmp_path)
    reference_ops_trace_validation._approved_trace_path(path, "attempt-004")
    outside = tmp_path / "untrusted-trace.jsonl"
    outside.write_bytes(path.read_bytes())
    outside.chmod(0o600)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises((OSError, ReferenceOpsTraceValidationError)):
        reference_ops_trace_validation._load_trace(
            root=reference_ops_trace_validation._TRACE_ROOT,
            attempt_id="attempt-004",
            filename="ops-mcp-trace.jsonl",
        )


def test_trace_loader_rejects_nonregular_file(tmp_path: Path) -> None:
    """Never read a device, pipe or substituted directory as JSONL evidence."""
    if os.name == "nt":
        pytest.skip("FIFO unavailable on Windows")
    path = _good_trace(tmp_path)
    path.unlink()
    os.mkfifo(path, mode=0o600)
    with pytest.raises(ReferenceOpsTraceValidationError, match="absent, empty or oversized"):
        reference_ops_trace_validation._load_trace(
            root=reference_ops_trace_validation._TRACE_ROOT,
            attempt_id="attempt-004",
            filename="ops-mcp-trace.jsonl",
        )


def test_trace_loader_rejects_content_change_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _good_trace(tmp_path)
    actual_read = reference_ops_trace_validation.os.read

    def changed_read(fd: int, size: int) -> bytes:
        content = actual_read(fd, size)
        if content:
            path.write_bytes(content + b"{}\\n")
        return content

    monkeypatch.setattr(reference_ops_trace_validation.os, "read", changed_read)
    with pytest.raises(ReferenceOpsTraceValidationError, match="changed during read"):
        reference_ops_trace_validation._load_trace(
            root=reference_ops_trace_validation._TRACE_ROOT,
            attempt_id="attempt-004",
            filename="ops-mcp-trace.jsonl",
        )


def test_trace_loader_blocks_public_attempt_directory(tmp_path: Path) -> None:
    """Directory descriptor policy remains effective after initial path checks."""
    if os.name == "nt":
        pytest.skip("POSIX directory permissions")
    path = _good_trace(tmp_path)
    path.parent.chmod(0o750)
    with pytest.raises(ReferenceOpsTraceValidationError, match="directory must be private"):
        reference_ops_trace_validation._load_trace(
            root=reference_ops_trace_validation._TRACE_ROOT,
            attempt_id="attempt-004",
            filename="ops-mcp-trace.jsonl",
        )


@pytest.mark.parametrize("attempt_id", ["../outside", ".", ""])
def test_trace_loader_rejects_invalid_attempt_before_file_open(
    tmp_path: Path, attempt_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _good_trace(tmp_path)

    def forbidden_open(**kwargs: object) -> int:
        pytest.fail(f"Untrusted path caused a file open: {kwargs}")

    monkeypatch.setattr(reference_ops_trace_validation, "_open_reserved_trace", forbidden_open)
    with pytest.raises(ReferenceOpsTraceValidationError, match="reserved"):
        reference_ops_trace_validation._load_trace(
            root=reference_ops_trace_validation._TRACE_ROOT,
            attempt_id=attempt_id,
            filename="ops-mcp-trace.jsonl",
        )


def test_windows_descriptor_path_requires_private_non_symlinked_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise the Windows branch even on non-Windows test runners."""
    from types import SimpleNamespace

    path = _good_trace(tmp_path)
    real_open = os.open
    fake_os = SimpleNamespace(
        name="nt",
        O_RDONLY=os.O_RDONLY,
        O_BINARY=getattr(os, "O_BINARY", 0),
        O_NOFOLLOW=getattr(os, "O_NOFOLLOW", 0),
        O_NONBLOCK=getattr(os, "O_NONBLOCK", 0),
        open=real_open,
    )
    monkeypatch.setattr(reference_ops_trace_validation, "os", fake_os)
    root = reference_ops_trace_validation._TRACE_ROOT
    fd = reference_ops_trace_validation._open_reserved_trace(
        root=root, attempt_id="attempt-004", filename="ops-mcp-trace.jsonl"
    )
    try:
        assert os.fstat(fd).st_size == path.stat().st_size
    finally:
        os.close(fd)

    link = path.parent / "ops-client-observed.jsonl"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ReferenceOpsTraceValidationError, match="reserved"):
        reference_ops_trace_validation._open_reserved_trace(
            root=root, attempt_id="attempt-004", filename="ops-client-observed.jsonl"
        )
