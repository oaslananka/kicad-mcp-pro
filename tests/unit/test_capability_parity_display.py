"""Preserve honest, user-visible capability parity descriptions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from kicad_mcp.tools import capability_parity


class _ToolCollector:
    def __init__(self) -> None:
        self.fn: Callable[..., str] | None = None

    def tool(self) -> Callable[[Callable[..., str]], Callable[..., str]]:
        def capture(fn: Callable[..., str]) -> Callable[..., str]:
            self.fn = fn
            return fn

        return capture


@pytest.mark.parametrize("view", ["query", "domain", "summary"])
@pytest.mark.parametrize("notes", ["", "Source lacks a native API"])
def test_unmapped_capabilities_report_no_tool_in_every_view(
    monkeypatch: pytest.MonkeyPatch, view: str, notes: str
) -> None:
    """Gaps must never appear as connected or registered MCP tools."""
    missing: dict[str, Any] = {
        "capability": "Unmapped test feature",
        "domain": "test",
        "mcp_tool": None,
        "status": "gap",
        "kicad_channel": "gui-only",
        "notes": notes,
    }
    monkeypatch.setattr(
        capability_parity,
        "get_matrix",
        lambda: {
            "domains": {
                "test": {
                    "description": "Representative unimplemented feature",
                    "capabilities": [missing],
                }
            }
        },
    )
    monkeypatch.setattr(capability_parity, "find_capabilities", lambda *_: [missing])
    monkeypatch.setattr(capability_parity, "opportunities", lambda *_args, **_kwargs: [missing])
    monkeypatch.setattr(
        capability_parity,
        "coverage_summary",
        lambda *_: {
            "kicad_baseline": "10",
            "updated": "2026-10-13",
            "overall": {
                "coverage_pct": 0.0,
                "covered": 0,
                "denominator": 1,
                "partial": 0,
                "gap": 1,
                "gui_only_no_api": 0,
            },
            "domains": {
                "test": {
                    "coverage_pct": 0.0,
                    "covered": 0,
                    "denominator": 1,
                    "partial": 0,
                    "gap": 1,
                    "gui_only_no_api": 0,
                }
            },
        },
    )
    monkeypatch.setattr(
        capability_parity,
        "metadata_coverage",
        lambda: {
            "registered_tools": 0,
            "routed_tools": 0,
            "coverage_pct": 0.0,
            "missing_tools": [],
        },
    )
    collector = _ToolCollector()
    capability_parity.register(collector)  # type: ignore[arg-type]
    assert collector.fn is not None
    kwargs = (
        {"query": "Unmapped"} if view == "query" else {"domain": "test"} if view == "domain" else {}
    )
    output = collector.fn(**kwargs)
    assert "Unmapped test feature" in output
    assert "(no tool)" in output
    assert "`gap`" in output
    if notes and view != "summary":
        assert notes in output


def test_capability_reports_unknown_queries_and_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability_parity, "find_capabilities", lambda *_args: [])
    matrix: dict[str, Any] = {"domains": {"pcb": {"capabilities": []}}}
    assert capability_parity._render_capability_matches("no-match", matrix) == (
        "No capabilities match 'no-match'."
    )
    assert capability_parity._render_capability_domain("unknown", matrix) == (
        "Unknown domain 'unknown'. Available: pcb"
    )


def test_capability_summary_reports_missing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = {
        "kicad_baseline": "10",
        "updated": "2026-10-29",
        "overall": {
            "coverage_pct": 50.0,
            "covered": 1,
            "denominator": 2,
            "partial": 0,
            "gap": 1,
            "gui_only_no_api": 0,
        },
        "domains": {
            "pcb": {
                "coverage_pct": 50.0,
                "covered": 1,
                "denominator": 2,
            }
        },
    }
    monkeypatch.setattr(capability_parity, "coverage_summary", lambda *_args: summary)
    monkeypatch.setattr(
        capability_parity,
        "metadata_coverage",
        lambda: {
            "registered_tools": 1,
            "routed_tools": 2,
            "coverage_pct": 50.0,
            "missing_tools": ["pcb_missing_tool"],
        },
    )
    monkeypatch.setattr(capability_parity, "opportunities", lambda *_args, **_kwargs: [])
    output = capability_parity._render_capability_overview({})
    assert "## Metadata gaps" in output
    assert "`pcb_missing_tool`" in output
    assert "`pcb`: 50.0% (1/2)" in output
