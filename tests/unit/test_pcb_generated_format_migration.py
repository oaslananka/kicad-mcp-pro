from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import kicad_mcp.tools.pcb as pcb_tools


class _UpgradeResult:
    upgraded = True
    detail = ""


def test_get_pcb_file_for_sync_migrates_new_board(
    tmp_path: Path,
    monkeypatch,
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    cfg = SimpleNamespace(pcb_file=board, project_file=None)
    calls: list[tuple[Path, str]] = []

    monkeypatch.setattr(pcb_tools, "get_config", lambda: cfg)
    monkeypatch.setattr(
        pcb_tools,
        "upgrade_generated_file",
        lambda path, kind, _run_cli: calls.append((path, kind)) or _UpgradeResult(),
        raising=False,
    )

    assert pcb_tools._get_pcb_file_for_sync() == board
    assert calls == [(board, "pcb")]


def test_transactional_board_write_migrates_replaced_board(
    tmp_path: Path,
    monkeypatch,
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    board.write_text(pcb_tools._default_board_text(), encoding="utf-8")
    cfg = SimpleNamespace(pcb_file=board, project_file=None)
    calls: list[tuple[Path, str]] = []

    monkeypatch.setattr(pcb_tools, "get_config", lambda: cfg)
    monkeypatch.setattr(pcb_tools, "clear_ttl_cache", lambda: None)
    monkeypatch.setattr(
        pcb_tools,
        "upgrade_generated_file",
        lambda path, kind, _run_cli: calls.append((path, kind)) or _UpgradeResult(),
        raising=False,
    )

    result = pcb_tools._transactional_board_write(lambda content: content)

    assert result == str(board)
    assert calls == [(board, "pcb")]
