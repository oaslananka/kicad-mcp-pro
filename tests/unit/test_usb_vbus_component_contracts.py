"""USB VBUS named rail aliases remain component-specific and strict."""

from kicad_mcp.tools.validation import _check_symbol_connectivity_and_contracts


def _group(ref: str, net: str) -> dict[str, object]:
    return {
        "pins": [{"reference": ref, "pin": "1"}],
        "names": [net],
        "points": [(0.0, 0.0)],
    }


def _evaluate(lib_id: str, footprint: str, groups: list[str]) -> list[str]:
    symbol = {"reference": "U3", "lib_id": lib_id, "footprint": footprint}
    failures: list[str] = []
    result = _check_symbol_connectivity_and_contracts(
        "Top level", [symbol], [_group("U3", name) for name in groups], failures
    )
    assert result[0] == 1  # Matched a known component contract.
    return failures


def test_usb_c_connector_accepts_hierarchical_usb_vbus() -> None:
    assert (
        _evaluate(
            "Connector:USB_C_Receptacle_USB2.0_16P",
            "Connector_USB:USB_C_Receptacle_GCT_USB4085",
            ["GND", "/USB_VBUS"],
        )
        == []
    )


def test_ap2112_regulator_accepts_hierarchical_usb_vbus() -> None:
    assert (
        _evaluate(
            "Regulator_Linear:AP2112K-3.3",
            "Package_TO_SOT_SMD:SOT-23-5",
            ["GND", "/USB_VBUS", "/3V3"],
        )
        == []
    )


def test_missing_vbus_is_rejected_for_usb_connector() -> None:
    failures = _evaluate(
        "Connector:USB_C_Receptacle_USB2.0_16P",
        "Connector_USB:USB_C_Receptacle_GCT_USB4085",
        ["GND", "/USB_DP", "/USB_DM"],
    )
    assert len(failures) == 1
    assert "missing required nets" in failures[0]


def test_usb_data_net_does_not_count_as_regulator_vbus() -> None:
    failures = _evaluate(
        "Regulator_Linear:AP2112K-3.3",
        "Package_TO_SOT_SMD:SOT-23-5",
        ["GND", "/USB_DP", "3V3"],
    )
    assert len(failures) == 1
    assert "+5V/VBUS" in failures[0]


def test_legacy_vbus_alias_remains_valid() -> None:
    for rail in ("VBUS", "+5V"):
        assert (
            _evaluate(
                "Connector:USB_C_Receptacle_USB2.0_16P",
                "Connector_USB:USB_C_Receptacle_GCT_USB4085",
                ["GND", rail],
            )
            == []
        )
