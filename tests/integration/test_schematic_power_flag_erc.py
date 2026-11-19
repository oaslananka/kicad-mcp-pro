"""Use KiCad ERC evidence for undriven power rails across all schematic sheets."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_power_flags_reports_native_erc_undriven_pin_on_child_sheet(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def native_erc(_name: str) -> tuple[Path, dict[str, object], None]:
        return (
            sample_project / "output" / "power_flag_erc_report.json",
            {
                "sheets": [
                    {
                        "path": "/Power",
                        "violations": [
                            {
                                "type": "power_pin_not_driven",
                                "severity": "error",
                                "description": "Power input +5V on U1 not driven",
                            }
                        ],
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr("kicad_mcp.tools.validation._run_erc_report", native_erc)
    server = build_server("schematic")
    result = await call_tool_text(server, "sch_check_power_flags", {})
    assert "Undriven power pins" in result, result
    assert "+5V" in result and "/Power" in result, result
    assert "No obvious missing power flags were detected." not in result, result


@pytest.mark.anyio
async def test_power_flags_does_not_claim_clean_when_erc_is_unavailable(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._run_erc_report",
        lambda name: (sample_project / "output" / name, None, "KiCad CLI unavailable"),
    )
    result = await call_tool_text(build_server("schematic"), "sch_check_power_flags", {})
    assert "ERC unavailable" in result, result
    assert "KiCad CLI unavailable" in result, result
