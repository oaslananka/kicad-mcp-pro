"""IPC failures must never masquerade as PCB design-validation failures."""

from __future__ import annotations

import pytest

from kicad_mcp.errors import IpcDisconnectedError, KiCadBoardNotOpenError
from kicad_mcp.tools import pcb


@pytest.mark.parametrize(
    ("error", "failure_mode", "retryable"),
    [
        (IpcDisconnectedError("Disconnected stale KiCad IPC endpoint"), "environment", True),
        (KiCadBoardNotOpenError("No board open"), "configuration", False),
    ],
)
def test_board_summary_unavailable_reports_setup_not_pcb_design(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    failure_mode: str,
    retryable: bool,
) -> None:
    monkeypatch.setattr(pcb, "_configured_board_file", lambda: None)
    report = pcb._file_backed_board_summary(error)

    assert report.verdict == "FAIL"
    assert report.summary.startswith("Board summary unavailable")
    assert "0 footprint" not in report.summary
    assert report.failure_mode == failure_mode
    assert report.retryable is retryable
    assert report.findings[0].failure_mode == failure_mode
    assert report.findings[0].retryable is retryable
    assert report.findings[0].suggested_fix is None
    assert "kicad_set_project(project_dir=" in report.remediation
    assert "no configured .kicad_pcb file" in report.text
    assert report.metadata == {"source": "file-backed", "available": False}
    assert "footprints" not in report.metadata
    assert "nets" not in report.metadata


def test_file_backed_summary_reports_source_and_environment_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    board_file = tmp_path / "test.kicad_pcb"
    board_file.write_text('(kicad_pcb (version 20221018) (generator "test"))')
    monkeypatch.setattr(pcb, "_configured_board_file", lambda: board_file)

    report = pcb._file_backed_board_summary(IpcDisconnectedError("stale IPC endpoint"))

    assert report.verdict == "WARN"
    assert report.metadata["source"] == "file-backed"
    assert report.metadata["available"] is True
    assert report.metadata["footprints"] == 0
    assert report.metadata["nets"] == 0
    assert report.failure_mode == "environment"
    assert report.retryable is True
    assert report.findings[0].failure_mode == "environment"
    assert "using file-backed" in report.text
