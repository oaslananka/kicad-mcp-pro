from __future__ import annotations

import pytest

import kicad_mcp.signal_integrity.differential_pair_skew as skew
from kicad_mcp.models.signal_integrity import DifferentialPairSkewInput
from kicad_mcp.signal_integrity.differential_pair_skew import (
    SignalIntegrityDifferentialPairSkewService,
)


@pytest.mark.parametrize(
    ("skew_mm", "expected"),
    [(1.0, "PASS"), (3.0, "WARN"), (5.0, "FAIL")],
)
def test_analyze_preserves_three_level_verdicts(
    monkeypatch: pytest.MonkeyPatch,
    skew_mm: float,
    expected: str,
) -> None:
    monkeypatch.setattr(skew, "trace_impedance", lambda *_args, **_kwargs: (50.0, 4.0))
    monkeypatch.setattr(skew, "propagation_delay_ps_per_mm", lambda _er: 5.0)

    report = SignalIntegrityDifferentialPairSkewService().analyze(
        payload=DifferentialPairSkewInput(
            net_p="P",
            net_n="N",
            er=4.2,
            trace_type="microstrip",
        ),
        lengths={"P": 100.0, "N": 100.0 + skew_mm},
        skew_budget_ps=10.0,
        track_width_provider=lambda _net: 0.2,
        dielectric_height_provider=lambda: 0.18,
        budget_resolver=lambda _p, _n: (99.0, "unused"),
    )

    assert report.verdict == expected
    assert f"Differential-pair skew analysis ({expected})" in report.text
    assert f"- Skew: {skew_mm:.3f} mm" in report.text
    assert "- Skew budget: 10.0 ps (source: explicit budget 10.0 ps)" in report.text


def test_analyze_preserves_missing_route_configuration_verdict() -> None:
    report = SignalIntegrityDifferentialPairSkewService().analyze(
        payload=DifferentialPairSkewInput(
            net_p="P",
            net_n="N",
            er=4.2,
            trace_type="microstrip",
        ),
        lengths={},
        skew_budget_ps=0.0,
        track_width_provider=lambda _net: 0.2,
        dielectric_height_provider=lambda: 0.18,
        budget_resolver=lambda _p, _n: (10.0, "fixture"),
    )

    assert report.verdict == "WARN"
    assert report.failure_mode == "configuration"
    assert "Could not compute differential-pair skew" in report.text
    assert report.remediation.startswith("Route both differential-pair nets")


def test_analyze_uses_design_intent_budget_when_explicit_budget_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(skew, "trace_impedance", lambda *_args, **_kwargs: (50.0, 4.0))
    monkeypatch.setattr(skew, "propagation_delay_ps_per_mm", lambda _er: 5.0)

    report = SignalIntegrityDifferentialPairSkewService().analyze(
        payload=DifferentialPairSkewInput(
            net_p="USB_DP",
            net_n="USB_DN",
            er=4.2,
            trace_type="microstrip",
        ),
        lengths={"USB_DP": 100.0, "USB_DN": 101.0},
        skew_budget_ps=0.0,
        track_width_provider=lambda _net: 0.18,
        dielectric_height_provider=lambda: 0.18,
        budget_resolver=lambda _p, _n: (8.0, "design-intent interface budget 8.0 ps"),
    )

    assert report.verdict == "PASS"
    assert "- Skew budget: 8.0 ps (source: design-intent interface budget 8.0 ps)" in report.text
