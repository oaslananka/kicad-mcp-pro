"""DRC report schema classification regressions for issue #496."""

from __future__ import annotations

from kicad_mcp.validation.drc_report import courtyard_violations


def test_courtyard_violations_reads_kicad_10_general_violations() -> None:
    report: dict[str, object] = {
        "violations": [
            {"type": "courtyards_overlap", "uuid": "c1", "description": "Courtyards overlap"},
            {
                "type": "pth_inside_courtyard",
                "uuid": "c2",
                "description": "PTH inside courtyard",
            },
            {
                "type": "npth_inside_courtyard",
                "uuid": "c3",
                "description": "NPTH inside courtyard",
            },
            {"type": "clearance", "uuid": "other", "description": "Clearance"},
        ]
    }

    assert [entry["uuid"] for entry in courtyard_violations(report)] == ["c1", "c2", "c3"]


def test_courtyard_violations_supports_legacy_report_field() -> None:
    legacy = {"uuid": "legacy", "description": "Legacy courtyard issue"}

    assert courtyard_violations({"items_not_passing_courtyard": [legacy]}) == [legacy]


def test_courtyard_violations_deduplicates_current_and_legacy_entries_by_uuid() -> None:
    current = {
        "type": "courtyards_overlap",
        "uuid": "same",
        "description": "Courtyards overlap",
    }
    legacy = {"uuid": "same", "description": "Courtyards overlap"}

    assert courtyard_violations(
        {
            "violations": [current],
            "items_not_passing_courtyard": [legacy],
        }
    ) == [current]


def test_courtyard_violations_ignores_malformed_report_values() -> None:
    assert courtyard_violations(
        {
            "violations": [None, "invalid", {"type": "courtyards_overlap", "uuid": "ok"}],
            "items_not_passing_courtyard": "invalid",
        }
    ) == [{"type": "courtyards_overlap", "uuid": "ok"}]


def test_courtyard_violations_deduplicates_uuid_less_identical_entries() -> None:
    entry = {"type": "courtyards_overlap", "description": "Courtyards overlap"}

    assert courtyard_violations(
        {
            "violations": [entry],
            "items_not_passing_courtyard": [dict(entry)],
        }
    ) == [entry]
