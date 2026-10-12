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
def test_unmapped_capabilities_report_no_tool_in_every_view(
    monkeypatch: pytest.MonkeyPatch, view: str
) -> None:
    """Gaps must never appear as connected or registered MCP tools."""
    missing: dict[str, Any] = {
        "capability": "Unmapped test feature",
        "domain": "test",
        "mcp_tool": None,
        "status": "gap",
        "kicad_channel": "gui-only",
        "notes": "",
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
