"""Preserve public PCB fallback diagnostics while reusing report literals."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.tools import pcb


@pytest.mark.parametrize(
    ("project_path", "board_path"),
    [
        (None, None),
        (Path("/workspace/design"), Path("/workspace/design/board.kicad_pcb")),
    ],
)
def test_board_diagnostic_formats_preserve_public_output(
    monkeypatch: pytest.MonkeyPatch,
    project_path: Path | None,
    board_path: Path | None,
) -> None:
    monkeypatch.setattr(
        pcb,
        "get_config",
        lambda: SimpleNamespace(
            project_dir=project_path,
            pcb_file=board_path,
            project_file=None,
            kicad_socket_path=None,
        ),
    )
    shown_project = str(project_path) if project_path is not None else "(not configured)"
    shown_board = str(board_path) if board_path is not None else "(not configured)"

    assert pcb._format_file_backed_diagnostics(
        KiCadConnectionError("Socket offline"),
        board_file=board_path,
        fallback_status="fallback available",
    ) == [
        "Diagnostics:",
        "- Source: file-backed",
        "- IPC endpoint: auto-discovery",
        "- KiCad board from IPC: unavailable (Socket offline)",
        f"- Active project path: {shown_project}",
        f"- Board file: {shown_board}",
        "- Fallback status: fallback available",
    ]
    assert pcb._format_board_file_diagnostics(
        board_file=board_path, status="using KiCad defaults"
    ) == [
        "Diagnostics:",
        "- Source: file-backed",
        f"- Active project path: {shown_project}",
        f"- Board file: {shown_board}",
        "- Fallback status: using KiCad defaults",
    ]
    assert pcb._with_pcb_diagnostics("No tracks found.") == "\n".join(
        [
            "No tracks found.",
            "Diagnostics:",
            "- Source: live-gui",
            f"- Active project path: {shown_project}",
            f"- Board file: {shown_board}",
        ]
    )


def test_reload_after_sync_keeps_manual_warning_when_ipc_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> None:
        raise KiCadConnectionError("no connection")

    monkeypatch.setattr(pcb, "get_board", unavailable)
    assert pcb._reload_board_after_file_sync() == (
        "The PCB file was updated. Reload it manually in KiCad if needed."
    )
    assert pcb._finalize_file_based_board_edit(False) == (
        "The PCB file was updated. Reload it manually in KiCad if needed."
    )


def test_reload_after_sync_keeps_manual_warning_when_revert_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_revert() -> None:
        raise OSError("board reload rejected")

    monkeypatch.setattr(pcb, "get_board", lambda: SimpleNamespace(revert=failed_revert))
    assert pcb._reload_board_after_file_sync() == (
        "The PCB file was updated. Reload it manually in KiCad if needed."
    )


def test_reload_after_sync_preserves_live_reload_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reverts: list[bool] = []
    monkeypatch.setattr(
        pcb, "get_board", lambda: SimpleNamespace(revert=lambda: reverts.append(True))
    )
    assert pcb._reload_board_after_file_sync() == (
        "The PCB file was updated and KiCad was asked to reload it."
    )
    assert reverts == [True]
