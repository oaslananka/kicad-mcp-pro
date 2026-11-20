"""Quality acceptance for file-backed force-directed PCB placement."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from kicad_mcp.tools import pcb, validation
from kicad_mcp.tools.validation import PlacementAnalysis


def _board_text() -> str:
    return """(kicad_pcb
  (version 20250316)
  (generator "pytest")
  (footprint "R_0603"
    (layer "F.Cu")
    (at 20 20 0)
    (property "Reference" "R1" (at 0 -2 0))
    (property "Value" "10k" (at 0 2 0))
    (fp_rect (start -1 -0.7) (end 1 0.7)
      (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
  )
  (footprint "R_0603"
    (layer "F.Cu")
    (at 40 20 0)
    (property "Reference" "R2" (at 0 -2 0))
    (property "Value" "10k" (at 0 2 0))
    (fp_rect (start -1 -0.7) (end 1 0.7)
      (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
  )
)
"""


def _score(score: int, failures: list[str] | None = None) -> PlacementAnalysis:
    return PlacementAnalysis(
        footprint_count=2,
        board_width_mm=60.0,
        board_height_mm=35.0,
        board_area_mm2=2100.0,
        footprint_area_mm2=2.8,
        density_pct=0.14,
        score=score,
        hard_failures=failures or [],
    )


@pytest.mark.parametrize(
    ("original_score", "new_score", "original_failures", "new_failures", "commit"),
    [
        (80, 50, [], [], False),
        (60, 70, [], ["Connector outside board"], False),
        (45, 70, [], [], True),
        (80, 80, [], [], True),
    ],
)
def test_force_directed_placement_accepts_only_nonregressing_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    original_score: int,
    new_score: int,
    original_failures: list[str],
    new_failures: list[str],
    commit: bool,
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    before = _board_text()
    board.write_text(before, encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(pcb, "_placement_nets_from_footprints", lambda *_: [object()])

    def place(components, _nets, _config, *, stats):
        stats.update(iterations_run=10, converged=False)
        return [replace(c, x=c.x + 10) for c in components]

    monkeypatch.setattr(pcb, "force_directed_placement", place)

    analyses = iter([_score(original_score, original_failures), _score(new_score, new_failures)])
    monkeypatch.setattr(validation, "_placement_analysis", lambda: (next(analyses), None))
    monkeypatch.setattr(
        validation, "_placement_analysis_from_content", lambda *_: next(analyses), raising=False
    )
    writes = []

    def atomic(mutator):
        writes.append(True)
        board.write_text(mutator(board.read_text(encoding="utf-8")), encoding="utf-8")
        return str(board)

    monkeypatch.setattr(pcb, "_transactional_board_write", atomic)
    message = pcb._auto_place_force_directed_board_file()

    assert bool(writes) is commit
    if commit:
        assert board.read_text(encoding="utf-8") != before
        assert "completed" in message
    else:
        assert board.read_text(encoding="utf-8") == before
        assert "rejected" in message
        assert f"{original_score}/100" in message
        assert f"{new_score}/100" in message


def test_unchanged_solver_positions_do_not_rewrite_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    original = _board_text()
    board.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(pcb, "_placement_nets_from_footprints", lambda *_: [object()])

    def unchanged(components, _nets, _config, *, stats):
        stats.update(iterations_run=1, converged=True)
        return components

    monkeypatch.setattr(pcb, "force_directed_placement", unchanged)
    monkeypatch.setattr(validation, "_placement_analysis_from_content", lambda *_: _score(65))
    monkeypatch.setattr(
        pcb,
        "_transactional_board_write",
        lambda *_: pytest.fail("No-op placement must not rewrite PCB"),
    )
    message = pcb._auto_place_force_directed_board_file()
    assert "skipped" in message
    assert board.read_text(encoding="utf-8") == original


def test_candidate_evaluation_failure_preserves_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    original = _board_text()
    board.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(pcb, "_placement_nets_from_footprints", lambda *_: [object()])
    monkeypatch.setattr(
        pcb,
        "force_directed_placement",
        lambda components, _nets, _config, *, stats: [replace(c, x=c.x + 10) for c in components],
    )
    scores = iter([_score(65), None])
    monkeypatch.setattr(validation, "_placement_analysis_from_content", lambda *_: next(scores))
    monkeypatch.setattr(
        pcb,
        "_transactional_board_write",
        lambda *_: pytest.fail("Unscorable candidate must not rewrite PCB"),
    )
    assert "rejected" in pcb._auto_place_force_directed_board_file()
    assert board.read_text(encoding="utf-8") == original


def test_candidate_aborts_if_board_changes_before_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    board.write_text(_board_text(), encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(pcb, "_placement_nets_from_footprints", lambda *_: [object()])
    monkeypatch.setattr(
        pcb,
        "force_directed_placement",
        lambda components, _nets, _config, *, stats: [replace(c, x=c.x + 10) for c in components],
    )
    monkeypatch.setattr(validation, "_placement_analysis_from_content", lambda *_: _score(70))

    def simulate_external_update(mutator):
        board.write_text("updated elsewhere", encoding="utf-8")
        mutator(board.read_text(encoding="utf-8"))
        pytest.fail("Concurrent update should stop the candidate")

    monkeypatch.setattr(pcb, "_transactional_board_write", simulate_external_update)
    with pytest.raises(RuntimeError, match="changed during auto-placement"):
        pcb._auto_place_force_directed_board_file()
    assert board.read_text(encoding="utf-8") == "updated elsewhere"


def test_candidate_scoring_matches_file_backed_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.tools import design_intent_state

    board = tmp_path / "demo.kicad_pcb"
    board.write_text(_board_text(), encoding="utf-8")
    monkeypatch.setattr(validation, "_get_pcb_file", lambda: board)
    monkeypatch.setattr(
        design_intent_state,
        "resolve_design_intent",
        lambda: SimpleNamespace(resolved=design_intent_state.ProjectDesignIntent()),
    )

    disk_analysis, blocked = validation._placement_analysis()
    preview_analysis = validation._placement_analysis_from_content(
        pcb._normalize_board_content(board.read_text(encoding="utf-8"))
    )
    assert blocked is None
    assert disk_analysis is not None
    assert preview_analysis is not None
    assert disk_analysis.score == preview_analysis.score
    assert disk_analysis.hard_failures == preview_analysis.hard_failures


def test_unscorable_board_preview_is_not_an_acceptable_candidate() -> None:
    assert (
        validation._placement_analysis_from_content(
            "(kicad_pcb (version 20250316) (generator pytest))"
        )
        is None
    )
