"""The PCB read/modify/write boundary must not lose parallel mutations."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

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


@pytest.fixture
def transaction_board(monkeypatch, tmp_path: Path) -> Path:
    board = tmp_path / "board.kicad_pcb"
    board.write_bytes(b"(kicad_pcb)\r\n")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(pcb, "_normalize_board_content", lambda text: text)
    monkeypatch.setattr(pcb, "_validate_board_text", lambda text: None)
    monkeypatch.setattr(pcb, "get_config", lambda: SimpleNamespace(workspace=tmp_path))
    monkeypatch.setattr(pcb, "clear_ttl_cache", lambda: None)
    monkeypatch.setattr(
        pcb, "upgrade_generated_file", lambda *args, **kwargs: SimpleNamespace(upgraded=True)
    )
    return board


def test_external_board_edit_is_preserved(transaction_board: Path) -> None:
    external = b"(kicad_pcb (external_edit))\n"

    def mutate(current: str) -> str:
        transaction_board.write_bytes(external)
        return current + "(local_edit)"

    with pytest.raises(RuntimeError, match="changed"):
        pcb._transactional_board_write(mutate)
    assert transaction_board.read_bytes() == external
    assert list(transaction_board.parent.iterdir()) == [transaction_board]


def test_windows_sharing_failure_retries_only_replace(monkeypatch, transaction_board: Path) -> None:
    real_replace = Path.replace
    attempts = 0
    mutations = 0

    def replace(source: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = PermissionError("sharing violation")
            error.winerror = 32
            raise error
        return real_replace(source, target)

    def mutate(current: str) -> str:
        nonlocal mutations
        mutations += 1
        return current + "(local_edit)"

    monkeypatch.setattr(Path, "replace", replace)
    assert pcb._transactional_board_write(mutate) == str(transaction_board)
    assert (attempts, mutations) == (2, 1)
    assert "(local_edit)" in transaction_board.read_text()
    assert list(transaction_board.parent.iterdir()) == [transaction_board]


def test_external_edit_during_sharing_failure_blocks(monkeypatch, transaction_board: Path) -> None:
    external = b"(kicad_pcb (external_edit))"

    def replace(source: Path, target: Path) -> Path:
        target.write_bytes(external)
        error = PermissionError("sharing violation")
        error.winerror = 32
        raise error

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(RuntimeError, match="changed"):
        pcb._transactional_board_write(lambda current: current + "(local_edit)")
    assert transaction_board.read_bytes() == external
    assert list(transaction_board.parent.iterdir()) == [transaction_board]


def test_persistent_windows_sharing_error_is_bounded(monkeypatch, transaction_board: Path) -> None:
    original = transaction_board.read_bytes()
    attempts = 0

    def replace(source: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        error = PermissionError("sharing violation")
        error.winerror = 32
        raise error

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(PermissionError, match="sharing violation"):
        pcb._transactional_board_write(lambda current: current + "(local_edit)")
    assert attempts == 6
    assert transaction_board.read_bytes() == original
    assert list(transaction_board.parent.iterdir()) == [transaction_board]
