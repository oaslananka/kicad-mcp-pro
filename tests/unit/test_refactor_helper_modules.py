from __future__ import annotations

import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from kicad_mcp.resources.gate_history import GateHistory, _status
from kicad_mcp.tools import board_file, export_support, routing_rules, schematic_transfer
from kicad_mcp.tools.gates import GateOutcome


def test_board_file_helpers_parse_geometry_nets_and_frame() -> None:
    empty = board_file._normalize_board_content("   ")
    assert f"(version {board_file.BOARD_FILE_VERSION})" in empty
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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, timeout, check
        _ = kwargs
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
    with closing(sqlite3.connect(db_path)) as db:
        with db:
            db.execute("PRAGMA user_version = 999")

    history = GateHistory(db_path)
    with pytest.raises(RuntimeError, match="newer than this server supports"):
        history._init()


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

    assert routing_rules._is_balanced('(rule "test\\"name" (condition "A"))') is True
    assert routing_rules._is_balanced('(rule "open') is False
    assert routing_rules._is_balanced("())") is False


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
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, timeout, check
        _ = kwargs
        out_path = Path(args[args.index("--output") + 1])
        out_path.write_text(netlist, encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(schematic_transfer.subprocess, "run", fake_run)

    exported, note = schematic_transfer._export_schematic_net_map()

    assert note == ""
    assert exported[("J1", "A6")] == "USB_DP"


def test_schematic_transfer_ignores_unidentified_and_non_net_blocks() -> None:
    text = (
        '(network (name "NOT_A_NET") (node (ref "R1") (pin "1")))'
        '(net (code "1") (node (ref "R2") (pin "2")))'
    )

    assert schematic_transfer._parse_netlist_text(text) == {}


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


def test_server_check_status_icon() -> None:
    from kicad_mcp.server import _check_status_icon

    assert _check_status_icon("ok") == "✅"
    assert _check_status_icon("warn") == "⚠️"
    assert _check_status_icon("error") == "❌"
    assert _check_status_icon("unknown") == "❌"


def test_discovery_recent_config_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    import platform

    from kicad_mcp.discovery import _kicad_recent_config_dirs

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    win_dirs = _kicad_recent_config_dirs()
    assert len(win_dirs) == 2
    assert any("AppData" in str(p) for p in win_dirs)

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    mac_dirs = _kicad_recent_config_dirs()
    assert len(mac_dirs) == 2
    assert any("Library" in str(p) for p in mac_dirs)

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    linux_dirs = _kicad_recent_config_dirs()
    assert len(linux_dirs) == 2
    assert any(".config" in str(p) for p in linux_dirs)


def test_diagnostics_evaluate_development_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    from kicad_mcp import diagnostics

    # Missing tool
    monkeypatch.setattr(diagnostics, "_development_tool_version", lambda *args: None)
    tool_diag = diagnostics._evaluate_development_tool(
        "kicad-cli", "live-kicad", "10.0.0", None, ["--version"]
    )
    assert tool_diag.status == "missing"
    assert "Install the supported KiCad CLI" in tool_diag.remediation

    # Version mismatch
    monkeypatch.setattr(diagnostics, "_development_tool_version", lambda *args: "9.0.0")
    tool_diag = diagnostics._evaluate_development_tool(
        "uv", "required", "0.12.0", None, ["--version"]
    )
    assert tool_diag.status == "version-mismatch"
    assert "restore the exact required tool" in tool_diag.remediation

    # OK tool
    monkeypatch.setattr(diagnostics, "_development_tool_version", lambda *args: "0.12.0")
    tool_diag = diagnostics._evaluate_development_tool(
        "uv", "optional", "0.12.0", None, ["--version"]
    )
    assert tool_diag.status == "ok"
    assert "optional development tool" in tool_diag.remediation


def test_diagnostics_evaluate_agent_config_entry() -> None:
    from kicad_mcp.diagnostics import _evaluate_agent_config_entry

    # Valid exists
    res = _evaluate_agent_config_entry(
        "claude-code", "user", {"path": "/a/b", "exists": True, "valid": True}
    )
    assert res.status == "ok"
    assert "config found at /a/b" in res.message

    # Invalid exists
    res = _evaluate_agent_config_entry(
        "claude-code",
        "user",
        {"path": "/a/b", "exists": True, "valid": False, "issues": ["bad token"]},
    )
    assert res.status == "warn"
    assert res.hint == "bad token"

    # Missing
    res = _evaluate_agent_config_entry("codex", "repo", {"path": "/c/d", "exists": False})
    assert res.status == "skipped"
    assert "Run: kicad-mcp-pro setup codex --write" in res.hint


def test_hook_pre_push_predicate_helpers() -> None:
    from scripts.hook_pre_push import (
        _is_architecture_changed,
        _is_tool_surface_changed,
        _is_workflow_changed,
    )

    assert _is_architecture_changed(["src/kicad_mcp/schematic/test.py"])
    assert not _is_architecture_changed(["README.md"])

    assert _is_tool_surface_changed(["src/kicad_mcp/tools/pcb.py"])
    assert not _is_tool_surface_changed(["docs/other.md"])

    assert _is_workflow_changed([".github/workflows/ci.yml"])
    assert _is_workflow_changed(["scripts/check_workflows.py"])
    assert not _is_workflow_changed(["src/kicad_mcp/server.py"])


def test_discovery_collect_cli_help_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp.discovery import _collect_cli_help_outputs

    def fail_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        _ = (args, kwargs)
        raise OSError("kicad-cli timed out")

    monkeypatch.setattr(subprocess, "run", fail_run)
    assert _collect_cli_help_outputs(tmp_path / "kicad-cli") == []

    def success_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        _ = kwargs
        return subprocess.CompletedProcess(
            args=list(args[0]) if isinstance(args[0], (list, tuple)) else ["kicad-cli"],
            returncode=0,
            stdout="help text",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", success_run)
    outputs = _collect_cli_help_outputs(tmp_path / "kicad-cli")
    assert len(outputs) == 5
    assert "help text" in outputs[0]


def test_command_queue_prepare_retry_reconnect_failure() -> None:
    from kicad_mcp.ipc.command_queue import KiCadCommandQueue

    def failing_reconnect() -> None:
        raise RuntimeError("network down")

    queue = KiCadCommandQueue(reconnect=failing_reconnect)
    with pytest.raises(RuntimeError, match="network down"):
        queue._prepare_retry(
            operation="test_op",
            correlation_id="corr-1",
            idempotency_key="idem-1",
            attempts=1,
            started=0.0,
        )
    history = queue.journal
    assert len(history) == 1
    assert history[0].status == "failed"


def test_hierarchy_authoring_resolve_target_sheet_blocks_and_errors(tmp_path: Path) -> None:
    from dataclasses import replace

    from tests.unit.test_schematic_hierarchy_authoring_service import _service

    service, _, _, _, _ = _service(root_path=tmp_path / "root.kicad_sch")

    blocks, err = service._resolve_target_sheet_blocks(
        tmp_path / "root.kicad_sch", "(kicad_sch)", None
    )
    assert blocks == ()
    assert "has no child sheets" in str(err)

    blocks, err = service._resolve_target_sheet_blocks(
        tmp_path / "root.kicad_sch", "(kicad_sch)", "MissingSheet"
    )
    assert blocks == ()
    assert "Sheet 'MissingSheet' was not found" in str(err)

    skipped_sch = '(kicad_sch (sheet (property "Sheetname" "BrokenSheet")))'
    blocks, err = service._resolve_target_sheet_blocks(
        tmp_path / "root.kicad_sch", skipped_sch, "BrokenSheet"
    )
    assert blocks == ()
    assert "cannot be addressed" in str(err)

    def fail_read(p: Path) -> str:
        raise OSError("Read failed")

    service_unreadable = replace(service, read_text=fail_read)
    res = service_unreadable.import_sheet_pins(None, False, False)
    assert "Could not read the top-level schematic" in res


def test_hierarchy_authoring_plan_block_pin_import_overflow_and_errors(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from tests.unit.test_schematic_hierarchy_authoring_service import _service
    from tests.unit.test_sheet_pins_planning import _sheet

    service, _, _, _, _ = _service(root_path=tmp_path / "root.kicad_sch")
    block = _sheet(size=(5.0, 5.0))

    def fail_read(p: Path) -> str:
        raise OSError("cannot read child")

    service_unreadable = replace(service, read_text=fail_read)
    lines, item = service_unreadable._plan_block_pin_import(
        tmp_path / "root.kicad_sch", block, 1.27, False
    )
    assert item is None
    assert "child sheet unreadable" in lines[0]

    labels_sch = """(kicad_sch
      (hierarchical_label "SIG1" (shape input) (at 0 0 0))
      (hierarchical_label "SIG2" (shape input) (at 0 0 0))
      (hierarchical_label "SIG3" (shape input) (at 0 0 0))
      (hierarchical_label "SIG4" (shape input) (at 0 0 0))
      (hierarchical_label "SIG5" (shape input) (at 0 0 0))
      (hierarchical_label "SIG6" (shape input) (at 0 0 0))
      (hierarchical_label "SIG7" (shape input) (at 0 0 0))
      (hierarchical_label "SIG8" (shape input) (at 0 0 0))
    )"""
    service_overflow = replace(service, read_text=lambda p: labels_sch)
    lines, item = service_overflow._plan_block_pin_import(
        tmp_path / "root.kicad_sch", block, 1.27, False
    )
    assert item is None
    assert "pins do not fit at the current size" in lines[0]


def test_schematic_tools_table_uri_and_pin_exceptions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp.tools import schematic

    resolved = schematic._resolve_kicad_table_uri("${KIPRJMOD}/sym-lib-table", tmp_path)
    assert Path(resolved) == tmp_path / "sym-lib-table"

    def fake_get_pin_positions(**kwargs: object) -> dict[str, tuple[float, float]]:
        _ = kwargs
        raise ValueError("Invalid symbol pins")

    monkeypatch.setattr(schematic, "get_pin_positions", fake_get_pin_positions)

    sym = {"lib_id": "Device:R", "x": 10.0, "y": 20.0, "unit": 1, "rotation": 0}
    bounds = schematic._symbol_bbox_bounds(sym)
    assert len(bounds) == 4
    assert bounds[0] < bounds[2]
    assert bounds[1] < bounds[3]
    assert schematic._symbol_local_extent(sym) is None
    _body, pins = schematic._symbol_body_and_pins(sym)
    assert pins == []


def test_server_status_overall_icon_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from kicad_mcp.diagnostics import CheckResult
    from kicad_mcp.server import app
    from tests.unit.test_cli_diagnostics import _diagnostic_report

    runner = CliRunner()

    for check_status, expected_overall in [
        ("ok", "Overall: ok"),
        ("warn", "Overall: degraded"),
        ("error", "Overall: error"),
    ]:
        report = _diagnostic_report([CheckResult(name="chk", status=check_status, message="msg")])
        monkeypatch.setattr("kicad_mcp.server.build_health_report", lambda r=report: r)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert expected_overall in result.output


def test_server_log_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from kicad_mcp.config import KiCadMCPConfig
    from kicad_mcp.server import app

    log_file = tmp_path / "test.log"
    log_file.write_text("INFO message 1\nERROR message 2\n", encoding="utf-8")

    cfg = KiCadMCPConfig(log_file=str(log_file))
    monkeypatch.setattr("kicad_mcp.server.get_config", lambda: cfg)

    runner = CliRunner()
    res = runner.invoke(app, ["log"])
    assert res.exit_code == 0
    assert "INFO message 1" in res.output
    assert "ERROR message 2" in res.output

    res_err = runner.invoke(app, ["log", "--level", "error"])
    assert res_err.exit_code == 0
    assert "ERROR message 2" in res_err.output


@pytest.mark.asyncio
async def test_server_call_tool_kicad_not_running_error() -> None:
    from kicad_mcp.errors import KiCadNotRunningError
    from kicad_mcp.server import KiCadFastMCP

    server = KiCadFastMCP("test-server")

    @server.tool()
    def failing_tool() -> str:
        raise KiCadNotRunningError("KiCad is not running")

    result = await server.call_tool("failing_tool", {})
    assert result is not None


def test_server_init_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from kicad_mcp.server import app

    called = False

    def fake_wizard() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("kicad_mcp.cli_init.run_wizard", fake_wizard)
    runner = CliRunner()
    res = runner.invoke(app, ["init", "--interactive"])
    assert res.exit_code == 0
    assert called


def test_server_status_json_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from kicad_mcp.diagnostics import CheckResult
    from kicad_mcp.server import app
    from tests.unit.test_cli_diagnostics import _diagnostic_report

    runner = CliRunner()
    report = _diagnostic_report([CheckResult(name="chk", status="ok", message="msg")])
    monkeypatch.setattr("kicad_mcp.server.build_health_report", lambda: report)
    res_json = runner.invoke(app, ["status", "--json"])
    assert res_json.exit_code == 0
    assert '"ok": true' in res_json.output

    def fail_health() -> object:
        raise RuntimeError("Health check failure")

    monkeypatch.setattr("kicad_mcp.server.build_health_report", fail_health)
    res_fail = runner.invoke(app, ["status"])
    assert res_fail.exit_code == 1
    assert "Error building status" in res_fail.output


def test_server_log_tail_follow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from kicad_mcp.config import KiCadMCPConfig
    from kicad_mcp.server import _tail_follow, app

    log_file = tmp_path / "test.log"
    log_file.write_text("INFO line 1\n", encoding="utf-8")

    class MockFile:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self) -> MockFile:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def seek(self, *args: object) -> None:
            pass

        def readline(self) -> str:
            self.calls += 1
            if self.calls == 1:
                return "INFO new line\n"
            raise KeyboardInterrupt

    monkeypatch.setattr("builtins.open", lambda *a, **kw: MockFile())
    _tail_follow(log_file, "")

    called_follow = False

    def fake_tail_follow(path: Path, level: str) -> None:
        nonlocal called_follow
        called_follow = True

    monkeypatch.setattr("kicad_mcp.server._tail_follow", fake_tail_follow)
    cfg = KiCadMCPConfig(log_file=str(log_file))
    monkeypatch.setattr("kicad_mcp.server.get_config", lambda: cfg)
    runner = CliRunner()
    res = runner.invoke(app, ["log", "--follow"])
    assert res.exit_code == 0
    assert called_follow


def test_server_init_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kicad_mcp.server import (
        _init_detect_kicad,
        _init_detect_project,
        _init_resolve_agent,
        _init_run_setup,
        _init_verify_health,
    )

    monkeypatch.setattr("kicad_mcp.discovery.discover_kicad_cli", lambda: None)
    _init_detect_kicad()

    proj = tmp_path / "my_proj"
    proj.mkdir()
    (proj / "board.kicad_pcb").write_text("", encoding="utf-8")
    (proj / "board.kicad_sch").write_text("", encoding="utf-8")
    res_p = _init_detect_project(str(proj))
    assert res_p == str(proj)
    _init_detect_project(None)

    agent = _init_resolve_agent("claude-code")
    assert agent == "claude-code"

    _init_run_setup("claude-code", str(proj), "write", False)
    _init_verify_health()
