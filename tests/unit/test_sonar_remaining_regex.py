"""Regression tests for formerly backtracking-prone Sonar #854 parsing paths."""

import pytest

from kicad_mcp.ir.from_kicad import _rail_name_and_voltage
from kicad_mcp.tools.library import _parse_passive_parametric_query
from kicad_mcp.tools.schematic import _set_label_justify
from kicad_mcp.utils.placement_rules import _has_crystal_frequency
from scripts.runtime_policy import _parse_version


@pytest.mark.parametrize(
    ("source", "parts"),
    [
        ("v1.2.3", (1, 2, 3)),
        ("python3.13", (3, 13, 0)),
        ("12.004.", (12, 4, 0)),
        ("version " + "8" * 60 + ".0.1", (int("8" * 60), 0, 1)),
    ],
)
def test_runtime_version_bounded_parse(source: str, parts: tuple[int, int, int]) -> None:
    version = _parse_version(source)
    assert (version.major, version.minor, version.patch) == parts


@pytest.mark.parametrize("source", ["no numbers", "1.", "v 1", "7."])
def test_runtime_version_rejects_non_version(source: str) -> None:
    with pytest.raises(ValueError, match="Cannot parse version"):
        _parse_version(source)


@pytest.mark.parametrize(
    ("name", "voltage"),
    [("VDD_3V3", 3.3), ("PWR_12V", 12.0), ("5V0", 5.0), ("1.2.3V6", 3.6), ("PWR_VCC", 3.3)],
)
def test_voltage_from_net_name(name: str, voltage: float) -> None:
    assert _rail_name_and_voltage(name)[1] == voltage


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        ("resistor 10k 12v", "12v"),
        ("resistor 10k 4.5 v", "4.5v"),
        ("resistor 10k 1.2.3v", "2.3v"),
        ("resistor 10k noise42v 9v", "9v"),
        ("resistor 10k 5vx", None),
        ("resistor 10k 5    V", "5v"),
        ("resistor 10k 8.2", None),
    ],
)
def test_passive_voltage_token(input_text: str, expected: str | None) -> None:
    query = _parse_passive_parametric_query(input_text)
    assert query is not None
    assert query.voltage == expected


@pytest.mark.parametrize(
    ("value", "detected"),
    [
        ("16MHz", True),
        ("24 khz", True),
        ("5   MHz", True),
        ("12X99", False),
        ("1 mh", False),
        ("no frequency", False),
    ],
)
def test_crystal_frequency_token(value: str, detected: bool) -> None:
    assert _has_crystal_frequency(value) == detected


@pytest.mark.parametrize("replacement", ["", "right"])
def test_label_justify_cleanup(replacement: str) -> None:
    source = '(label "A" (effects (font (size 1 1)  ) (justify left )  ))'
    edited = _set_label_justify(source, replacement)
    assert "(justify left" not in edited
    assert "(justify right)" in edited if replacement else "(justify " not in edited
    assert "(size 1 1)" in edited
