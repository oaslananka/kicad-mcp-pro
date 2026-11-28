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


@pytest.mark.parametrize("origin", [(0.0, 0.0), (60.0, 40.0), (-60.0, -40.0), (60.25, 40.75)])
@pytest.mark.parametrize("has_outline", [True, False])
def test_file_backed_placement_is_translation_invariant(
    monkeypatch: pytest.MonkeyPatch,
    sample_project: Path,
    origin: tuple[float, float],
    has_outline: bool,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.tools import design_intent_state
    from tests.integration.test_placement_quality_gate import _footprint_block

    x, y = origin
    board = sample_project / "demo.kicad_pcb"
    outline = (
        f"(gr_rect (start {x} {y}) (end {x + 40} {y + 30}) "
        '(stroke (width 0.05) (type solid)) (fill no) (layer "Edge.Cuts"))'
        if has_outline
        else ""
    )
    original = (
        pcb._default_board_text().rstrip()[:-1]
        + outline
        + _footprint_block("R1", "10k", x + 10, y + 10, net_name="SIGNAL")
        + _footprint_block("R2", "10k", x + 30, y + 20, net_name="SIGNAL")
        + ")"
    )
    board.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(
        design_intent_state,
        "resolve_design_intent",
        lambda: SimpleNamespace(resolved=design_intent_state.ProjectDesignIntent()),
    )
    message = pcb._auto_place_force_directed_board_file()
    assert "completed" in message, message
    saved = board.read_text(encoding="utf-8")
    assert saved != original
    footprints = pcb._parse_board_footprint_blocks(saved)
    assert set(footprints) == {"R1", "R2"}
    assert (footprints["R1"]["x_mm"], footprints["R1"]["y_mm"]) == (x + 17, y + 14)
    assert (footprints["R2"]["x_mm"], footprints["R2"]["y_mm"]) == (x + 23, y + 16)
    assert all(entry["pad_nets"] == {"1": "SIGNAL"} for entry in footprints.values())
    analysis = validation._placement_analysis_from_content(saved)
    assert analysis is not None
    assert analysis.score == 100
    assert not analysis.hard_failures


def test_dense_translated_board_keeps_feasible_candidate(
    monkeypatch: pytest.MonkeyPatch, sample_project: Path
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.tools import design_intent_state
    from tests.integration.test_placement_quality_gate import _footprint_block

    board = sample_project / "demo.kicad_pcb"
    blocks = []
    expected_nets = {}
    for index in range(36):
        row, col = divmod(index, 6)
        ref = f"R{index + 1}"
        net = f"ROW{row + 1}"
        expected_nets[ref] = {"1": net}
        blocks.append(
            _footprint_block(
                ref,
                "10k",
                63 + col * 5,
                45 + row * 10,
                width_mm=3,
                height_mm=2,
                net_name=net,
            )
        )
    original = (
        pcb._default_board_text().rstrip()[:-1]
        + "(gr_rect (start 60 40) (end 92 100) (stroke (width 0.05) (type solid)) "
        + '(fill no) (layer "Edge.Cuts"))'
        + "".join(blocks)
        + ")"
    )
    board.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(
        design_intent_state,
        "resolve_design_intent",
        lambda: SimpleNamespace(resolved=design_intent_state.ProjectDesignIntent()),
    )
    before = validation._placement_analysis_from_content(original)
    assert before is not None
    assert before.score == 95
    assert not before.hard_failures
    message = pcb._auto_place_force_directed_board_file()
    assert "completed" in message, message
    saved = board.read_text(encoding="utf-8")
    assert saved != original
    actual = {
        ref: entry["pad_nets"] for ref, entry in pcb._parse_board_footprint_blocks(saved).items()
    }
    assert actual == expected_nets
    after = validation._placement_analysis_from_content(saved)
    assert after is not None
    assert after.score == before.score
    assert not after.hard_failures


@pytest.mark.parametrize("lock_value", ["yes", "no"])
def test_placement_respects_explicit_footprint_lock(
    monkeypatch: pytest.MonkeyPatch,
    sample_project: Path,
    lock_value: str,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.tools import design_intent_state
    from tests.integration.test_placement_quality_gate import _footprint_block

    board = sample_project / "demo.kicad_pcb"
    first = _footprint_block("R1", "10k", 70, 50, net_name="SIGNAL")
    first = first.replace('(layer "F.Cu")', f'(locked {lock_value}) (layer "F.Cu")', 1)
    original = (
        pcb._default_board_text().rstrip()[:-1]
        + "(gr_rect (start 60 40) (end 100 70) (stroke (width 0.05) (type solid)) "
        + '(fill no) (layer "Edge.Cuts"))'
        + first
        + _footprint_block("R2", "10k", 90, 60, net_name="SIGNAL")
        + ")"
    )
    board.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    monkeypatch.setattr(
        design_intent_state,
        "resolve_design_intent",
        lambda: SimpleNamespace(resolved=design_intent_state.ProjectDesignIntent()),
    )
    message = pcb._auto_place_force_directed_board_file()
    assert "completed" in message, message
    entries = pcb._parse_board_footprint_blocks(board.read_text(encoding="utf-8"))
    position = (entries["R1"]["x_mm"], entries["R1"]["y_mm"])
    if lock_value == "yes":
        assert position == (70, 50)
        assert entries["R1"]["block"] == pcb._parse_board_footprint_blocks(original)["R1"]["block"]
    else:
        assert position != (70, 50)
    assert (entries["R2"]["x_mm"], entries["R2"]["y_mm"]) != (90, 60)


def test_rejected_candidate_reports_actionable_hard_failure_details() -> None:
    message = pcb._degrading_placement_message(100, [], 60, ["R1 overlaps RF keepout 'Antenna'."])
    assert message is not None
    assert "R1 overlaps RF keepout 'Antenna'." in message
    assert "Current board preserved" in message
    assert "not proof" in message


def test_rf_keepout_rejection_preserves_translated_board(
    monkeypatch: pytest.MonkeyPatch, sample_project: Path
) -> None:
    from types import SimpleNamespace

    from kicad_mcp.tools import design_intent_state
    from tests.integration.test_placement_quality_gate import _footprint_block

    board = sample_project / "demo.kicad_pcb"
    original = (
        pcb._default_board_text().rstrip()[:-1]
        + "(gr_rect (start 60 40) (end 100 70) (stroke (width 0.05) (type solid)) "
        + '(fill no) (layer "Edge.Cuts"))'
        + _footprint_block("R1", "10k", 70, 50, net_name="SIGNAL")
        + _footprint_block("R2", "10k", 90, 60, net_name="SIGNAL")
        + ")"
    )
    board.write_text(original, encoding="utf-8")
    before = board.read_bytes()
    monkeypatch.setattr(pcb, "_get_pcb_file_for_sync", lambda: board)
    intent = design_intent_state.ProjectDesignIntent(
        rf_keepout_regions=[
            design_intent_state.RFKeepoutIntent(name="Antenna", x_mm=77, y_mm=54, w_mm=2, h_mm=2)
        ]
    )
    monkeypatch.setattr(
        design_intent_state,
        "resolve_design_intent",
        lambda: SimpleNamespace(resolved=intent),
    )
    initial = validation._placement_analysis_from_content(original)
    assert initial is not None
    assert not initial.hard_failures
    message = pcb._auto_place_force_directed_board_file()
    assert "rejected" in message
    assert "R1 overlaps RF keepout 'Antenna'." in message
    assert board.read_bytes() == before
