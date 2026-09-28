from pathlib import Path

import pytest

from kicad_mcp.tools import schematic

# Pin geometry copied from the KiCad 10.0.6 stock Device library.
DEVICE_LIBRARY = """(kicad_symbol_lib
  (symbol "LED"
    (symbol "LED_1_1"
      (pin passive line (at -3.81 0 0) (length 1.27) (name "K") (number "1"))
      (pin passive line (at 3.81 0 180) (length 1.27) (name "A") (number "2"))
    )
  )
  (symbol "R"
    (symbol "R_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
      (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))
    )
  )
)
"""

# Pin positions for a symbol placed at (100, 100), as reported by KiCad 10.0.6
# (`kicad-cli sch erc --format json` pin_not_connected locations).
KICAD_PIN_POSITIONS = [
    ("LED", 0, {"1": (96.19, 100.0), "2": (103.81, 100.0)}),
    ("LED", 90, {"1": (100.0, 103.81), "2": (100.0, 96.19)}),
    ("LED", 180, {"1": (103.81, 100.0), "2": (96.19, 100.0)}),
    ("LED", 270, {"1": (100.0, 96.19), "2": (100.0, 103.81)}),
    ("R", 0, {"1": (100.0, 96.19), "2": (100.0, 103.81)}),
    ("R", 90, {"1": (96.19, 100.0), "2": (103.81, 100.0)}),
    ("R", 180, {"1": (100.0, 103.81), "2": (100.0, 96.19)}),
    ("R", 270, {"1": (103.81, 100.0), "2": (96.19, 100.0)}),
]


@pytest.fixture
def device_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library = tmp_path / "Device.kicad_sym"
    library.write_text(DEVICE_LIBRARY, encoding="utf-8")
    monkeypatch.setattr(schematic, "_symbol_library_file", lambda _library: library)


@pytest.mark.usefixtures("device_library")
@pytest.mark.parametrize(("symbol", "rotation", "expected"), KICAD_PIN_POSITIONS)
def test_pin_positions_match_kicad_for_each_rotation(
    symbol: str, rotation: int, expected: dict[str, tuple[float, float]]
) -> None:
    assert schematic.get_pin_positions("Device", symbol, 100.0, 100.0, rotation) == expected


@pytest.mark.usefixtures("device_library")
@pytest.mark.parametrize(("symbol", "rotation", "expected"), KICAD_PIN_POSITIONS)
def test_pin_alias_positions_match_kicad_for_each_rotation(
    symbol: str, rotation: int, expected: dict[str, tuple[float, float]]
) -> None:
    aliases = schematic.get_pin_alias_positions("Device", symbol, 100.0, 100.0, rotation)

    assert {pin: aliases[pin] for pin in expected} == expected
    if symbol == "LED":
        assert aliases["K"] == expected["1"]
        assert aliases["A"] == expected["2"]


# KiCad applies (mirror x|y) after rotating; same ERC source as above.
KICAD_MIRRORED_PIN_POSITIONS = [
    ("LED", 0, "x", {"1": (96.19, 100.0), "2": (103.81, 100.0)}),
    ("LED", 90, "x", {"1": (100.0, 96.19), "2": (100.0, 103.81)}),
    ("LED", 180, "x", {"1": (103.81, 100.0), "2": (96.19, 100.0)}),
    ("LED", 270, "x", {"1": (100.0, 103.81), "2": (100.0, 96.19)}),
    ("LED", 0, "y", {"1": (103.81, 100.0), "2": (96.19, 100.0)}),
    ("LED", 90, "y", {"1": (100.0, 103.81), "2": (100.0, 96.19)}),
    ("LED", 180, "y", {"1": (96.19, 100.0), "2": (103.81, 100.0)}),
    ("LED", 270, "y", {"1": (100.0, 96.19), "2": (100.0, 103.81)}),
    ("R", 0, "x", {"1": (100.0, 103.81), "2": (100.0, 96.19)}),
    ("R", 90, "x", {"1": (96.19, 100.0), "2": (103.81, 100.0)}),
    ("R", 180, "x", {"1": (100.0, 96.19), "2": (100.0, 103.81)}),
    ("R", 270, "x", {"1": (103.81, 100.0), "2": (96.19, 100.0)}),
    ("R", 0, "y", {"1": (100.0, 96.19), "2": (100.0, 103.81)}),
    ("R", 90, "y", {"1": (103.81, 100.0), "2": (96.19, 100.0)}),
    ("R", 180, "y", {"1": (100.0, 103.81), "2": (100.0, 96.19)}),
    ("R", 270, "y", {"1": (96.19, 100.0), "2": (103.81, 100.0)}),
]


@pytest.mark.usefixtures("device_library")
@pytest.mark.parametrize(("symbol", "rotation", "mirror", "expected"), KICAD_MIRRORED_PIN_POSITIONS)
def test_pin_positions_match_kicad_for_mirrored_symbols(
    symbol: str, rotation: int, mirror: str, expected: dict[str, tuple[float, float]]
) -> None:
    assert (
        schematic.get_pin_positions("Device", symbol, 100.0, 100.0, rotation, mirror=mirror)
        == expected
    )


@pytest.mark.usefixtures("device_library")
@pytest.mark.parametrize(("symbol", "rotation", "mirror", "expected"), KICAD_MIRRORED_PIN_POSITIONS)
def test_pin_alias_positions_match_kicad_for_mirrored_symbols(
    symbol: str,
    rotation: int,
    mirror: str,
    expected: dict[str, tuple[float, float]],
) -> None:
    aliases = schematic.get_pin_alias_positions(
        "Device",
        symbol,
        100.0,
        100.0,
        rotation,
        mirror=mirror,
    )

    assert {pin: aliases[pin] for pin in expected} == expected
    if symbol == "LED":
        assert aliases["K"] == expected["1"]
        assert aliases["A"] == expected["2"]


@pytest.mark.usefixtures("device_library")
def test_connectivity_graph_reads_symbol_mirror(tmp_path: Path) -> None:
    sch_file = tmp_path / "mirrored.kicad_sch"
    sch_file.write_text(
        "(kicad_sch\n"
        "\t(version 20250316)\n"
        '\t(generator "pytest")\n'
        '\t(uuid "aa111111-2222-3333-4444-555555555555")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols)\n"
        '\t(label "K_NET" (at 100 103.81 0))\n'
        '\t(label "A_NET" (at 100 96.19 0))\n'
        "\t(symbol\n"
        '\t\t(lib_id "Device:LED")\n'
        "\t\t(at 100 100 270)\n"
        "\t\t(mirror x)\n"
        "\t\t(unit 1)\n"
        '\t\t(property "Reference" "D1" (at 100 100 0))\n'
        '\t\t(property "Value" "LED" (at 100 100 0))\n'
        "\t)\n"
        ")\n",
        encoding="utf-8",
    )

    groups = schematic._build_connectivity_groups(sch_file)

    pins_by_net = {
        tuple(group["names"]): [f"{pin['reference']}:{pin['pin']}" for pin in group["pins"]]
        for group in groups
    }
    assert pins_by_net == {("A_NET",): ["D1:2"], ("K_NET",): ["D1:1"]}
