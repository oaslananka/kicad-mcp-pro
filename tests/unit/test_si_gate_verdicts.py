"""Three-level PASS/WARN/FAIL verdicts for SI gates (work order P1-T3, K2).

Proves each gate can actually FAIL — not just PASS/WARN — by feeding controlled
geometry through the board-access helpers. A gate that can never FAIL is not a gate.
"""

from __future__ import annotations

import pytest

import kicad_mcp.tools.signal_integrity as si
from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.verdicts import three_level_verdict
from tests.conftest import call_tool_text


def test_three_level_verdict_helper() -> None:
    assert three_level_verdict(5, pass_max=10, warn_max=20) == "PASS"
    assert three_level_verdict(10, pass_max=10, warn_max=20) == "PASS"  # boundary
    assert three_level_verdict(15, pass_max=10, warn_max=20) == "WARN"
    assert three_level_verdict(20, pass_max=10, warn_max=20) == "WARN"  # boundary
    assert three_level_verdict(25, pass_max=10, warn_max=20) == "FAIL"


@pytest.fixture
def si_server(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "experimental")
    reset_config()
    return build_server("agent_full")


@pytest.mark.anyio
@pytest.mark.parametrize(("skew_mm", "expected"), [(1.0, "PASS"), (3.0, "WARN"), (5.0, "FAIL")])
async def test_diff_pair_skew_verdicts(
    si_server: object, monkeypatch: pytest.MonkeyPatch, skew_mm: float, expected: str
) -> None:
    # delay 5 ps/mm, explicit budget 10 ps -> FAIL threshold 20 ps.
    # skew 1mm=5ps PASS, 3mm=15ps WARN, 5mm=25ps FAIL.
    monkeypatch.setattr(si, "_track_lengths_by_net", lambda: {"P": 100.0, "N": 100.0 + skew_mm})
    monkeypatch.setattr(si, "_track_width_mm", lambda _net: 0.2)
    monkeypatch.setattr(si, "_outer_dielectric_height_mm", lambda: 0.18)
    monkeypatch.setattr(si, "propagation_delay_ps_per_mm", lambda _er: 5.0)
    out = await call_tool_text(
        si_server,
        "si_check_differential_pair_skew",
        {"net_p": "P", "net_n": "N", "skew_budget_ps": 10.0},
    )
    assert f"({expected})" in out


@pytest.mark.anyio
@pytest.mark.parametrize(("spread_mm", "expected"), [(1.0, "PASS"), (3.0, "WARN"), (5.0, "FAIL")])
async def test_length_matching_verdicts(
    monkeypatch: pytest.MonkeyPatch, spread_mm: float, expected: str
) -> None:
    # tolerance 2 mm -> FAIL threshold 4 mm. spread 1=PASS, 3=WARN, 5=FAIL.
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "experimental")
    monkeypatch.setattr(
        "kicad_mcp.tools.signal_integrity_length_matching._track_lengths_by_net",
        lambda: {"A": 10.0, "B": 10.0 + spread_mm},
    )
    reset_config()
    server = build_server("agent_full")
    out = await call_tool_text(
        server,
        "si_validate_length_matching",
        {"net_groups": [["A", "B"]], "tolerance_mm": 2.0},
    )
    assert f"({expected})" in out


@pytest.mark.anyio
@pytest.mark.parametrize(("distance_mm", "expected"), [(1.0, "PASS"), (3.0, "WARN"), (5.0, "FAIL")])
async def test_decoupling_placement_verdicts(
    si_server: object, monkeypatch: pytest.MonkeyPatch, distance_mm: float, expected: str
) -> None:
    # recommended 2 mm -> FAIL threshold 4 mm. distance 1=PASS, 3=WARN, 5=FAIL.
    monkeypatch.setattr(si, "recommended_decoupling_distance_mm", lambda _f: 2.0)
    monkeypatch.setattr(si, "_find_power_anchor", lambda _ic, _pin: (0.0, 0.0))
    monkeypatch.setattr(
        si, "_nearest_capacitors", lambda _ic, _x, _y: [("C1", distance_mm, "100nF")]
    )
    out = await call_tool_text(
        si_server,
        "si_calculate_decoupling_placement",
        {"ic_ref": "U1", "power_pin": "1", "target_freq_mhz": 100.0},
    )
    assert f"({expected};" in out
