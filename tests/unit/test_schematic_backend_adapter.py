from __future__ import annotations

import json
from pathlib import Path

from kicad_mcp.tools.schematic import (
    SCHEMATIC_BACKEND_CAPABILITY_MATRIX,
    SCHEMATIC_PUBLIC_TOOL_NAMES,
    _extract_uuid,
    _extract_wires,
    _normalize_schematic_wire_connectivity,
    _reload_schematic,
    get_schematic_backend,
    parse_schematic_file,
    transactional_write,
    update_symbol_property,
    wire_block,
)

_REALISTIC_SCH_HEADER = (
    "(kicad_sch\n"
    "\t(version 20250316)\n"
    '\t(generator "eeschema")\n'
    '\t(generator_version "10.0")\n'
    '\t(uuid "aa111111-2222-3333-4444-555555555555")\n'
    '\t(paper "A4")\n'
    "\t(lib_symbols\n"
    '\t\t(symbol "Device:R"\n'
    '\t\t\t(uuid "ffffffff-0000-0000-0000-000000000000")\n'
    "\t\t)\n"
    "\t)\n"
    "\t(sheet_instances\n"
    '\t\t(path "/" (page "1"))\n'
    "\t)\n"
    ")\n"
)


def test_extract_uuid_reads_root_uuid_past_version_and_generator() -> None:
    """The root UUID sits after (version)/(generator), so the extractor must skip
    them; a regex that stops at the first '(' returns '' on every real file and
    breaks incremental symbol placement (mismatched instance paths -> blank sheet).
    """
    assert _extract_uuid(_REALISTIC_SCH_HEADER) == "aa111111-2222-3333-4444-555555555555"


def test_parse_schematic_file_surfaces_root_uuid(tmp_path: Path) -> None:
    sch_file = tmp_path / "demo.kicad_sch"
    sch_file.write_text(_REALISTIC_SCH_HEADER, encoding="utf-8")

    assert parse_schematic_file(sch_file)["uuid"] == "aa111111-2222-3333-4444-555555555555"


def _placed_symbol(lib_id: str, reference: str, value: str, x: float) -> str:
    return (
        "\t(symbol\n"
        f'\t\t(lib_id "{lib_id}")\n'
        f"\t\t(at {x} 50.8 0)\n"
        "\t\t(unit 1)\n"
        f'\t\t(property "Reference" "{reference}" (at {x} 50.8 0))\n'
        f'\t\t(property "Value" "{value}" (at {x} 50.8 0))\n'
        "\t)\n"
    )


def test_parse_schematic_file_detects_power_symbols_by_lib_symbol_flag(tmp_path: Path) -> None:
    """KiCad marks power symbols with ``(power)`` in lib_symbols, not by the
    ``power:`` library name, so project-library rails must still name nets."""
    sch_file = tmp_path / "demo.kicad_sch"
    sch_file.write_text(
        "(kicad_sch\n"
        "\t(version 20250316)\n"
        '\t(generator "eeschema")\n'
        '\t(uuid "aa111111-2222-3333-4444-555555555555")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols\n"
        '\t\t(symbol "ecc83-pp:GND"\n'
        "\t\t\t(power)\n"
        '\t\t\t(symbol "GND_1_1" (pin power_in line (at 0 0 270) (length 0)'
        ' (name "GND") (number "1")))\n'
        "\t\t)\n"
        '\t\t(symbol "ecc83-pp:+5V"\n'
        "\t\t\t(power global)\n"
        "\t\t)\n"
        '\t\t(symbol "ecc83-pp:R"\n'
        '\t\t\t(symbol "R_1_1" (pin passive line (at 0 3.81 270) (length 1.27)'
        ' (name "~") (number "1")))\n'
        "\t\t)\n"
        "\t)\n"
        + _placed_symbol("ecc83-pp:GND", "#PWR01", "GND", 10.16)
        + _placed_symbol("ecc83-pp:+5V", "#PWR02", "+5V", 20.32)
        + _placed_symbol("ecc83-pp:R", "R1", "10k", 30.48)
        # No lib_symbols entry: fall back to the power: library prefix.
        + _placed_symbol("power:VCC", "#PWR03", "VCC", 40.64)
        + ")\n",
        encoding="utf-8",
    )

    parsed = parse_schematic_file(sch_file)

    assert sorted(symbol["reference"] for symbol in parsed["power_symbols"]) == [
        "#PWR01",
        "#PWR02",
        "#PWR03",
    ]
    assert [symbol["reference"] for symbol in parsed["symbols"]] == ["R1"]


def test_schematic_capability_matrix_matches_reference_fixture() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "schematic_backend_capability_matrix.json"
    )
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert SCHEMATIC_BACKEND_CAPABILITY_MATRIX == expected


def test_schematic_capability_matrix_covers_every_public_tool() -> None:
    assert set(SCHEMATIC_BACKEND_CAPABILITY_MATRIX) == set(SCHEMATIC_PUBLIC_TOOL_NAMES)


def test_default_schematic_backend_is_kicad_sch_api() -> None:
    backend = get_schematic_backend()

    assert backend.name == "kicad_sch_api"
    assert backend.capability_matrix == SCHEMATIC_BACKEND_CAPABILITY_MATRIX


def test_parse_schematic_file_delegates_to_active_backend(monkeypatch, tmp_path: Path) -> None:
    schematic_file = tmp_path / "demo.kicad_sch"
    schematic_file.write_text("(kicad_sch)\n", encoding="utf-8")
    calls: list[Path] = []

    class FakeBackend:
        name = "fake"
        capability_matrix = {}

        def parse_schematic_file(self, sch_file: Path) -> dict[str, object]:
            calls.append(sch_file)
            return {"backend": "fake"}

        def transactional_write(self, mutator):
            raise AssertionError("not used")

        def update_symbol_property(self, reference: str, field: str, value: str) -> str:
            raise AssertionError("not used")

        def reload_schematic(self) -> str:
            raise AssertionError("not used")

    monkeypatch.setattr("kicad_mcp.tools.schematic.get_schematic_backend", lambda: FakeBackend())

    assert parse_schematic_file(schematic_file) == {"backend": "fake"}
    assert calls == [schematic_file]


def test_transactional_helpers_delegate_to_active_backend(monkeypatch) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeBackend:
        name = "fake"
        capability_matrix = {}

        def parse_schematic_file(self, sch_file: Path) -> dict[str, object]:
            raise AssertionError("not used")

        def transactional_write(self, mutator):
            calls.append(("transactional_write", (mutator,)))
            return "written"

        def update_symbol_property(self, reference: str, field: str, value: str) -> str:
            calls.append(("update_symbol_property", (reference, field, value)))
            return "updated"

        def reload_schematic(self) -> str:
            calls.append(("reload_schematic", ()))
            return "reloaded"

    monkeypatch.setattr("kicad_mcp.tools.schematic.get_schematic_backend", lambda: FakeBackend())

    assert transactional_write(lambda text: text) == "written"
    assert update_symbol_property("R1", "Value", "10k") == "updated"
    assert _reload_schematic() == "reloaded"
    assert [name for name, _ in calls] == [
        "transactional_write",
        "update_symbol_property",
        "reload_schematic",
    ]


def test_wire_normalizer_preserves_touching_collinear_segments() -> None:
    segments = [
        (50.8, 50.8, 76.2, 50.8),
        (76.2, 50.8, 86.36, 50.8),
        (86.36, 50.8, 160.02, 50.8),
    ]
    source = (
        "(kicad_sch\\n"
        + "\\n".join(wire_block(*segment) for segment in segments)
        + "\\n\\t(sheet_instances)\\n)"
    )

    normalized = _normalize_schematic_wire_connectivity(source)
    wires = _extract_wires(normalized)

    assert len(wires) == len(segments)
    assert [(wire["x1"], wire["y1"], wire["x2"], wire["y2"]) for wire in wires] == segments
