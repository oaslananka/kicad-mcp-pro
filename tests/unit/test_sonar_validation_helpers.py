"""Regression coverage for extracted, behavior-preserving validation helpers."""

from __future__ import annotations

from kicad_mcp.tools import validation


def test_manhattan_mst_preserves_deterministic_distances() -> None:
    assert 0.0 == validation._manhattan_mst_length([])
    assert 0.0 == validation._manhattan_mst_length([(1.0, 1.0)])
    assert 7.0 == validation._manhattan_mst_length([(0.0, 0.0), (2.0, 0.0), (2.0, 5.0)])


def test_project_emptiness_short_circuits_after_schematic(monkeypatch) -> None:
    monkeypatch.setattr(validation, "_has_schematic_contents", lambda: True)

    def unexpected_pcb_probe() -> bool:
        raise AssertionError("PCB must not be probed after schematic content was found")

    monkeypatch.setattr(validation, "_has_pcb_contents", unexpected_pcb_probe)
    assert not validation._is_project_empty()


def test_project_emptiness_checks_pcb_after_empty_schematic(monkeypatch) -> None:
    monkeypatch.setattr(validation, "_has_schematic_contents", lambda: False)
    monkeypatch.setattr(validation, "_has_pcb_contents", lambda: True)
    assert not validation._is_project_empty()
    monkeypatch.setattr(validation, "_has_pcb_contents", lambda: False)
    assert validation._is_project_empty()
