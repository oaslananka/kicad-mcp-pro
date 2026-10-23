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
    assert error is not None
    assert "not-present.kicad_pcb" in error


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
    assert error is not None
    assert "utf-8" in error.lower()


def test_parity_rejects_unbalanced_saved_board_without_ipc_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pcb = _saved_board(tmp_path, "R1")
    # The footprint block is intact, but the enclosing PCB is incomplete.
    pcb.write_text(pcb.read_text(encoding="utf-8").rstrip()[:-1], encoding="utf-8")
    monkeypatch.setattr(validation, "_get_pcb_file", lambda: pcb)

    def unrelated_active_board() -> None:
        raise AssertionError("Do not consult unrelated IPC after corrupt PCB text")

    monkeypatch.setattr(validation, "get_board", unrelated_active_board, raising=False)
    references, source, error = validation._board_footprint_references()
    assert references == set()
    assert source == "file"
    assert error is not None
    assert "unbalanced parentheses" in error


@pytest.mark.parametrize(
    "corruption",
    [
        "wrong_root",
        "root_prefix",
        "extra_root",
    ],
)
def test_parity_rejects_validly_balanced_non_pcb_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    pcb = _saved_board(tmp_path, "R1")
    document = pcb.read_text(encoding="utf-8")
    if corruption == "wrong_root":
        document = document.replace("(kicad_pcb", "(schematic", 1)
    elif corruption == "root_prefix":
        document = document.replace("(kicad_pcb", "(kicad_pcb_fake", 1)
    else:
        document += "\n(other_document)\n"
    pcb.write_text(document, encoding="utf-8")
    monkeypatch.setattr(validation, "_get_pcb_file", lambda: pcb)

    def unrelated_active_board() -> None:
        raise AssertionError("Never consult an unrelated GUI board for an invalid PCB")

    monkeypatch.setattr(validation, "get_board", unrelated_active_board, raising=False)
    references, source, error = validation._board_footprint_references()
    assert references == set()
    assert source == "file"
    assert error is not None
    expected = "one root" if corruption == "extra_root" else "not a KiCad PCB"
    assert expected in error
