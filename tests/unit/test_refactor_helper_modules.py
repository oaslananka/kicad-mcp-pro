from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from kicad_mcp.resources.gate_history import GateHistory, _status
from kicad_mcp.tools import board_file, export_support, routing_rules, schematic_transfer
from kicad_mcp.tools.gates import GateOutcome


def test_board_file_helpers_parse_geometry_nets_and_frame() -> None:
    empty = board_file._normalize_board_content("   ")
    assert "(version 20250216)" in empty
    assert board_file._normalize_board_content("(kicad_pcb)") == empty

    content = """
    (kicad_pcb
      (version 20250216)
      (gr_rect (start -5 -4) (end 25 18)
        (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))
      (footprint "Resistor_SMD:R_0805"
        (layer "F.Cu")
        (at 10 20 90)
        (property "Reference" "R1")
        (property "Value" "10k")
        (fp_rect (start -1 -0.5) (end 1 0.5)
          (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
        (fp_line (start -1 -0.6) (end 1 -0.6) (stroke (width 0.05) (type solid)) (layer "F.SilkS"))
        (fp_circle (center 0 0) (end 0 1)
          (stroke (width 0.05) (type solid)) (fill no) (layer "F.SilkS"))
        (pad "1" smd rect (at -0.95 0) (size 0.8 1.2) (layers "F.Cu") (net 1 "GND"))
        (pad "2" smd rect (at 0.95 0) (size 0.8 1.2) (layers "F.Cu") (net 2 "VCC"))
      )
    )
    """

    footprints = board_file._parse_board_footprint_blocks(content)

    assert footprints["R1"]["name"] == "Resistor_SMD:R_0805"
    assert footprints["R1"]["value"] == "10k"
    assert footprints["R1"]["x_mm"] == pytest.approx(10.0)
    assert footprints["R1"]["y_mm"] == pytest.approx(20.0)
    assert footprints["R1"]["rotation"] == 90
    assert footprints["R1"]["layer_name"] == "F.Cu"
    assert footprints["R1"]["net_names"] == ["GND", "VCC"]
    assert footprints["R1"]["pad_nets"] == {"1": "GND", "2": "VCC"}
    assert footprints["R1"]["width_mm"] >= 2.0
    assert board_file._board_frame_mm(content, footprints) == (-5.0, -4.0, 25.0, 18.0)
    assert board_file._board_frame_mm("(kicad_pcb)", footprints)[0] < 10.0
    assert board_file._board_frame_mm("(kicad_pcb)", {}) == (0.0, 0.0, 100.0, 80.0)
    assert board_file._placement_boxes_overlap(0, 0, 2, 2, 1.9, 0, 2, 2, 0.0)
    assert not board_file._placement_boxes_overlap(0, 0, 2, 2, 5, 0, 2, 2, 0.0)


def test_export_support_retries_transient_cli_errors(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del sample_project
    attempts: list[list[str]] = []

    def fake_run(
        args: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, timeout, check
        attempts.append(args)
        if len(attempts) == 1:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr=f"{args[0]} IPC socket timeout",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=f"exported by {args[0]}",
            stderr="",
        )

    monkeypatch.setattr(export_support.subprocess, "run", fake_run)
    monkeypatch.setattr(export_support.time, "sleep", lambda _delay: None)

    code, stdout, stderr = export_support._run_cli("pcb", "export", "gerbers")

    assert code == 0
    assert stdout == "exported by kicad-cli"
    assert stderr == ""
    assert len(attempts) == 2


def test_export_support_reports_missing_files_and_variant_timeouts(
    fake_cli: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del fake_cli

    with pytest.raises(ValueError, match="No PCB file"):
        export_support._get_pcb_file()
    with pytest.raises(ValueError, match="No schematic file"):
        export_support._get_sch_file()

    def fake_cli_run(*_args: str) -> tuple[int, str, str]:
        raise subprocess.TimeoutExpired(cmd=["kicad-cli"], timeout=1.0)

    monkeypatch.setattr(export_support, "_run_cli", fake_cli_run)

    assert export_support._run_cli_variants([["sch", "export", "netlist"]]) == (
        124,
        "",
        "The kicad-cli command timed out.",
    )


def test_gate_history_records_trends_and_regressions(tmp_path: Path) -> None:
    history = GateHistory(tmp_path / "gate_history.db")
    history._init()

    history.record(GateOutcome("dfm", "PASS", "ok"))
    history.record(GateOutcome("dfm", "FAIL", "failed", ["clearance"]), auto_fixed=2)

    trend = history.trend("dfm", last_n=2)
    latest = history.latest(last_n=1)

    assert trend[0]["status"] == "FAIL"
    assert trend[0]["issue_count"] == 1
    assert trend[0]["auto_fixed"] == 2
    assert trend[1]["status"] == "PASS"
    assert latest[0]["gate_name"] == "dfm"
    assert history.regression_check() == ["dfm regressed from PASS to FAIL."]
    assert _status("unexpected") == "FAIL"


def test_gate_history_rejects_newer_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "future_gate_history.db"
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA user_version = 999")

    with pytest.raises(RuntimeError, match="newer than this server supports"):
        GateHistory(db_path)._init()


def test_routing_rules_load_upsert_and_write(sample_project: Path) -> None:
    path = routing_rules._rules_file_path()
    assert path == sample_project / "demo.kicad_dru"
    assert routing_rules._load_rules_content(path) == "(rules)\n"
    assert routing_rules._load_rules_content(sample_project / "missing.kicad_dru") == "(rules)\n"
    assert routing_rules._mm(0.127) == "0.1270mm"

    rule = '(rule "min-width" (constraint track_width (min 0.2000mm)))'
    inserted = routing_rules._upsert_rule("(rules)\n", "min-width", rule)
    assert rule in inserted

    replacement = '(rule "min-width" (constraint track_width (min 0.2500mm)))'
    replaced = routing_rules._upsert_rule(inserted, "min-width", replacement)
    assert replacement in replaced
    assert "0.2000mm" not in replaced

    written_path = routing_rules._write_rule("min-width", replacement)
    assert written_path == path
    assert replacement in path.read_text(encoding="utf-8")

    bad = sample_project / "bad.kicad_dru"
    bad.write_text('(rules (rule "unterminated")', encoding="utf-8")
    with pytest.raises(ValueError, match="unbalanced parentheses"):
        routing_rules._load_rules_content(bad)
    with pytest.raises(ValueError, match="root"):
        routing_rules._upsert_rule("not a rules file", "x", '(rule "x")')


def test_schematic_transfer_parses_netlist_and_exports_map(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    netlist = """
    (export
      (nets
        (net (code "1") (name "USB_DP")
          (node (ref "J1") (pin "A6"))
          (node (ref "U1") (pin "12")))
        (net (code "2") (name "GND")
          (node (ref "J1") (pin "A1")))))
    """
    assert schematic_transfer._parse_netlist_text(netlist) == {
        ("J1", "A6"): "USB_DP",
        ("U1", "12"): "USB_DP",
        ("J1", "A1"): "GND",
    }

    def fake_run(
        args: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, timeout, check
        out_path = Path(args[args.index("--output") + 1])
        out_path.write_text(netlist, encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(schematic_transfer.subprocess, "run", fake_run)

    exported, note = schematic_transfer._export_schematic_net_map()

    assert note == ""
    assert exported[("J1", "A6")] == "USB_DP"


def test_schematic_transfer_collects_components_and_reports_conflicts(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del sample_project

    parsed: dict[str, list[dict[str, Any]]] = {
        "symbols": [
            {
                "reference": "U1",
                "value": "MCU",
                "footprint": "Package_QFP:LQFP-48",
                "x": 10,
                "y": 20,
                "rotation": 0,
            },
            {
                "reference": "U1",
                "value": "MCU",
                "footprint": "Package_QFP:LQFP-48",
                "x": 14,
                "y": 24,
                "rotation": 90,
            },
            {
                "reference": "R1",
                "value": "10k",
                "footprint": "Resistor_SMD:R_0805",
                "x": 1,
                "y": 2,
                "rotation": 0,
            },
            {
                "reference": "R1",
                "value": "10k",
                "footprint": "Resistor_SMD:R_0603",
                "x": 1,
                "y": 2,
                "rotation": 0,
            },
        ]
    }
    monkeypatch.setattr(schematic_transfer, "parse_schematic_file", lambda _path: parsed)

    components, issues = schematic_transfer._collect_schematic_components()

    assert components == [
        {
            "reference": "U1",
            "value": "MCU",
            "footprint": "Package_QFP:LQFP-48",
            "x": 12.0,
            "y": 22.0,
            "rotation": 0,
        }
    ]
    assert issues == [
        "R1 has conflicting footprint assignments: Resistor_SMD:R_0603, Resistor_SMD:R_0805"
    ]
