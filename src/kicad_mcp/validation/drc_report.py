"""Schema-aware helpers for KiCad DRC JSON reports."""

from __future__ import annotations

import json

Report = dict[str, object]
ReportEntry = dict[str, object]

COURTYARD_VIOLATION_TYPES: frozenset[str] = frozenset(
    {
        "courtyards_overlap",
        "pth_inside_courtyard",
        "npth_inside_courtyard",
    }
)


def report_entries(report: Report, key: str) -> list[ReportEntry]:
    """Return dictionary entries from one report list, ignoring malformed values."""
    raw = report.get(key)
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def _entry_identity(entry: ReportEntry) -> tuple[str, str]:
    uuid = entry.get("uuid")
    if isinstance(uuid, str) and uuid:
        return ("uuid", uuid)
    return ("json", json.dumps(entry, sort_keys=True, separators=(",", ":")))


def courtyard_violations(report: Report) -> list[ReportEntry]:
    """Extract courtyard findings from current and legacy KiCad DRC report schemas."""
    current = [
        entry
        for entry in report_entries(report, "violations")
        if entry.get("type") in COURTYARD_VIOLATION_TYPES
    ]
    legacy = report_entries(report, "items_not_passing_courtyard")

    result: list[ReportEntry] = []
    seen: set[tuple[str, str]] = set()
    for entry in [*current, *legacy]:
        identity = _entry_identity(entry)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(entry)
    return result
