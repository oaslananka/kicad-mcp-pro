"""Capability-parity computation helpers (work order P0-T4).

Pure functions over the capability-parity matrix. The matrix source of truth is
``docs/compatibility/capability-parity-matrix.yaml``; an embedded, generated copy
ships in :mod:`kicad_mcp.parity_matrix_data` so the runtime ``kicad_capability_parity``
tool needs no YAML dependency (mirroring the :mod:`kicad_mcp.compatibility` pattern).

Coverage % per domain (and overall) = covered / (total - gui_only_no_api): the
fraction of KiCad's *programmatically reachable* surface that an MCP tool drives.
``gui-only-no-api`` rows are excluded from the denominator because they are a KiCad
API limit, not a gap in this server.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STATUSES: tuple[str, ...] = ("covered", "partial", "gap", "gui-only-no-api")
CHANNELS: tuple[str, ...] = ("file", "cli", "ipc", "gui-only")

# Status keys are hyphenated in the matrix; this maps them to identifier-safe keys.
_STATUS_KEY = {
    "covered": "covered",
    "partial": "partial",
    "gap": "gap",
    "gui-only-no-api": "gui_only_no_api",
}


def get_matrix() -> dict[str, Any]:
    """Return a deep copy of the embedded capability-parity matrix."""
    from kicad_mcp.parity_matrix_data import CAPABILITY_PARITY_MATRIX

    return deepcopy(CAPABILITY_PARITY_MATRIX)


def _count(capabilities: list[dict[str, Any]]) -> dict[str, Any]:
    counts = dict.fromkeys(STATUSES, 0)
    for cap in capabilities:
        counts[cap["status"]] += 1
    total = sum(counts.values())
    denominator = total - counts["gui-only-no-api"]
    coverage_pct = round(100.0 * counts["covered"] / denominator, 1) if denominator else 0.0
    summary: dict[str, Any] = {"total": total}
    for status in STATUSES:
        summary[_STATUS_KEY[status]] = counts[status]
    summary["denominator"] = denominator
    summary["coverage_pct"] = coverage_pct
    return summary


def coverage_summary(matrix: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute per-domain and overall coverage statistics for the matrix."""
    if matrix is None:
        matrix = get_matrix()
    domains: dict[str, Any] = matrix["domains"]
    per_domain: dict[str, Any] = {}
    all_caps: list[dict[str, Any]] = []
    for name, info in domains.items():
        caps = info["capabilities"]
        all_caps.extend(caps)
        per_domain[name] = _count(caps)
    return {
        "kicad_baseline": matrix.get("kicad_baseline"),
        "updated": matrix.get("updated"),
        "overall": _count(all_caps),
        "domains": per_domain,
    }


def opportunities(
    matrix: dict[str, Any] | None = None, *, limit: int | None = None
) -> list[dict[str, Any]]:
    """Return the open ``gap`` (then ``partial``) rows — the surface left to close.

    ``gui-only-no-api`` rows are never returned: they are not closeable by us.
    """
    if matrix is None:
        matrix = get_matrix()
    rank = {"gap": 0, "partial": 1}
    rows: list[dict[str, Any]] = []
    for domain, info in matrix["domains"].items():
        for cap in info["capabilities"]:
            if cap["status"] in rank:
                rows.append(
                    {
                        "domain": domain,
                        "capability": cap["capability"],
                        "status": cap["status"],
                        "kicad_channel": cap["kicad_channel"],
                        "mcp_tool": cap["mcp_tool"],
                        "notes": cap["notes"],
                    }
                )
    rows.sort(key=lambda row: (rank[row["status"]], row["domain"], row["capability"]))
    return rows[:limit] if limit else rows


def find_capabilities(query: str, matrix: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return capability rows whose capability text or tool name matches ``query``."""
    if matrix is None:
        matrix = get_matrix()
    needle = query.strip().casefold()
    hits: list[dict[str, Any]] = []
    for domain, info in matrix["domains"].items():
        for cap in info["capabilities"]:
            haystack = f"{cap['capability']} {cap['mcp_tool'] or ''} {cap['notes']}".casefold()
            if not needle or needle in haystack:
                hits.append({"domain": domain, **cap})
    return hits
