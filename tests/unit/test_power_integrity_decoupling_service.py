from __future__ import annotations

from kicad_mcp.models.power_integrity import DecouplingRecommendationInput
from kicad_mcp.power_integrity.decoupling import PowerIntegrityDecouplingService


def _payload(*, ripple_mv: float = 20.0) -> DecouplingRecommendationInput:
    return DecouplingRecommendationInput(
        ic_refs=["U1", "U2"],
        vcc_net="3V3",
        supply_voltage_v=3.3,
        target_ripple_mv=ripple_mv,
    )


def test_service_preserves_recommendation_output_contract() -> None:
    result = PowerIntegrityDecouplingService().recommend(
        payload=_payload(),
        references=["U1", "U2"],
        recommendation_mm=2.5,
        nearby_by_ref={
            "U1": [("C1", 1.0, "100n")],
            "U2": [("C2", 4.0, "")],
        },
    )

    assert result.startswith("Decoupling recommendation for 3V3:\n")
    assert "- Supply voltage: 3.300 V" in result
    assert "- Target ripple: 20.00 mV" in result
    assert "- Baseline local decoupler per IC: 100 nF X7R placed at the power pin" in result
    assert "- Shared bulk recommendation near rail entry: 9.4 uF low-ESR" in result
    assert "- U1: nearest capacitor is C1 (100n) at 1.000 mm [OK]" in result
    assert "- U2: nearest capacitor is C2 (unknown) at 4.000 mm [MOVE CLOSER]" in result


def test_service_preserves_missing_cap_guidance() -> None:
    result = PowerIntegrityDecouplingService().recommend(
        payload=_payload(),
        references=["U1"],
        recommendation_mm=3.25,
        nearby_by_ref={"U1": []},
    )

    assert "- U1: add one 100 nF local cap within 3.25 mm" in result
    assert "- U2:" not in result


def test_service_preserves_ripple_scaling_and_uses_all_ics_for_bulk() -> None:
    payload = DecouplingRecommendationInput(
        ic_refs=["U1", "U2", "U3"],
        vcc_net="1V8",
        supply_voltage_v=1.8,
        target_ripple_mv=10.0,
    )

    result = PowerIntegrityDecouplingService().recommend(
        payload=payload,
        references=["U1"],
        recommendation_mm=1.0,
        nearby_by_ref={"U1": []},
    )

    assert "- Shared bulk recommendation near rail entry: 28.2 uF low-ESR" in result
    assert "- U1:" in result
    assert "- U2:" not in result
