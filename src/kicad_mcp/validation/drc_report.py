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


def normalize_report_severity(severity: object) -> str:
    """Normalize KiCad DRC/ERC severity values to the public finding contract."""
    normalized = str(severity or "error").casefold()
    if normalized in {"warning", "warn", "marginal"}:
        return "warning"
    return "error"


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


def bracketed_net(description: object) -> str | None:
    """Return the net name in the first bracketed token of a DRC item description.

    KiCad renders items as e.g. ``Pad 1 [GND] of R1 on F.Cu``. Only the words around the
    token are localised, so the bracket is the language-independent part. Brackets inside
    the net name (``DATA[0]``) are kept by balancing nested brackets. Returns ``None`` when
    there is no balanced, non-empty token.
    """
    if not isinstance(description, str):
        return None
    start = description.find("[")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(description)):
        char = description[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                name = description[start + 1 : index].strip()
                return name or None
    return None


def unconnected_nets(
    entries: list[ReportEntry],
) -> tuple[dict[str, list[ReportEntry]], int]:
    """Group ``unconnected_items`` entries by net.

    Returns ``(entries_by_net, unparsed_count)``. An entry whose items carry no parsable
    net is counted in ``unparsed_count`` instead of being dropped, so callers can keep
    treating it as an open connection.
    """
    by_net: dict[str, list[ReportEntry]] = {}
    unparsed = 0
    for entry in entries:
        items = entry.get("items")
        nets: list[str] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = bracketed_net(item.get("description"))
                if name is not None and name not in nets:
                    nets.append(name)
        if not nets:
            unparsed += 1
            continue
        for name in nets:
            by_net.setdefault(name, []).append(entry)
    return by_net, unparsed


def connectivity_evidence_problems(report: Report) -> list[str]:
    """List reasons the DRC JSON cannot prove the board is fully connected.

    A report that lacks the ``unconnected_items`` list, that was produced with the
    unconnected check ignored, or without error-level severities says nothing about
    connectivity, so it must not be read as "zero unconnected items".
    """
    problems: list[str] = []
    if not isinstance(report.get("unconnected_items"), list):
        problems.append(
            "The DRC report has no 'unconnected_items' list, so connectivity was not reported."
        )
    ignored = report.get("ignored_checks")
    if isinstance(ignored, list) and any(
        isinstance(entry, dict) and entry.get("key") == "unconnected_items" for entry in ignored
    ):
        problems.append(
            "The 'unconnected_items' check is ignored in the board's DRC severity settings."
        )
    severities = report.get("included_severities")
    if isinstance(severities, list) and "error" not in severities:
        problems.append("The DRC report did not include error-level violations.")
    return problems
