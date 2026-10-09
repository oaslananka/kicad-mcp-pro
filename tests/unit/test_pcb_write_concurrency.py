"""The PCB read/modify/write boundary must not lose parallel mutations."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from kicad_mcp.tools import pcb


def test_parallel_file_backed_pcb_writes_preserve_every_edit(monkeypatch, tmp_path: Path) -> None:
    board = tmp_path / "parallel.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(pcb, "_normalize_board_content", lambda text: text)
    monkeypatch.setattr(pcb, "_validate_board_text", lambda text: None)
    monkeypatch.setattr(pcb, "get_config", lambda: SimpleNamespace(workspace=tmp_path))
    monkeypatch.setattr(pcb, "clear_ttl_cache", lambda: None)
    monkeypatch.setattr(
        pcb,
        "upgrade_generated_file",
        lambda *args, **kwargs: SimpleNamespace(upgraded=True),
    )

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def write(index: int) -> str:
        def mutate(current: str) -> str:
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.005)
                return current + f'(marker "{index}")\n'
            finally:
                with active_lock:
                    active -= 1

        return pcb._transactional_board_write(mutate)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(20)))

    assert results == [str(board)] * 20
    assert max_active == 1
    contents = board.read_text(encoding="utf-8")
    for index in range(20):
        assert contents.count(f'(marker "{index}")') == 1


def test_invalid_utf8_board_fails_closed_without_losing_original_bytes(
    monkeypatch, tmp_path: Path
) -> None:
    import pytest

    board = tmp_path / "non-utf8.kicad_pcb"
    original = b"(kicad_pcb)\n\xff"
    board.write_bytes(original)
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    mutator_called = False

    def mutate(_content: str) -> str:
        nonlocal mutator_called
        mutator_called = True
        return "changed"

    with pytest.raises(UnicodeDecodeError):
        pcb._transactional_board_write(mutate)
    assert not mutator_called
    assert board.read_bytes() == original
    assert sorted(tmp_path.iterdir()) == [board]


def test_failed_board_replace_preserves_original_and_cleans_temp_file(
    monkeypatch, tmp_path: Path
) -> None:
    import pytest

    board = tmp_path / "replace-failure.kicad_pcb"
    original = "(kicad_pcb)\n"
    board.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(pcb, "_normalize_board_content", lambda text: text)
    monkeypatch.setattr(pcb, "_validate_board_text", lambda text: None)

    def fail_replace(_source: Path, _target: Path) -> Path:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated rename failure"):
        pcb._transactional_board_write(lambda current: current + '(marker "new")\n')
    assert board.read_text(encoding="utf-8") == original
    assert sorted(tmp_path.iterdir()) == [board]
