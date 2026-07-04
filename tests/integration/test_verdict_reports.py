"""Structured verdict payloads for high-traffic agent tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.gates import GateOutcome
from tests.conftest import call_tool_payload, call_tool_text


@pytest.mark.anyio
async def test_run_drc_returns_structured_verdict_with_stable_finding_ids(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = {
        "violations": [
            {
                "uuid": "clearance-1",
                "severity": "error",
                "type": "clearance",
                "description": "Clearance violation",
            }
        ],
        "unconnected_items": [],
        "items_not_passing_courtyard": [],
    }

    def fake_run_drc(report_name: str) -> tuple[Path, dict[str, object], None]:
        return sample_project / "output" / report_name, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    first = await call_tool_payload(server, "run_drc", {"save_report": True})
    second = await call_tool_payload(server, "run_drc", {"save_report": True})

    assert isinstance(first, dict)
    assert first["text"].startswith("DRC summary:")
    assert first["verdict"] == "FAIL"
    assert first["findings"][0]["severity"] == "error"
    assert first["findings"][0]["suggested_fix"]["tool"] == "run_drc"
    assert first["findings"][0]["id"] == second["findings"][0]["id"]


@pytest.mark.anyio
async def test_quality_gate_returns_verdict_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_gate",
        lambda: GateOutcome(
            name="Schematic",
            status="FAIL",
            summary="ERC reported blocking issues.",
            details=["FAIL: U1 pin 3 is not connected."],
        ),
    )
    server = build_server("full")

    payload = await call_tool_payload(server, "schematic_quality_gate", {})

    assert isinstance(payload, dict)
    assert payload["text"].startswith("Schematic quality gate: FAIL")
    assert payload["verdict"] == "FAIL"
    assert payload["findings"][0]["location"] == "Schematic"
    assert payload["findings"][0]["suggested_fix"]["tool"] == "sch_annotate"


@pytest.mark.anyio
async def test_project_next_action_includes_verdict_and_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: [
            GateOutcome(
                name="PCB",
                status="FAIL",
                summary="PCB still has blocking physical-rule issues.",
                details=["FAIL: clearance between J1 and U1."],
            )
        ],
    )
    server = build_server("full")

    payload = await call_tool_payload(server, "project_get_next_action", {})

    assert isinstance(payload, dict)
    assert payload["status"] == "FAIL"
    assert payload["verdict"] == "FAIL"
    assert payload["suggested_tool"] == "run_drc()"
    assert payload["findings"][0]["suggested_fix"]["tool"] == "run_drc"


@pytest.mark.anyio
async def test_gate_findings_ignore_informational_metric_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_gate",
        lambda: GateOutcome(
            name="Schematic",
            status="FAIL",
            summary="Schematic still has blocking issues.",
            details=[
                "Pages analysed: 4",
                "Dangling label groups: 0",
                "Zero-wire pages: 0",
                "FAIL: U1 pin 3 is not connected.",
            ],
        ),
    )
    server = build_server("full")

    payload = await call_tool_payload(server, "schematic_quality_gate", {})

    assert isinstance(payload, dict)
    assert payload["verdict"] == "FAIL"
    descriptions = [finding["description"] for finding in payload["findings"]]
    assert descriptions == ["U1 pin 3 is not connected."]


@pytest.mark.anyio
async def test_project_next_action_ignores_metric_details_for_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: [
            GateOutcome(
                name="Schematic connectivity",
                status="FAIL",
                summary="Connectivity smells suggest the schematic is not ready.",
                details=[
                    "Pages analysed: 3",
                    "Dangling label groups: 0",
                    "Zero-wire pages: 0",
                    "FAIL: Sheet 'Power' is required by design intent.",
                ],
            )
        ],
    )
    server = build_server("full")

    payload = await call_tool_payload(server, "project_get_next_action", {})

    assert isinstance(payload, dict)
    assert payload["status"] == "FAIL"
    assert payload["reason"] == "Sheet 'Power' is required by design intent."


@pytest.mark.anyio
async def test_non_passing_gate_without_tagged_details_uses_summary_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_gate",
        lambda: GateOutcome(
            name="Schematic",
            status="FAIL",
            summary="ERC reported blocking issues.",
            details=[
                "Pages analysed: 1",
                "Violations: 0",
            ],
        ),
    )
    server = build_server("full")

    payload = await call_tool_payload(server, "schematic_quality_gate", {})

    assert isinstance(payload, dict)
    assert payload["findings"][0]["description"] == "ERC reported blocking issues."


@pytest.mark.anyio
async def test_pcb_board_summary_returns_verdict_report(mock_board: object) -> None:
    server = build_server("pcb")

    payload = await call_tool_payload(server, "pcb_get_board_summary", {})

    assert isinstance(payload, dict)
    assert payload["text"].startswith("Board summary:")
    assert payload["verdict"] == "PASS"
    assert payload["metadata"]["source"] == "live-gui"
    assert payload["metadata"]["tracks"] == 0


@pytest.mark.anyio
async def test_verdict_findings_include_evidence_remediation_and_retryability(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = {
        "violations": [
            {
                "uuid": "clearance-1",
                "severity": "error",
                "type": "clearance",
                "description": "Clearance violation",
            }
        ],
        "unconnected_items": [],
        "items_not_passing_courtyard": [],
    }

    def fake_run_drc(report_name: str) -> tuple[Path, dict[str, object], None]:
        return sample_project / "output" / report_name, report, None

    monkeypatch.setattr("kicad_mcp.tools.validation._run_drc_report", fake_run_drc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(server, "run_drc", {"save_report": True})

    assert payload["schema_version"] == "verdict.v1"
    assert payload["failure_mode"] == "design"
    assert payload["retryable"] is False
    assert payload["remediation"] == "Fix DRC findings and rerun run_drc(save_report=True)."
    assert payload["evidence"][0]["report_path"].endswith("drc_report.json")
    finding = payload["findings"][0]
    assert finding["failure_mode"] == "design"
    assert finding["retryable"] is False
    assert finding["remediation"].startswith("Fix the drc finding")
    assert finding["evidence"][0]["entry"]["uuid"] == "clearance-1"


@pytest.mark.anyio
async def test_environment_gate_error_is_retryable_and_distinct_from_design_failure(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_erc(report_name: str) -> tuple[Path, None, str]:
        return sample_project / "output" / report_name, None, "kicad-cli unavailable"

    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", fake_run_erc)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(server, "run_erc", {"save_report": True})

    assert payload["verdict"] == "FAIL"
    assert payload["failure_mode"] == "environment"
    assert payload["retryable"] is True
    assert payload["findings"][0]["failure_mode"] == "environment"
    assert payload["findings"][0]["retryable"] is True


@pytest.mark.anyio
async def test_critic_tools_return_standard_verdict_payloads(sample_project, mock_board) -> None:
    server = build_server("full")
    mock_board.get_tracks.return_value = []
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(
        server,
        "si_check_differential_pair_skew",
        {"net_p": "USB_DP", "net_n": "USB_DN"},
    )

    assert payload["schema_version"] == "verdict.v1"
    assert payload["verdict"] == "WARN"
    assert payload["failure_mode"] == "configuration"
    assert payload["findings"][0]["remediation"].startswith("Route both differential-pair nets")
