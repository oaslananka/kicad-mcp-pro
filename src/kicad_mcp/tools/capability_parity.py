"""Capability-parity discovery tool (work order P0-T4).

Exposes ``kicad_capability_parity`` so an agent can ask "can this server do X?" and
get an honest answer grounded in the machine-readable parity matrix.
"""

from __future__ import annotations

from typing import cast

from mcp.server.mcpserver import MCPServer as FastMCP

from ..capabilities import metadata_coverage
from ..parity import coverage_summary, find_capabilities, get_matrix, opportunities


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def register(mcp: FastMCP) -> None:
    """Register the capability-parity discovery tool."""

    @mcp.tool()
    def kicad_capability_parity(domain: str = "", query: str = "") -> str:
        """Report how much of KiCad's programmatic surface this server can drive.

        Answers "can I do X with this server?". Pass ``query`` to search capabilities
        by keyword or tool name, ``domain`` to list one domain's capabilities, or
        neither for overall and per-domain coverage plus the biggest open gaps.
        Coverage % = covered / (total - gui-only-no-api); GUI-only-no-api items are
        KiCad API limits, not gaps in this server.
        """
        matrix = get_matrix()
        domains = matrix["domains"]

        if query:
            hits = find_capabilities(query, matrix)
            if not hits:
                return f"No capabilities match '{query}'."
            lines = [f"# Capabilities matching '{query}'", ""]
            for hit in hits:
                tool = f"`{hit['mcp_tool']}`" if hit["mcp_tool"] else "(no tool)"
                lines.append(
                    f"- **{hit['capability']}** [`{hit['domain']}`] — {tool}, "
                    f"status `{hit['status']}`, channel `{hit['kicad_channel']}`."
                )
                if hit["notes"]:
                    lines.append(f"  - {hit['notes']}")
            return "\n".join(lines)

        if domain:
            info = domains.get(domain)
            if info is None:
                available = ", ".join(sorted(domains))
                return f"Unknown domain '{domain}'. Available: {available}"
            stats = coverage_summary(matrix)["domains"][domain]
            lines = [
                f"# Capability parity — `{domain}`",
                str(info.get("description", "")),
                "",
                (
                    f"Coverage: {_pct(stats['coverage_pct'])} "
                    f"({stats['covered']} covered, {stats['partial']} partial, "
                    f"{stats['gap']} gap, {stats['gui_only_no_api']} GUI-only)."
                ),
                "",
            ]
            for cap in info["capabilities"]:
                tool = f"`{cap['mcp_tool']}`" if cap["mcp_tool"] else "(no tool)"
                lines.append(
                    f"- [`{cap['status']}`] **{cap['capability']}** — {tool} "
                    f"via `{cap['kicad_channel']}`."
                )
                if cap["notes"]:
                    lines.append(f"  - {cap['notes']}")
            return "\n".join(lines)

        summary = coverage_summary(matrix)
        overall = summary["overall"]
        metadata = metadata_coverage()
        lines = [
            "# KiCad capability parity",
            f"KiCad baseline `{summary['kicad_baseline']}` · updated {summary['updated']}.",
            "",
            (
                f"**Overall {_pct(overall['coverage_pct'])}** — {overall['covered']} of "
                f"{overall['denominator']} programmatically-reachable capabilities driven "
                f"({overall['partial']} partial, {overall['gap']} gap; "
                f"{overall['gui_only_no_api']} GUI-only with no KiCad API)."
            ),
            "",
            (
                "Tool metadata coverage: "
                f"{metadata['registered_tools']}/{metadata['routed_tools']} routed tools "
                f"({metadata['coverage_pct']:.1f}%)."
            ),
            "",
            "## By domain",
        ]
        missing = cast(list[str], metadata["missing_tools"])
        if missing:
            lines.extend(["## Metadata gaps", *[f"- `{name}`" for name in missing]])
            lines.append("")
        for name, stats in summary["domains"].items():
            lines.append(
                f"- `{name}`: {_pct(stats['coverage_pct'])} "
                f"({stats['covered']}/{stats['denominator']})"
            )
        lines.extend(["", "## Biggest open gaps"])
        for row in opportunities(matrix, limit=8):
            tool = f"`{row['mcp_tool']}`" if row["mcp_tool"] else "(no tool)"
            lines.append(f"- [`{row['status']}`] {row['capability']} [`{row['domain']}`] — {tool}")
        lines.append("")
        lines.append("Query a domain with domain=<name> or search with query=<text>.")
        return "\n".join(lines)
