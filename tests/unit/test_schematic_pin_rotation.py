import os
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


def test_pin_inspection_reuses_parse_and_observes_edits_with_same_stat(
    tmp_path: Path, monkeypatch
) -> None:
    library = tmp_path / "Device.kicad_sym"
    library.write_text(DEVICE_LIBRARY, encoding="utf8")
    monkeypatch.setattr(schematic, "_symbol_library_file", lambda _: library)
    schematic._read_cached_library_symbols.cache_clear()
    original_stat = Path.stat
    initial_stat = library.stat()
    original_parse = schematic._library_symbol_blocks
    parses = 0

    def unchanged_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path == library:
            return initial_stat
        return original_stat(path, follow_symlinks=follow_symlinks)

    def tracked_parse(content: str) -> dict[str, str]:
        nonlocal parses
        parses += 1
        return original_parse(content)

    monkeypatch.setattr(Path, "stat", unchanged_stat)
    monkeypatch.setattr(schematic, "_library_symbol_blocks", tracked_parse)
    assert schematic.get_pin_positions("Device", "R", 0, 0)["1"] == (0, -3.81)
    assert schematic.get_pin_metadata("Device", "R")["1"]["etype"] == "passive"
    assert schematic.get_pin_alias_positions("Device", "LED", 0, 0)["K"] == (-3.81, 0)
    assert parses == 1
    library.write_text(DEVICE_LIBRARY.replace("0 3.81 270", "0 12.7 270"), encoding="utf8")
    assert schematic.get_pin_positions("Device", "R", 0, 0)["1"] == (0, -12.7)
    assert parses == 2

    other = tmp_path / "other.kicad_sym"
    other.write_text(DEVICE_LIBRARY.replace("0 3.81 270", "0 5.08 270"), encoding="utf8")
    monkeypatch.setattr(schematic, "_symbol_library_file", lambda _: other)
    assert schematic.get_pin_positions("Device", "R", 0, 0)["1"] == (0, -5.08)
    assert parses == 3


def test_nested_unit_is_not_a_library_symbol(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "Device.kicad_sym"
    library.write_text(DEVICE_LIBRARY, encoding="utf8")
    monkeypatch.setattr(schematic, "_symbol_library_file", lambda _: library)
    assert schematic.symbol_exists("Device", "R_1_1") is False
    assert schematic.get_pin_positions("Device", "R_1_1", 0, 0) == {}
    library.write_text(
        DEVICE_LIBRARY.replace('(symbol "LED"', '(symbol "Genuine_1_1") (symbol "LED"', 1),
        encoding="utf8",
    )
    assert schematic.symbol_exists("Device", "Genuine_1_1") is True
    assert schematic.suggest_symbol_names("Device", "Genuine_1_1") == ["Genuine_1_1"]


def test_large_symbol_library_is_not_retained_in_parse_cache(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "Device.kicad_sym"
    library.write_text(DEVICE_LIBRARY, encoding="utf8")
    monkeypatch.setattr(schematic, "_MAX_CACHED_LIBRARY_BYTES", 1)
    schematic._read_cached_library_symbols.cache_clear()
    assert "R" in schematic._library_symbols_from_file(library)
    assert schematic._read_cached_library_symbols.cache_info().currsize == 0
