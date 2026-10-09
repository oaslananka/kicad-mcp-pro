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
