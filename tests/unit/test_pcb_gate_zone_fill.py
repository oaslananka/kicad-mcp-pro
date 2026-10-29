"""Zone-fill verification for the PCB gate (read-only, BLOCKED when unverifiable)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.tools import validation
from kicad_mcp.validation.zone_fill import (
    drc_outcome_changes,
    fill_geometry_changes,
    scan_zone_fill,
)

FILLED_ZONE = """
	(zone
		(net 1)
		(net_name "GND")
		(layers "F&B.Cu")
		(uuid "11111111-1111-1111-1111-111111111111")
		(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))
		(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
		(filled_polygon (layer "F.Cu") (pts (xy 1 1) (xy 9 1) (xy 9 9)))
		(filled_polygon (layer "B.Cu") (pts (xy 1 1) (xy 9 1) (xy 9 9)))
	)"""

UNFILLED_ZONE = """
	(zone
		(net 2)
		(net_name "+3V3")
		(layer "F.Cu")
		(uuid "22222222-2222-2222-2222-222222222222")
		(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))
		(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
	)"""

KEEPOUT_ZONE = """
	(zone
		(net 0)
		(net_name "")
		(layer "F.Cu")
		(uuid "33333333-3333-3333-3333-333333333333")
		(keepout (tracks not_allowed) (vias not_allowed) (pads allowed))
		(fill (thermal_gap 0.5))
		(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
	)"""

SILK_ZONE = """
	(zone
		(net 0)
		(net_name "")
		(layer "F.SilkS")
		(uuid "44444444-4444-4444-4444-444444444444")
		(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
	)"""

PAD_WITH_ZONE_CONNECT = """
	(footprint "R"
		(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (zone_connect 2))
		(property "Value" "(zone fake)")
	)"""


def _board(*parts: str) -> str:
    return "(kicad_pcb\n\t(version 20260206)\n" + "\n".join(parts) + "\n)\n"


def test_scan_reports_nothing_for_a_board_without_zones() -> None:
    scan = scan_zone_fill(_board())

    assert 0 == scan.copper_zones
    assert [] == scan.unfilled


def test_scan_accepts_a_filled_zone() -> None:
    scan = scan_zone_fill(_board(FILLED_ZONE))

    assert 1 == scan.copper_zones
    assert [] == scan.unfilled


def test_scan_flags_a_copper_zone_without_filled_polygons() -> None:
    scan = scan_zone_fill(_board(FILLED_ZONE, UNFILLED_ZONE))

    assert 2 == scan.copper_zones
    assert 1 == len(scan.unfilled)
    assert "+3V3" in scan.unfilled[0]
    assert "F.Cu" in scan.unfilled[0]


PARTLY_FILLED_ZONE = """
	(zone
		(net 1)
		(net_name "GND")
		(layers "F.Cu" "B.Cu")
		(uuid "55555555-5555-5555-5555-555555555555")
		(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))
		(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
		(filled_polygon (layer "F.Cu") (pts (xy 1 1) (xy 9 1) (xy 9 9)))
	)"""


def test_scan_flags_a_multi_layer_zone_filled_on_only_one_of_its_layers() -> None:
    scan = scan_zone_fill(_board(PARTLY_FILLED_ZONE))

    assert 1 == scan.copper_zones
    assert 1 == len(scan.unfilled)
    assert "B.Cu" in scan.unfilled[0]
    assert "no stored fill on B.Cu" in scan.unfilled[0]


def test_scan_flags_the_f_and_b_shorthand_filled_on_only_one_layer() -> None:
    shorthand = PARTLY_FILLED_ZONE.replace('(layers "F.Cu" "B.Cu")', '(layers "F&B.Cu")')

    scan = scan_zone_fill(_board(shorthand))

    assert 1 == len(scan.unfilled)
    assert "no stored fill on B.Cu" in scan.unfilled[0]
    assert "F.Cu" not in scan.unfilled[0].split("no stored fill on")[1]


def test_scan_flags_a_shorthand_zone_with_no_fill_on_either_layer() -> None:
    bare = FILLED_ZONE.replace("filled_polygon", "other_thing")

    scan = scan_zone_fill(_board(bare))

    assert 1 == len(scan.unfilled)
    assert "no stored fill on F.Cu, B.Cu" in scan.unfilled[0]


def test_scan_accepts_a_multi_layer_zone_filled_on_every_layer() -> None:
    both = PARTLY_FILLED_ZONE.replace(
        "\n\t)", '\n\t\t(filled_polygon (layer "B.Cu") (pts (xy 1 1) (xy 9 1) (xy 9 9)))\n\t)'
    )

    assert [] == scan_zone_fill(_board(both)).unfilled


def test_scan_only_requires_fill_on_the_copper_layers_of_a_mixed_layer_zone() -> None:
    mixed = PARTLY_FILLED_ZONE.replace('(layers "F.Cu" "B.Cu")', '(layers "F.Cu" "F.Mask")')

    assert [] == scan_zone_fill(_board(mixed)).unfilled


def test_scan_ignores_rule_areas_and_non_copper_zones_and_zone_connect() -> None:
    scan = scan_zone_fill(_board(KEEPOUT_ZONE, SILK_ZONE, PAD_WITH_ZONE_CONNECT))

    assert 0 == scan.copper_zones
    assert [] == scan.unfilled


def test_scan_reads_the_net_from_the_quoted_net_token_of_newer_boards() -> None:
    newer = UNFILLED_ZONE.replace("(net 2)", "").replace('(net_name "+3V3")', '(net "+3V3")')

    scan = scan_zone_fill(_board(newer))

    assert "+3V3" in scan.unfilled[0]


def test_scan_reports_a_zone_whose_fill_is_disabled() -> None:
    disabled = UNFILLED_ZONE.replace("(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))", "")

    scan = scan_zone_fill(_board(disabled))

    assert 1 == len(scan.unfilled)


def test_drc_outcome_changes_is_empty_for_identical_reports() -> None:
    report = {
        "violations": [{"type": "clearance", "items": [{"description": "Track [GND]"}]}],
        "unconnected_items": [{"type": "unconnected_items", "items": [{"description": "Pad [A]"}]}],
    }

    assert [] == drc_outcome_changes(report, json.loads(json.dumps(report)))


def test_drc_outcome_changes_describes_what_a_refill_changes() -> None:
    stored = {
        "violations": [],
        "unconnected_items": [
            {"type": "unconnected_items", "items": [{"description": "Pad 1 [GND] of C1"}]},
            {"type": "unconnected_items", "items": [{"description": "Pad 2 [VCC] of C2"}]},
        ],
    }
    refilled = {
        "violations": [{"type": "isolated_copper", "items": [{"description": "Zone [GND]"}]}],
        "unconnected_items": [
            {"type": "unconnected_items", "items": [{"description": "Pad 2 [VCC] of C2"}]},
        ],
    }

    changes = drc_outcome_changes(stored, refilled)

    assert any("unconnected_items 2 -> 1" in change for change in changes)
    assert any("violations 0 -> 1" in change for change in changes)


# ---- gate integration -----------------------------------------------------------------


def _clean_report() -> dict[str, object]:
    return {"violations": [], "unconnected_items": [], "items_not_passing_courtyard": []}


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    board_text: str | None,
    *,
    report: dict[str, object] | None = None,
    probe: object = None,
) -> list[str]:
    """Patch the gate's inputs; return a list that records refill-probe calls."""
    calls: list[str] = []
    board = tmp_path / "demo.kicad_pcb"
    if board_text is not None:
        board.write_text(board_text, encoding="utf-8")
    drc = report if report is not None else _clean_report()
    monkeypatch.setattr(validation, "_get_pcb_file", lambda: board)
    monkeypatch.setattr(validation, "_run_drc_report", lambda name: (Path(name), drc, None))

    def fake_probe(path: Path) -> tuple[dict[str, object] | None, str | None, str | None]:
        calls.append(path.name)
        if probe is None:
            # A refill that reproduces both the DRC result and the stored fill.
            return json.loads(json.dumps(drc)), board_text, None
        return probe  # type: ignore[return-value]

    monkeypatch.setattr(validation, "_refill_probe_report", fake_probe)
    return calls


def test_gate_passes_without_zones_and_never_runs_the_refill_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _wire(monkeypatch, tmp_path, _board())

    outcome = validation._evaluate_pcb_gate()

    assert "PASS" == outcome.status
    assert [] == calls


def test_gate_passes_when_a_fresh_refill_agrees_with_the_stored_fill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _wire(monkeypatch, tmp_path, _board(FILLED_ZONE))

    outcome = validation._evaluate_pcb_gate()

    assert "PASS" == outcome.status
    assert ["demo.kicad_pcb"] == calls
    assert any("Zone fill: 1 copper zone(s) filled and current" in d for d in outcome.details)


def test_gate_is_blocked_when_a_copper_zone_is_not_filled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _wire(monkeypatch, tmp_path, _board(FILLED_ZONE, UNFILLED_ZONE))

    outcome = validation._evaluate_pcb_gate()

    assert "BLOCKED" == outcome.status
    assert [] == calls
    assert any(d.startswith("BLOCKED: ") and "+3V3" in d for d in outcome.details)
    assert any("pcb_refill_zones" in d for d in outcome.details)


def test_gate_is_blocked_when_the_stored_fill_is_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stale = _clean_report()
    stale["unconnected_items"] = [
        {"type": "unconnected_items", "items": [{"description": "Pad 1 [GND] of C1"}]}
    ]
    _wire(
        monkeypatch,
        tmp_path,
        _board(FILLED_ZONE),
        report=stale,
        probe=(_clean_report(), _board(FILLED_ZONE), None),
    )

    outcome = validation._evaluate_pcb_gate()

    assert "BLOCKED" == outcome.status
    assert any("stale" in d and "unconnected_items 1 -> 0" in d for d in outcome.details)
    # The connectivity findings from the stored fill stay visible next to the block.
    assert any(d.startswith("FAIL: net GND") for d in outcome.details)


def test_gate_is_blocked_when_the_refill_probe_cannot_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _wire(monkeypatch, tmp_path, _board(FILLED_ZONE), probe=(None, None, "timed out"))

    outcome = validation._evaluate_pcb_gate()

    assert "BLOCKED" == outcome.status
    assert any("could not be verified" in d and "timed out" in d for d in outcome.details)


def test_gate_is_blocked_when_the_board_file_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _wire(monkeypatch, tmp_path, None)

    outcome = validation._evaluate_pcb_gate()

    assert "BLOCKED" == outcome.status
    assert any("zone fill" in d.lower() for d in outcome.details)


def test_gate_is_blocked_when_no_pcb_file_is_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _wire(monkeypatch, tmp_path, _board())

    def missing() -> Path:
        raise ValueError("No PCB file is configured.")

    monkeypatch.setattr(validation, "_get_pcb_file", missing)

    assert "BLOCKED" == validation._evaluate_pcb_gate().status


def test_gate_keeps_fail_semantics_for_real_violations_on_a_filled_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = _clean_report()
    report["violations"] = [{"type": "clearance", "severity": "error", "description": "x"}]
    _wire(monkeypatch, tmp_path, _board(FILLED_ZONE), report=report)

    assert "FAIL" == validation._evaluate_pcb_gate().status


# ---- the refill probe itself ----------------------------------------------------------


def test_refill_probe_saves_the_refilled_copy_and_never_touches_the_board(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    board.write_text(_board(FILLED_ZONE), encoding="utf-8")
    (tmp_path / "demo.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "fp-lib-table").write_text("(fp_lib_table)", encoding="utf-8")
    before = board.read_bytes()
    seen: list[list[str]] = []

    def fake_cli(variants: list[list[str]]) -> tuple[int, str, str]:
        (args,) = variants
        seen.append(args)
        out = Path(args[args.index("--output") + 1])
        copy = Path(args[-1])
        assert copy != board
        assert before == copy.read_bytes()
        assert (copy.parent / "demo.kicad_pro").is_file()
        assert (copy.parent / "fp-lib-table").is_file()
        out.write_text(json.dumps(_clean_report()), encoding="utf-8")
        copy.write_text(_board(FILLED_ZONE) + "; saved by kicad-cli", encoding="utf-8")
        return 0, "", ""

    monkeypatch.setattr(validation, "_run_cli_variants", fake_cli)

    report, refilled_text, error = validation._refill_probe_report(board)

    assert error is None
    assert _clean_report() == report
    assert refilled_text is not None
    assert refilled_text.endswith("; saved by kicad-cli")
    (args,) = seen
    assert "--refill-zones" in args
    assert "--save-board" in args
    assert before == board.read_bytes()
    assert not Path(args[-1]).parent.exists()


@pytest.mark.parametrize(
    ("result", "needle"),
    [((1, "", "boom"), "boom"), ((0, "", ""), "report")],
)
def test_refill_probe_reports_cli_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, result: tuple[int, str, str], needle: str
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    board.write_text(_board(FILLED_ZONE), encoding="utf-8")
    monkeypatch.setattr(validation, "_run_cli_variants", lambda _variants: result)

    report, refilled_text, error = validation._refill_probe_report(board)

    assert report is None
    assert refilled_text is None
    assert error is not None
    assert needle in error


def test_refill_probe_reports_a_missing_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    board.write_text(_board(FILLED_ZONE), encoding="utf-8")

    def no_cli(_variants: list[list[str]]) -> tuple[int, str, str]:
        raise FileNotFoundError("kicad-cli is not available")

    monkeypatch.setattr(validation, "_run_cli_variants", no_cli)

    report, refilled_text, error = validation._refill_probe_report(board)

    assert report is None
    assert refilled_text is None
    assert error is not None
    assert "not available" in error


def test_gate_lists_blockers_before_the_per_net_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = _clean_report()
    report["unconnected_items"] = [
        {"type": "unconnected_items", "items": [{"description": f"Pad 1 [N{i}] of R{i}"}]}
        for i in range(30)
    ]
    _wire(monkeypatch, tmp_path, _board(FILLED_ZONE, UNFILLED_ZONE), report=report)

    outcome = validation._evaluate_pcb_gate()

    # Downstream renderers keep only the first few detail lines.
    assert any(d.startswith("BLOCKED: ") for d in outcome.details[:6])


def test_gate_is_blocked_when_different_fills_give_identical_drc_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    refilled_board = _board(FILLED_ZONE.replace("(xy 9 9)", "(xy 8 8)"))
    _wire(
        monkeypatch,
        tmp_path,
        _board(FILLED_ZONE),
        probe=(_clean_report(), refilled_board, None),
    )

    outcome = validation._evaluate_pcb_gate()

    assert "BLOCKED" == outcome.status
    assert any("stale" in d and "fill geometry" in d for d in outcome.details)
    assert not any("filled and current" in d for d in outcome.details)


def test_gate_is_blocked_when_the_refilled_copy_was_not_saved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _wire(monkeypatch, tmp_path, _board(FILLED_ZONE), probe=(_clean_report(), None, None))

    outcome = validation._evaluate_pcb_gate()

    assert "BLOCKED" == outcome.status
    assert any("could not be verified as current" in d for d in outcome.details)


def test_gate_accepts_the_same_fill_written_in_another_vertex_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reordered = FILLED_ZONE.replace(
        "(pts (xy 1 1) (xy 9 1) (xy 9 9))",
        "(pts\n\t\t\t(xy 9.000000 9)\n\t\t\t(xy 1 1) (xy 9 1.0))",
    )
    _wire(
        monkeypatch,
        tmp_path,
        _board(FILLED_ZONE),
        probe=(_clean_report(), _board(reordered), None),
    )

    assert "PASS" == validation._evaluate_pcb_gate().status


def test_fill_geometry_changes_pinpoints_the_zone_and_layer() -> None:
    moved = FILLED_ZONE.replace(
        '(filled_polygon (layer "B.Cu") (pts (xy 1 1) (xy 9 1) (xy 9 9)))',
        '(filled_polygon (layer "B.Cu") (pts (xy 1 1) (xy 9 1) (xy 9 8)))',
    )

    changes = fill_geometry_changes(_board(FILLED_ZONE), _board(moved))

    assert 1 == len(changes)
    assert "11111111-1111-1111-1111-111111111111" in changes[0]
    assert "B.Cu" in changes[0]
    assert [] == fill_geometry_changes(_board(FILLED_ZONE), _board(FILLED_ZONE))


def test_refill_probe_leaves_the_original_board_and_project_files_byte_identical(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    project = tmp_path / "demo.kicad_pro"
    board.write_text(_board(FILLED_ZONE), encoding="utf-8")
    project.write_text("{}", encoding="utf-8")
    before = (board.read_bytes(), project.read_bytes())

    def fake_cli(variants: list[list[str]]) -> tuple[int, str, str]:
        (args,) = variants
        copy = Path(args[-1])
        # kicad-cli rewrites its input: here, the scratch copy and its project file.
        copy.write_text(_board(), encoding="utf-8")
        (copy.parent / "demo.kicad_pro").write_text('{"changed": 1}', encoding="utf-8")
        Path(args[args.index("--output") + 1]).write_text(
            json.dumps(_clean_report()), encoding="utf-8"
        )
        return 0, "", ""

    monkeypatch.setattr(validation, "_run_cli_variants", fake_cli)

    validation._refill_probe_report(board)

    assert before == (board.read_bytes(), project.read_bytes())
