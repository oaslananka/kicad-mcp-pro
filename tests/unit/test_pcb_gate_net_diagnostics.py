"""Per-net unconnected diagnostics and connectivity-evidence checks in the PCB gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kicad_mcp.tools import validation
from kicad_mcp.validation.drc_report import unconnected_nets


def _pair(net_a: str, net_b: str | None = None, *, ref: str = "R1") -> dict[str, Any]:
    net_b = net_a if net_b is None else net_b
    return {
        "type": "unconnected_items",
        "severity": "error",
        "description": "Missing connection between items",
        "items": [
            {"description": f"Pad 1 [{net_a}] of {ref} on F.Cu", "uuid": "a"},
            {"description": f"Track [{net_b}] on F.Cu, length 1.0 mm", "uuid": "b"},
        ],
    }


def _report(**overrides: object) -> dict[str, Any]:
    report: dict[str, Any] = {
        "violations": [],
        "unconnected_items": [],
        "items_not_passing_courtyard": [],
        "ignored_checks": [
            {"description": "Footprint has no courtyard", "key": "missing_courtyard"}
        ],
        "included_severities": ["error", "warning", "exclusion"],
    }
    report.update(overrides)
    return report


def _gate(monkeypatch: pytest.MonkeyPatch, report: dict[str, Any] | None):
    monkeypatch.setattr(
        validation,
        "_run_drc_report",
        lambda name: (Path(name), report, None if report is not None else "boom"),
    )
    # Zone-fill evidence is covered separately; keep these tests about the DRC JSON.
    monkeypatch.setattr(validation, "_zone_fill_check", lambda _report: ([], []), raising=False)
    return validation._evaluate_pcb_gate()


def test_unconnected_nets_groups_items_by_bracketed_net() -> None:
    entries = [_pair("GND"), _pair("GND", ref="R2"), _pair("Net-(IC1A-OUT)"), _pair("+3V3")]

    nets, unparsed = unconnected_nets(entries)

    assert {name: len(rows) for name, rows in nets.items()} == {
        "GND": 2,
        "Net-(IC1A-OUT)": 1,
        "+3V3": 1,
    }
    assert unparsed == 0


def test_unconnected_nets_handles_brackets_inside_net_names_and_localised_text() -> None:
    entry = {
        "type": "unconnected_items",
        "items": [
            {"description": "Pad 3 [DATA[0]] von U1 auf B.Cu"},
            {"description": "Zone [DATA[0]] auf F.Cu und B.Cu, Priorität 1"},
        ],
    }

    nets, unparsed = unconnected_nets([entry])

    assert list(nets) == ["DATA[0]"]
    assert unparsed == 0


def test_unconnected_nets_counts_entries_without_a_parsable_net() -> None:
    entries = [
        {"type": "unconnected_items", "items": [{"description": "no brackets here"}]},
        {"type": "unconnected_items"},
        {"type": "unconnected_items", "items": "not-a-list"},
    ]

    nets, unparsed = unconnected_nets(entries)

    assert nets == {}
    assert unparsed == 3


def test_gate_reports_each_unconnected_net_with_count_and_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(unconnected_items=[_pair("GND"), _pair("GND", ref="C3"), _pair("VCC")])

    outcome = _gate(monkeypatch, report)

    assert outcome.status == "FAIL"
    assert "Unconnected items: 3" in outcome.details
    assert "Unconnected nets: 2" in outcome.details
    gnd = next(d for d in outcome.details if d.startswith("FAIL: net GND"))
    assert "2 unconnected" in gnd
    assert "Pad 1 [GND] of R1 on F.Cu" in gnd
    assert any(d.startswith("FAIL: net VCC") and "1 unconnected" in d for d in outcome.details)


def test_gate_orders_nets_by_count_and_caps_the_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [_pair(f"N{i:02d}") for i in range(30)] + [_pair("BUSY")] * 5
    outcome = _gate(monkeypatch, _report(unconnected_items=entries))

    net_lines = [d for d in outcome.details if d.startswith("FAIL: net ")]
    assert net_lines[0].startswith("FAIL: net BUSY")
    assert len(net_lines) == validation._MAX_UNCONNECTED_NET_LINES
    assert any("more net(s)" in d for d in outcome.details)
    assert "Unconnected nets: 31" in outcome.details


def test_gate_stays_fail_when_no_net_can_be_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _report(unconnected_items=[{"type": "unconnected_items", "description": "x"}])

    outcome = _gate(monkeypatch, report)

    assert outcome.status == "FAIL"
    assert any("no parsable net" in d for d in outcome.details)


def test_gate_is_blocked_when_the_report_has_no_unconnected_items_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report()
    del report["unconnected_items"]

    outcome = _gate(monkeypatch, report)

    assert outcome.status == "BLOCKED"
    assert any(d.startswith("BLOCKED: ") and "unconnected_items" in d for d in outcome.details)


def test_gate_is_blocked_when_the_unconnected_check_was_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(
        ignored_checks=[
            {"description": "Missing connection between items", "key": "unconnected_items"}
        ]
    )

    outcome = _gate(monkeypatch, report)

    assert outcome.status == "BLOCKED"
    assert any("ignored" in d for d in outcome.details)


def test_gate_is_blocked_when_error_severity_was_not_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = _gate(monkeypatch, _report(included_severities=["warning"]))

    assert outcome.status == "BLOCKED"


def test_gate_still_passes_a_complete_clean_report(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = _gate(monkeypatch, _report())

    assert outcome.status == "PASS"
    assert "Unconnected nets: 0" in outcome.details


def test_gate_accepts_reports_without_the_optional_ignored_checks_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = {"violations": [], "unconnected_items": []}

    assert _gate(monkeypatch, report).status == "PASS"


def test_gate_still_blocks_when_drc_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _gate(monkeypatch, None).status == "BLOCKED"
