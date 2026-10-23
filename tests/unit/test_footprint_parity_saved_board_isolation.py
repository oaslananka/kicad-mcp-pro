"""Project parity must never silently compare an unrelated PCB Editor board."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.tools import validation


def _saved_board(tmp_path: Path, reference: str) -> Path:
    path = tmp_path / "design.kicad_pcb"
    path.write_text(
        "(kicad_pcb\n"
        '\t(footprint "Resistor_SMD:R_0805"\n'
        f'\t\t(property "Reference" "{reference}" (at 0 0 0) (layer "F.SilkS"))\n'
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )
    return path


def test_parity_uses_configured_board_not_unrelated_live_editor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pcb = _saved_board(tmp_path, "R1")
    monkeypatch.setattr(validation, "_get_pcb_file", lambda: pcb)

    def unrelated_active_board() -> None:
        raise AssertionError("Unrelated PCB Editor context must not be consulted")

    monkeypatch.setattr(validation, "get_board", unrelated_active_board, raising=False)
    references, source, error = validation._board_footprint_references()
    assert (references, source, error) == ({"R1"}, "file", None)


def test_parity_fails_closed_if_configured_board_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pcb = tmp_path / "not-present.kicad_pcb"
    monkeypatch.setattr(validation, "_get_pcb_file", lambda: pcb)

    def unrelated_active_board() -> None:
        raise AssertionError("Unrelated PCB Editor must never fill a missing file")

    monkeypatch.setattr(validation, "get_board", unrelated_active_board, raising=False)
    references, source, error = validation._board_footprint_references()
    assert references == set()
    assert source == "file"
    assert error and "not-present.kicad_pcb" in error


def test_parity_rejects_invalid_utf8_in_saved_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pcb = _saved_board(tmp_path, "R1")
    pcb.write_bytes(pcb.read_bytes() + b"\xff")
    monkeypatch.setattr(validation, "_get_pcb_file", lambda: pcb)

    def unrelated_active_board() -> None:
        raise AssertionError("Do not fall back to a different board after decode errors")

    monkeypatch.setattr(validation, "get_board", unrelated_active_board, raising=False)
    references, source, error = validation._board_footprint_references()
    assert references == set()
    assert source == "file"
    assert error and "utf-8" in error.lower()
