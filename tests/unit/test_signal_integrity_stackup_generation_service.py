from __future__ import annotations

import pytest
from pydantic import ValidationError

from kicad_mcp.signal_integrity.stackup_generation import (
    SignalIntegrityStackupGenerationService,
    _stackup_templates,
)


def test_generate_preserves_jlcpcb_four_layer_output_contract() -> None:
    result = SignalIntegrityStackupGenerationService().generate(
        layer_count=4,
        target_impedance_ohm=50.0,
        manufacturer="JLCPCB",
        er=4.2,
        copper_oz=1.0,
    )

    assert result.startswith("Recommended 4-layer JLCPCB stackup:\n")
    assert "- Target outer-layer impedance: 50.00 ohm" in result
    assert "- Approximate 100 ohm differential pair starting point:" in result
    assert "- 1. F.Cu | signal | Copper | 0.035 mm" in result
    assert "- 7. B.Cu | signal | Copper | 0.035 mm" in result
    assert result.endswith(
        "- Review with your fabricator's published stackup table before freezing impedance rules."
    )


def test_pcbway_template_preserves_manufacturer_specific_core() -> None:
    template = _stackup_templates("PCBWay", 4)

    assert template[1] == {
        "name": "Prepreg",
        "role": "dielectric",
        "material": "FR4",
        "thickness_mm": 0.17,
    }
    assert template[3]["thickness_mm"] == 1.124


@pytest.mark.parametrize(
    ("manufacturer", "expected_roles"),
    [
        ("PCBWay", ("ground plane", "power / signal")),
        ("JLCPCB", ("solid GND plane", "power / signal")),
    ],
)
def test_four_layer_fabricator_role_contract_remains_stable(
    manufacturer: str, expected_roles: tuple[str, str]
) -> None:
    """Stackup roles are consumed by downstream KiCad layer mapping."""
    template = _stackup_templates(manufacturer, 4)
    actual_names = (template[2]["name"], template[4]["name"])
    actual_roles = (template[2]["role"], template[4]["role"])
    assert actual_names == ("In1.Cu", "In2.Cu")
    assert actual_roles == expected_roles


@pytest.mark.parametrize("manufacturer", ["JLCPCB", "PCBWay", "Generic"])
def test_six_layer_fabricator_inner_copper_names_unchanged(manufacturer: str) -> None:
    template = _stackup_templates(manufacturer, 6)
    assert [entry["name"] for entry in template if str(entry["name"]).startswith("In")] == [
        "In1.Cu",
        "In2.Cu",
        "In3.Cu",
        "In4.Cu",
    ]


def test_generate_preserves_stackup_input_validation() -> None:
    service = SignalIntegrityStackupGenerationService()

    with pytest.raises(ValidationError):
        service.generate(layer_count=3)

    with pytest.raises(ValidationError):
        service.generate(manufacturer="UnknownFab")
