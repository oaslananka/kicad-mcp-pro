"""Precise DRC regression detection for reviewed PCB routing candidates."""

from __future__ import annotations

import pytest

from kicad_mcp.validation.drc_report import newly_reported_drc_violations


def _finding(kind: str, uid: str, x: float = 1.0) -> dict[str, object]:
    return {
        "type": kind,
        "severity": "error",
        "description": "Physical finding",
        "items": [
            {
                "uuid": uid,
                "description": "Track [MID] on F.Cu",
                "pos": {"x": x, "y": 2.0},
            }
        ],
    }


def _report(*violations: dict[str, object]) -> dict[str, object]:
    return {"violations": list(violations), "unconnected_items": []}


def test_same_count_cannot_hide_a_different_new_violation() -> None:
    old = _report(_finding("clearance", "old-track"))
    new = _report(_finding("clearance", "new-track"))

    regressions = newly_reported_drc_violations(old, new)

    assert len(regressions) == 1
    assert regressions[0]["items"][0]["uuid"] == "new-track"


def test_modified_position_is_distinct_from_original_violation() -> None:
    original = _finding("clearance", "unchanged-uuid", x=5.0)
    moved = _finding("clearance", "unchanged-uuid", x=6.0)

    assert newly_reported_drc_violations(_report(original), _report(moved)) == [moved]


def test_order_of_items_and_findings_does_not_create_false_regression() -> None:
    old = _finding("clearance", "item-one")
    old["items"].append({"uuid": "second", "description": "Pad 1", "pos": {"x": 3.0, "y": 2.0}})
    updated = {**old, "items": list(reversed(old["items"]))}
    other = _finding("dangling", "third")

    assert newly_reported_drc_violations(_report(old, other), _report(other, updated)) == []


def test_duplicate_findings_preserve_multiplicity() -> None:
    finding = _finding("clearance", "one")

    assert newly_reported_drc_violations(_report(finding), _report(finding, finding)) == [finding]


def test_removed_violation_is_not_a_regression() -> None:
    assert newly_reported_drc_violations(_report(_finding("clearance", "old")), _report()) == []


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"violations": None},
        {"violations": ["not-a-dict"]},
        {"violations": [{"type": "clearance", "items": "bad"}]},
    ],
)
def test_invalid_drc_report_refuses_success(report: dict[str, object]) -> None:
    _checked_args = (_report(), report)
    with pytest.raises(ValueError):
        newly_reported_drc_violations(*_checked_args)


def _unconnected(net: str) -> dict[str, object]:
    """Match the native KiCad DRC item-description net identity."""
    return {
        "description": "Unconnected items",
        "items": [{"description": f"Pad 1 [{net}] of J1 on F.Cu"}],
    }


def test_route_drc_rejects_newly_unconnected_net_even_when_total_drops() -> None:
    from kicad_mcp.validation.drc_report import evaluate_route_drc

    before = {
        "violations": [],
        "unconnected_items": [_unconnected("USB_D_P"), _unconnected("VBUS")],
    }
    after = {"violations": [], "unconnected_items": [_unconnected("UNRELATED_OPEN")]}

    result = evaluate_route_drc(before, after)

    assert result["accepted"] is False
    assert result["introducedViolations"] == 0
    assert result["unconnectedBefore"] == 2
    assert result["unconnectedAfter"] == 1


def test_route_drc_rejects_unidentifiable_remaining_open_net() -> None:
    from kicad_mcp.validation.drc_report import evaluate_route_drc

    before = {
        "violations": [],
        "unconnected_items": [_unconnected("MID"), _unconnected("VBUS")],
    }
    after = {"violations": [], "unconnected_items": [{"description": "no net identity"}]}

    assert evaluate_route_drc(before, after)["accepted"] is False


def test_route_drc_accepts_improvement_without_any_new_native_finding() -> None:
    from kicad_mcp.validation.drc_report import evaluate_route_drc

    before = {
        "violations": [_finding("clearance", "existing")],
        "unconnected_items": [_unconnected("MID"), _unconnected("VBUS")],
    }
    after = {
        "violations": [_finding("clearance", "existing")],
        "unconnected_items": [_unconnected("VBUS")],
    }

    result = evaluate_route_drc(before, after)

    assert result["accepted"] is True
    assert result["introducedViolations"] == 0
    assert result["unconnectedBefore"] == 2
    assert result["unconnectedAfter"] == 1


def test_route_drc_rejects_same_count_changed_violation() -> None:
    from kicad_mcp.validation.drc_report import evaluate_route_drc

    before = {
        "violations": [_finding("clearance", "existing")],
        "unconnected_items": [{"id": "a"}, {"id": "b"}],
    }
    after = {"violations": [_finding("clearance", "new")], "unconnected_items": [{"id": "a"}]}

    result = evaluate_route_drc(before, after)

    assert result["accepted"] is False
    assert result["introducedViolations"] == 1


def test_route_drc_rejects_no_real_connectivity_improvement() -> None:
    from kicad_mcp.validation.drc_report import evaluate_route_drc

    result = evaluate_route_drc(
        {"violations": [], "unconnected_items": [{"id": "a"}]},
        {"violations": [], "unconnected_items": [{"id": "a"}]},
    )

    assert result["accepted"] is False


def test_route_drc_rejects_untrusted_or_incomplete_reports() -> None:
    from kicad_mcp.validation.drc_report import evaluate_route_drc

    with pytest.raises(ValueError):
        evaluate_route_drc({"violations": []}, {"violations": [], "unconnected_items": []})
    with pytest.raises(ValueError):
        evaluate_route_drc(
            {"violations": [], "unconnected_items": []},
            {"violations": [], "unconnected_items": "invalid"},
        )
