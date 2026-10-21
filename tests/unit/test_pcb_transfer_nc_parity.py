"""KiCad-generated no-connect pad parity regression tests."""

import pytest

from kicad_mcp.tools.validation import _check_pad_net_match, _compare_ref_pad_nets


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("unconnected-(J1-SBU1-PadA8)", "unconnected-(J1-SBU1-PadA8)"),
        ("unconnected-(J2-NC/TDI-Pad8)", "unconnected-(J2-NC{slash}TDI-Pad8)"),
        ("unconnected-(J2-NC{slash}TDI-Pad8)", "unconnected-(J2-NC{slash}TDI-Pad8)"),
        ("unconnected-(J2-NC{slash}TDI-Pad8)", "unconnected-(J2-NC/TDI-Pad8)"),
        ("unconnected-(J2-SWO{slash}TDO-Pad6)", "unconnected-(J2-SWO{slash}TDO-Pad6)"),
        ("unconnected-(U3-NC-Pad4)", ""),
    ],
)
def test_valid_generated_no_connect_pads_match(expected: str, actual: str) -> None:
    assert _check_pad_net_match("J2", "8", expected, actual) == (True, None)


@pytest.mark.parametrize(
    "incorrect",
    ["GND", "unconnected-(J2-OTHER-Pad7)", "unconnected-(U3-NC-Pad4)"],
)
def test_no_connect_pad_rejects_unsafe_or_misidentified_net(incorrect: str) -> None:
    passed, reason = _check_pad_net_match("J2", "8", "unconnected-(J2-NC/TDI-Pad8)", incorrect)
    assert not passed
    assert reason is not None
    assert "expected unconnected net" in reason


def test_named_copper_nets_still_require_exact_match() -> None:
    assert _check_pad_net_match("U1", "8", "GND", "GND") == (True, None)
    passed, reason = _check_pad_net_match("U1", "8", "GND", "/3V3")
    assert not passed
    assert reason is not None
    assert "expected 'GND'" in reason


def test_transfer_coverage_counts_generated_no_connect_pads() -> None:
    expected = [
        ("A8", "unconnected-(J1-SBU1-PadA8)"),
        ("B8", "unconnected-(J1-SBU2-PadB8)"),
        ("A7", "/USB_DM"),
    ]
    actual = {
        "A8": "unconnected-(J1-SBU1-PadA8)",
        "B8": "unconnected-(J1-SBU2-PadB8)",
        "A7": "/USB_DM",
    }
    matched, issues = _compare_ref_pad_nets("J1", expected, actual)
    assert matched == 3
    assert issues == []
