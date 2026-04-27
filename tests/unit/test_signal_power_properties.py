from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from kicad_mcp.tools.power_integrity import (
    _ipc_current_capacity_a,
    _required_width_mm,
    _track_resistance_ohm,
)
from kicad_mcp.utils.impedance import (
    solve_width_for_impedance,
    trace_impedance,
    via_stub_resonance_ghz,
)


@settings(max_examples=50)
@given(
    width_mm=st.floats(min_value=0.05, max_value=5.0, allow_nan=False, allow_infinity=False),
    length_a_mm=st.floats(min_value=1.0, max_value=250.0, allow_nan=False, allow_infinity=False),
    length_b_mm=st.floats(min_value=1.0, max_value=250.0, allow_nan=False, allow_infinity=False),
    copper_oz=st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
)
def test_pdn_trace_resistance_increases_with_length(
    width_mm: float,
    length_a_mm: float,
    length_b_mm: float,
    copper_oz: float,
) -> None:
    shorter, longer = sorted((length_a_mm, length_b_mm))

    short_resistance = _track_resistance_ohm(width_mm, shorter, copper_oz)
    long_resistance = _track_resistance_ohm(width_mm, longer, copper_oz)

    assert long_resistance >= short_resistance


@settings(max_examples=50)
@given(
    expected_current_a=st.floats(
        min_value=0.05,
        max_value=8.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    copper_thickness_mm=st.floats(
        min_value=0.017,
        max_value=0.105,
        allow_nan=False,
        allow_infinity=False,
    ),
    max_temp_rise_c=st.floats(
        min_value=5.0,
        max_value=40.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    external=st.booleans(),
)
def test_pdn_required_width_meets_current_capacity(
    expected_current_a: float,
    copper_thickness_mm: float,
    max_temp_rise_c: float,
    external: bool,
) -> None:
    width_mm = _required_width_mm(
        expected_current_a,
        copper_thickness_mm,
        external=external,
        max_temp_rise_c=max_temp_rise_c,
    )

    capacity_a = _ipc_current_capacity_a(
        width_mm,
        copper_thickness_mm,
        external=external,
        max_temp_rise_c=max_temp_rise_c,
    )

    assert capacity_a >= expected_current_a * 0.999


@settings(max_examples=50)
@given(
    seed_width_mm=st.floats(min_value=0.02, max_value=4.0, allow_nan=False, allow_infinity=False),
    height_mm=st.floats(min_value=0.08, max_value=1.2, allow_nan=False, allow_infinity=False),
    er=st.floats(min_value=2.5, max_value=6.5, allow_nan=False, allow_infinity=False),
    copper_oz=st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False),
)
def test_trace_width_solver_round_trips_to_target_impedance(
    seed_width_mm: float,
    height_mm: float,
    er: float,
    copper_oz: float,
) -> None:
    target_ohm, _ = trace_impedance(
        seed_width_mm,
        height_mm,
        er,
        trace_type="microstrip",
        copper_oz=copper_oz,
    )
    width_mm = solve_width_for_impedance(
        target_ohm,
        height_mm,
        er,
        trace_type="microstrip",
        copper_oz=copper_oz,
    )
    solved_ohm, _effective_er = trace_impedance(
        width_mm,
        height_mm,
        er,
        trace_type="microstrip",
        copper_oz=copper_oz,
    )

    assert math.isclose(solved_ohm, target_ohm, rel_tol=0.02, abs_tol=0.5)


@settings(max_examples=50)
@given(
    short_stub_mm=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
    extra_length_mm=st.floats(min_value=0.05, max_value=3.0, allow_nan=False, allow_infinity=False),
    er=st.floats(min_value=2.5, max_value=6.5, allow_nan=False, allow_infinity=False),
)
def test_thermal_via_stub_resonance_decreases_as_stub_gets_longer(
    short_stub_mm: float,
    extra_length_mm: float,
    er: float,
) -> None:
    short_resonance = via_stub_resonance_ghz(short_stub_mm, er=er)
    long_resonance = via_stub_resonance_ghz(short_stub_mm + extra_length_mm, er=er)

    assert long_resonance < short_resonance
