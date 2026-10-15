"""Unit tests for the .kicad_dru conflict analyzer (issue #202)."""

from __future__ import annotations

from kicad_mcp.utils.dru import parse_dru
from kicad_mcp.utils.dru_analysis import analyze_rule_conflicts, parse_dimension_mm


def _analyze(dru_text: str) -> list:
    root, _version = parse_dru(dru_text)
    return analyze_rule_conflicts(root)


def test_parse_dimension_units() -> None:
    assert parse_dimension_mm("0.2mm") == 0.2
    assert parse_dimension_mm("0.2") == 0.2
    assert parse_dimension_mm("5mil") == 5 * 0.0254
    assert parse_dimension_mm("0.01in") == 0.01 * 25.4
    assert parse_dimension_mm("100um") == 0.1
    assert parse_dimension_mm("garbage") is None


def test_clean_rules_have_no_conflicts() -> None:
    dru = (
        "(rules\n"
        '  (rule "hs_clearance" (condition "A.NetClass == \'HS\'")'
        " (constraint clearance (min 0.2mm)))\n"
        '  (rule "pwr_width" (condition "A.NetClass == \'PWR\'")'
        " (constraint track_width (min 0.5mm)))\n"
        ")\n"
    )
    assert _analyze(dru) == []


def test_duplicate_rule_name_is_flagged() -> None:
    dru = (
        "(rules\n"
        '  (rule "clr" (constraint clearance (min 0.2mm)))\n'
        '  (rule "clr" (constraint clearance (min 0.3mm)))\n'
        ")\n"
    )
    conflicts = _analyze(dru)
    dupes = [c for c in conflicts if c.kind == "duplicate_name"]
    assert len(dupes) == 1
    assert dupes[0].severity == "error"
    assert dupes[0].rules == ("clr",)


def test_contradictory_min_for_same_condition_is_flagged() -> None:
    dru = (
        "(rules\n"
        '  (rule "a" (condition "A.NetClass == \'HS\'") (constraint clearance (min 0.2mm)))\n'
        '  (rule "b" (condition "A.NetClass == \'HS\'") (constraint clearance (min 0.3mm)))\n'
        ")\n"
    )
    conflicts = _analyze(dru)
    contradict = [c for c in conflicts if c.kind == "contradictory_constraint"]
    assert len(contradict) == 1
    assert contradict[0].severity == "warning"
    assert set(contradict[0].rules) == {"a", "b"}


def test_same_condition_same_value_is_not_flagged() -> None:
    dru = (
        "(rules\n"
        '  (rule "a" (condition "A.NetClass==\'HS\'") (constraint clearance (min 0.2mm)))\n'
        # Different whitespace/quote style but the same normalized condition + value.
        '  (rule "b" (condition "A.NetClass == \'HS\'") (constraint clearance (min 0.2mm)))\n'
        ")\n"
    )
    assert not any(c.kind == "contradictory_constraint" for c in _analyze(dru))


def test_inverted_bounds_are_flagged() -> None:
    dru = '(rules (rule "r" (constraint track_width (min 0.6mm) (max 0.2mm))))\n'
    conflicts = _analyze(dru)
    inverted = [c for c in conflicts if c.kind == "inverted_bounds"]
    assert len(inverted) == 1
    assert inverted[0].severity == "error"


def test_negative_dimension_is_flagged() -> None:
    dru = '(rules (rule "r" (constraint clearance (min -0.1mm))))\n'
    conflicts = _analyze(dru)
    negative = [c for c in conflicts if c.kind == "negative_dimension"]
    assert len(negative) == 1
    assert negative[0].severity == "error"


def test_errors_sort_before_warnings() -> None:
    dru = (
        "(rules\n"
        '  (rule "a" (condition "A.NetClass==\'HS\'") (constraint clearance (min 0.2mm)))\n'
        '  (rule "b" (condition "A.NetClass==\'HS\'") (constraint clearance (min 0.3mm)))\n'
        '  (rule "a" (constraint clearance (min 0.2mm)))\n'
        ")\n"
    )
    conflicts = _analyze(dru)
    assert conflicts == sorted(conflicts, key=lambda c: c.sort_key())
    assert conflicts[0].severity == "error"


def test_dimension_parser_accepts_decimal_boundaries_without_backtracking() -> None:
    assert parse_dimension_mm(".5mm") == 0.5
    assert parse_dimension_mm("+12.25mm") == 12.25
    assert parse_dimension_mm("-2mil") == -2 * 0.0254
    assert parse_dimension_mm("12.") is None
    assert parse_dimension_mm("9" * 3000 + "x") is None
