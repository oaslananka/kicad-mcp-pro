from __future__ import annotations

import json
import re

import pytest

from kicad_mcp.models.pcb import SetStackupInput
from kicad_mcp.signal_integrity import stackup_synthesis as synthesis


def test_synthesize_preserves_stackup_report_contract(monkeypatch) -> None:
    selected: list[str] = []
    monkeypatch.setattr(
        synthesis,
        "DIELECTRIC_LIBRARY",
        {
            "fr4_standard": ("FR4", 4.2, 0.02, "standard"),
            "fr4_midloss": ("Midloss", 3.7, 0.01, "midloss"),
        },
    )
    monkeypatch.setattr(
        synthesis,
        "recommend_dielectric_for_frequency",
        lambda _freq: "fr4_midloss",
    )

    def fake_get_dielectric(key: str) -> tuple[str, float, float, str]:
        selected.append(key)
        return ("Fixture laminate", 3.7, 0.009, "fixture material")

    monkeypatch.setattr(synthesis, "get_dielectric", fake_get_dielectric)
    monkeypatch.setattr(synthesis, "solve_width_for_impedance", lambda *_args, **_kwargs: 0.300)
    monkeypatch.setattr(synthesis, "trace_impedance", lambda *_args, **_kwargs: (49.8, 3.7))
    monkeypatch.setattr(
        synthesis,
        "solve_spacing_for_differential_impedance",
        lambda *_args, **_kwargs: 0.170,
    )

    result = synthesis.SignalIntegrityStackupSynthesisService().synthesize(
        interfaces=[
            {
                "kind": "usb3",
                "differential": True,
                "impedance_target_ohm": 90,
            }
        ],
        cost_tier="standard",
        board_thickness_mm=1.2,
    )

    assert selected == ["fr4_midloss"]
    assert result.startswith("# Stackup Synthesis Report\n")
    assert "  usb3: 2.50 GHz, 90ohm diff" in result
    assert "Max interface frequency: 2.50 GHz" in result
    assert "Has differential pairs: True" in result
    assert "Has high-speed signals (&gt;=1 GHz): True" in result
    assert "- Layer count: **6**" in result
    assert "- Dielectric: **Fixture laminate** (Er=3.7, tan_d=0.009)" in result
    assert "- Board thickness: 1.2 mm" in result
    assert "- 50ohm trace width: **0.300 mm** (estimated Z=49.8ohm)" in result
    assert "- 90ohm diff-pair gap: **0.170 mm**" in result
    assert "Material note: fixture material" in result


def test_synthesize_defaults_unknown_cost_tier_to_standard(monkeypatch) -> None:
    selected: list[str] = []
    monkeypatch.setattr(
        synthesis,
        "DIELECTRIC_LIBRARY",
        {"fr4_standard": ("FR4", 4.2, 0.02, "standard")},
    )
    monkeypatch.setattr(
        synthesis,
        "recommend_dielectric_for_frequency",
        lambda _freq: "fr4_standard",
    )
    monkeypatch.setattr(
        synthesis,
        "get_dielectric",
        lambda key: selected.append(key) or ("FR4", 4.2, 0.02, "standard"),
    )
    monkeypatch.setattr(synthesis, "solve_width_for_impedance", lambda *_args, **_kwargs: 0.2)
    monkeypatch.setattr(synthesis, "trace_impedance", lambda *_args, **_kwargs: (50.0, 4.2))
    monkeypatch.setattr(
        synthesis,
        "solve_spacing_for_differential_impedance",
        lambda *_args, **_kwargs: 0.2,
    )

    synthesis.SignalIntegrityStackupSynthesisService().synthesize(
        interfaces=[{"kind": "i2c"}],
        cost_tier="unknown",
    )

    assert selected == ["fr4_standard"]


@pytest.mark.parametrize(
    ("kind", "count"), [("i2c", 2), ("usb2", 4), ("usb3", 6), ("usb3_gen2", 8)]
)
def test_synthesis_returns_valid_candidate_stackup_call(kind: str, count: int) -> None:
    report = synthesis.SignalIntegrityStackupSynthesisService().synthesize(
        [{"kind": kind}], board_thickness_mm=1.6
    )
    actions = [json.loads(x) for x in re.findall(r"```json\n(.*?)\n```", report, re.S)]
    stackup = next(a for a in actions if a["tool"] == "pcb_set_stackup")
    args = stackup["arguments"]
    assert args["allow_open_board"] is False
    payload = SetStackupInput.model_validate({"layers": args["layers"]})
    names = [layer.name for layer in payload.layers if layer.name.endswith(".Cu")]
    assert names == ["F.Cu", *[f"In{i}.Cu" for i in range(1, count - 1)], "B.Cu"]
    assert sum(layer.thickness_mm for layer in payload.layers) == pytest.approx(1.6)
    assert "estimate" in report.casefold()
    assert "fabricator" in report.casefold()
    assert "with layer_count and dielectric params" not in report


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"kind": "usb22"},
        {"kind": "custom"},
        {"kind": "usb2", "differential": "false"},
        {"kind": "usb2", "impedance_target_ohm": -1},
    ],
)
def test_synthesis_rejects_unusable_interface_specs(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="interface"):
        synthesis.SignalIntegrityStackupSynthesisService().synthesize([raw])


def test_synthesis_rejects_impossible_thickness() -> None:
    with pytest.raises(ValueError, match="thickness"):
        synthesis.SignalIntegrityStackupSynthesisService().synthesize(
            [{"kind": "usb3_gen2"}], board_thickness_mm=0.1
        )


def test_synthesis_rejects_empty_interface_list() -> None:
    with pytest.raises(ValueError, match="At least one interface"):
        synthesis.SignalIntegrityStackupSynthesisService().synthesize([])


@pytest.mark.parametrize("thickness", [0.0, -1.0, float("nan"), float("inf")])
def test_synthesis_rejects_nonpositive_or_nonfinite_thickness(thickness: float) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        synthesis.SignalIntegrityStackupSynthesisService().synthesize(
            [{"kind": "usb2"}], board_thickness_mm=thickness
        )
