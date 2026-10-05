from __future__ import annotations

from kicad_mcp.power_integrity.voltage_drop import track_resistance_ohm
from kicad_mcp.tools.power_integrity import _ipc_current_capacity_a, _required_width_mm
from kicad_mcp.utils.pdn_mesh import PdnLoad, PdnMesh


def test_track_resistance_and_drop_are_reasonable() -> None:
    resistance_ohm = track_resistance_ohm(0.5, 100.0, 1.0)

    assert 0.09 <= resistance_ohm <= 0.11


def test_ipc_current_capacity_helper_and_required_width_are_consistent() -> None:
    capacity_a = _ipc_current_capacity_a(
        0.5,
        0.035,
        external=True,
        max_temp_rise_c=10.0,
    )
    required_width_mm = _required_width_mm(
        1.0,
        0.035,
        external=True,
        max_temp_rise_c=10.0,
    )

    assert 0.8 <= capacity_a <= 1.6
    assert 0.2 <= required_width_mm <= 0.7


def test_pdn_mesh_reports_voltage_drop_and_violations() -> None:
    result = PdnMesh().solve(
        net_name="+3V3",
        source_ref="U_REG",
        loads=[PdnLoad(ref="U1", current_a=0.5, distance_mm=120.0)],
        trace_width_mm=0.15,
        copper_weight_oz=1.0,
        nominal_voltage_v=3.3,
        tolerance_pct=5.0,
    )

    assert result.max_drop_mv > 0.0
    assert result.violations
    assert "Widen +3V3 traces" in result.recommendations[0]


def test_ipc2221_temperature_rise_physics() -> None:
    """IPC-2221 self-heating estimate behaves physically (work order P3-T2)."""
    from kicad_mcp.utils.pdn_mesh import ipc2221_temperature_rise_c

    # Known-good order of magnitude: 1 A on a 0.5 mm / 1 oz external trace ~ a few C.
    mild = ipc2221_temperature_rise_c(1.0, 0.5, 1.0)
    assert 3.0 < mild < 6.0

    # No current -> no rise.
    assert ipc2221_temperature_rise_c(0.0, 0.5, 1.0) == 0.0

    # Internal traces run hotter than external for the same geometry (less cooling).
    assert ipc2221_temperature_rise_c(1.0, 0.5, 1.0, internal=True) > mild

    # Wider copper runs cooler; an overloaded thin trace gets very hot.
    assert ipc2221_temperature_rise_c(3.0, 2.0, 1.0) < ipc2221_temperature_rise_c(3.0, 0.5, 1.0)
    assert ipc2221_temperature_rise_c(5.0, 0.5, 1.0) > 100.0
