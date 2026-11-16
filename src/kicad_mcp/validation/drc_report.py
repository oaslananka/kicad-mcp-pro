"""Schema-aware helpers for KiCad DRC JSON reports."""

from __future__ import annotations

import json
from collections import Counter

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


def _entry_net_names(entry: ReportEntry) -> list[str]:
    """Find unique, ordered net names on a DRC unconnected item."""
    items = entry.get("items")
    nets: list[str] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            name = bracketed_net(item.get("description"))
            if name is not None and name not in nets:
                nets.append(name)
    return nets


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
        nets = _entry_net_names(entry)
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


def _violation_identity(entry: ReportEntry) -> str:
    """Use finding type and exact native item identity, not only issue totals.

    Descriptions, UUIDs and locations distinguish same-type violations on
    different copper. Report timestamps and source paths are intentionally
    excluded so identical saved-board issues remain stable across DRC runs.
    """
    kind = entry.get("type")
    if not isinstance(kind, str) or not kind:
        raise ValueError("DRC violation type is missing or malformed")
    items = entry.get("items", [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("DRC violation items must be a list of objects")
    normalized_items = sorted(
        json.dumps(
            {
                "uuid": item.get("uuid"),
                "description": item.get("description"),
                "pos": item.get("pos"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for item in items
    )
    return json.dumps(
        {
            "type": kind,
            "severity": normalize_report_severity(entry.get("severity")),
            "excluded": entry.get("excluded", False),
            "description": entry.get("description", ""),
            "items": normalized_items,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def newly_reported_drc_violations(
    before: Report,
    after: Report,
) -> list[ReportEntry]:
    """Return native PCB violations newly introduced by an attempted change.

    Compares a multiset of native finding identities. This detects a new
    violation replacing an old one even when the total count stays constant.
    Does NOT evaluate unrouted connections: check those separately with the
    native DRC unconnected_items list. Invalid/missing evidence fails closed.
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("Both DRC reports must be objects")

    def entries(report: Report) -> list[ReportEntry]:
        raw = report.get("violations")
        if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
            raise ValueError("DRC violations must be a list of objects")
        return raw

    remaining = Counter(_violation_identity(item) for item in entries(before))
    introduced: list[ReportEntry] = []
    for item in entries(after):
        identity = _violation_identity(item)
        if remaining[identity]:
            remaining[identity] -= 1
        else:
            introduced.append(item)
    return introduced


def evaluate_route_drc(
    before: Report,
    after: Report,
    *,
    routed_nets: frozenset[str] | None = None,
) -> dict[str, bool | int]:
    """Refuse a routing candidate that adds native DRC errors or fails to connect pads.

    Both reports must explicitly contain native violations and unconnected items.
    Report counts alone cannot establish non-regression: use finding identity.
    When routed_nets is supplied, verify that only those nets become more
    connected. KiCad can silently reconcile a mislabelled candidate copper
    segment's net to the pad it touches without reporting a short.
    """

    def count_unconnected(report: Report) -> int:
        entries = report.get("unconnected_items")
        if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
            raise ValueError("Native DRC unconnected_items list is missing or malformed")
        return len(entries)

    previous = count_unconnected(before)
    current = count_unconnected(after)
    introduced = newly_reported_drc_violations(before, after)
    previous_nets, unidentified_previous = unconnected_nets(
        report_entries(before, "unconnected_items")
    )
    current_nets, unidentified_current = unconnected_nets(
        report_entries(after, "unconnected_items")
    )
    newly_open_nets = current_nets.keys() - previous_nets.keys()
    scoped_connectivity_ok = True
    if routed_nets is not None:
        improved = {
            net
            for net, entries in previous_nets.items()
            if len(current_nets.get(net, [])) < len(entries)
        }
        regressed = any(
            len(entries) > len(previous_nets.get(net, [])) for net, entries in current_nets.items()
        )
        scoped_connectivity_ok = (
            bool(improved)
            and improved <= routed_nets
            and not regressed
            and not unidentified_previous
        )
    # A lower global count cannot excuse disconnecting a previously connected net.
    # If KiCad cannot identify a remaining open net, refuse the candidate.
    return {
        "accepted": not introduced
        and current < previous
        and not newly_open_nets
        and not unidentified_current
        and scoped_connectivity_ok,
        "introducedViolations": len(introduced),
        "unconnectedBefore": previous,
        "unconnectedAfter": current,
    }
