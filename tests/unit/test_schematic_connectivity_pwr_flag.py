from pathlib import Path

import pytest

from kicad_mcp.tools.schematic import _build_connectivity_groups


def _power_symbol(lib_id: str, reference: str, value: str, x: float, y: float) -> str:
    return (
        "\t(symbol\n"
        f'\t\t(lib_id "{lib_id}")\n'
        f"\t\t(at {x} {y} 0)\n"
        "\t\t(unit 1)\n"
        f'\t\t(property "Reference" "{reference}" (at {x} {y} 0))\n'
        f'\t\t(property "Value" "{value}" (at {x} {y} 0))\n'
        "\t)\n"
    )


def _wire(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"\t(wire (pts (xy {x1} {y1}) (xy {x2} {y2})))\n"


@pytest.mark.parametrize("flag_value", ["PWR_FLAG", "FLAG"])
def test_pwr_flag_does_not_name_or_merge_nets(tmp_path: Path, flag_value: str) -> None:
    """PWR_FLAG has a power_out pin and names no net in KiCad, so two rails that
    each carry one must stay two groups."""
    sch_file = tmp_path / "rails.kicad_sch"
    sch_file.write_text(
        "(kicad_sch\n"
        "\t(version 20250316)\n"
        '\t(generator "pytest")\n'
        '\t(uuid "aa111111-2222-3333-4444-555555555555")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols)\n"
        + _wire(10.16, 10.16, 20.32, 10.16)
        + _power_symbol("power:+5V", "#PWR01", "+5V", 10.16, 10.16)
        + _power_symbol("power:PWR_FLAG", "#FLG01", flag_value, 20.32, 10.16)
        + _wire(10.16, 30.48, 20.32, 30.48)
        + _power_symbol("power:GND", "#PWR02", "GND", 10.16, 30.48)
        + _power_symbol("power:PWR_FLAG", "#FLG02", flag_value, 20.32, 30.48)
        + ")\n",
        encoding="utf-8",
    )

    groups = _build_connectivity_groups(sch_file)

    assert sorted(group["names"] for group in groups) == [["+5V"], ["GND"]]
