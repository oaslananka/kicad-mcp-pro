from __future__ import annotations

from types import SimpleNamespace

from kicad_mcp.power_integrity import pdn_mesh_check as module


def test_service_preserves_solver_inputs_and_pass_rendering(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    class FakeMesh:
        def solve(self, **kwargs: object):
            captured.append(kwargs)
            return SimpleNamespace(
                max_drop_mv=12.5,
                violations=[],
                drops_mv={"U1": 8.0, "U2": 12.5},
                impedance_ohm={1_000.0: 0.05},
                max_impedance_ohm=0.05,
                impedance_violations=[],
                recommendations=["Keep decoupling close"],
            )

    monkeypatch.setattr(module, "PdnMesh", FakeMesh)
    report = module.PowerIntegrityPdnMeshService().analyze(
        net_name="3V3",
        source_ref="U_REG",
        load_refs=["U1", "U2"],
        trace_width_mm=0.5,
        load_current_a=0.2,
        trace_length_mm=100.0,
        copper_weight_oz=1.0,
        nominal_voltage_v=3.3,
        frequency_points_hz=[1_000.0],
        decoupling_caps_uf=[0.1, 4.7],
        target_impedance_ohm=0.1,
        decoupling_esr_mohm=20.0,
        decoupling_esl_nh=1.0,
    )

    assert len(captured) == 1
    call = captured[0]
    assert call["net_name"] == "3V3"
    assert call["source_ref"] == "U_REG"
    loads = call["loads"]
    assert [(load.ref, load.current_a, load.distance_mm) for load in loads] == [
        ("U1", 0.2, 50.0),
        ("U2", 0.2, 100.0),
    ]
    caps = call["decoupling_caps"]
    assert [(cap.ref, cap.capacitance_f, cap.esr_ohm, cap.esl_h) for cap in caps] == [
        ("C1", 0.1e-6, 0.02, 1e-9),
        ("C2", 4.7e-6, 0.02, 1e-9),
    ]
    assert call["target_impedance_ohm"] == 0.1

    assert report.verdict == "PASS"
    assert "PDN mesh check:" in report.text
    assert "- U2: 12.50 mV" in report.text
    assert "- Max AC impedance: 0.0500 ohm" in report.text
    assert "- Z(1000 Hz): 0.0500 ohm" in report.text
    assert "- Recommendation: Keep decoupling close" in report.text
    assert "- Method: distributed multi-load resistive PDN mesh" in report.text
    assert report.remediation == ""


def test_service_preserves_failure_verdict_and_remediation(monkeypatch) -> None:
    class FakeMesh:
        def solve(self, **kwargs: object):
            return SimpleNamespace(
                max_drop_mv=150.0,
                violations=["drop too high"],
                drops_mv={"U1": 150.0},
                impedance_ohm={},
                max_impedance_ohm=0.0,
                impedance_violations=["impedance too high"],
                recommendations=[],
            )

    monkeypatch.setattr(module, "PdnMesh", FakeMesh)
    report = module.PowerIntegrityPdnMeshService().analyze(
        net_name="3V3",
        source_ref="U_REG",
        load_refs=["U1"],
        trace_width_mm=0.1,
    )

    assert report.verdict == "FAIL"
    assert "- FAIL: drop too high" in report.text
    assert "- IMPEDANCE FAIL: impedance too high" in report.text
    assert report.summary == "PDN mesh check completed for 3V3 with 2 violation(s)."
    assert report.remediation == (
        "Widen copper, shorten paths, add decoupling, then rerun check_power_integrity()."
    )
