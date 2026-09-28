from pathlib import Path

import pytest

from kicad_mcp.tools import library as library_mod


def test_component_rows_expand_reused_hierarchical_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sch_file = tmp_path / "channel.kicad_sch"
    sch_file.write_text(
        '(kicad_sch (symbol (lib_id "Device:R") '
        '(property "Reference" "R201") '
        '(property "Value" "10k") '
        '(property "Footprint" "Resistor_SMD:R_0805") '
        '(property "LCSC" "C123") '
        '(instances (path "/a" (reference "R201") (unit 1)) '
        '(path "/b" (reference "R301") (unit 1)))))',
        encoding="utf-8",
    )

    class FakeBackend:
        def parse_schematic_file(self, _path: Path) -> dict[str, object]:
            return {
                "symbols": [
                    {
                        "reference": "R201",
                        "value": "10k",
                        "footprint": "Resistor_SMD:R_0805",
                        "lib_id": "Device:R",
                    }
                ]
            }

    monkeypatch.setattr(library_mod, "_active_schematic_file", lambda: sch_file)
    monkeypatch.setattr(library_mod, "project_schematic_files", lambda: [sch_file])
    monkeypatch.setattr(library_mod, "get_schematic_backend", lambda: FakeBackend())

    rows = library_mod._schematic_component_rows()
    by_reference = {row["reference"]: row for row in rows}

    assert set(by_reference) == {"R201", "R301"}
    assert by_reference["R201"]["lcsc"] == "C123"
    assert by_reference["R301"]["lcsc"] == "C123"
    assert by_reference["R301"]["value"] == "10k"


def test_symbol_instance_references_falls_back_without_instances() -> None:
    block = '(symbol (lib_id "Device:R") (property "Reference" "R7"))'

    assert library_mod._symbol_instance_references(block, "R7") == ["R7"]


def test_component_rows_propagate_metadata_to_every_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sch_file = tmp_path / "channel.kicad_sch"
    sch_file.write_text(
        '(kicad_sch (symbol (lib_id "Device:R") '
        '(property "Reference" "R201") '
        '(property "Value" "10k") '
        '(property "Footprint" "Resistor_SMD:R_0805") '
        '(property "MPN" "RC0805FR-0710KL") '
        '(property "Manufacturer" "Yageo") '
        '(property "Populate" "Hand") '
        '(instances (path "/a" (reference "R201") (unit 1)) '
        '(path "/b" (reference "R301") (unit 1)))))',
        encoding="utf-8",
    )

    class FakeBackend:
        def parse_schematic_file(self, _path: Path) -> dict[str, object]:
            return {
                "symbols": [
                    {
                        "reference": "R201",
                        "value": "10k",
                        "footprint": "Resistor_SMD:R_0805",
                        "lib_id": "Device:R",
                    }
                ]
            }

    monkeypatch.setattr(library_mod, "_active_schematic_file", lambda: sch_file)
    monkeypatch.setattr(library_mod, "project_schematic_files", lambda: [sch_file])
    monkeypatch.setattr(library_mod, "get_schematic_backend", lambda: FakeBackend())

    rows = library_mod._schematic_component_rows()

    assert {row["reference"] for row in rows} == {"R201", "R301"}
    assert {row["mpn"] for row in rows} == {"RC0805FR-0710KL"}
    assert {row["manufacturer"] for row in rows} == {"Yageo"}
    assert {row["populate"] for row in rows} == {"Hand"}


def test_component_rows_propagate_dnp_to_every_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sch_file = tmp_path / "channel.kicad_sch"
    sch_file.write_text(
        '(kicad_sch (symbol (lib_id "Device:R") '
        '(property "Reference" "R201") '
        '(property "Value" "10k") '
        '(property "Footprint" "Resistor_SMD:R_0805") '
        "(dnp yes) "
        '(instances (path "/a" (reference "R201") (unit 1)) '
        '(path "/b" (reference "R301") (unit 1)))))',
        encoding="utf-8",
    )

    class FakeBackend:
        def parse_schematic_file(self, _path: Path) -> dict[str, object]:
            return {
                "symbols": [
                    {
                        "reference": "R201",
                        "value": "10k",
                        "footprint": "Resistor_SMD:R_0805",
                        "lib_id": "Device:R",
                    }
                ]
            }

    monkeypatch.setattr(library_mod, "_active_schematic_file", lambda: sch_file)
    monkeypatch.setattr(library_mod, "project_schematic_files", lambda: [sch_file])
    monkeypatch.setattr(library_mod, "get_schematic_backend", lambda: FakeBackend())

    rows = library_mod._schematic_component_rows()

    assert {row["reference"] for row in rows} == {"R201", "R301"}
    assert {row["populate"] for row in rows} == {"DNP"}


def test_component_rows_ignore_raw_symbol_missing_from_backend_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sch_file = tmp_path / "channel.kicad_sch"
    sch_file.write_text(
        '(kicad_sch (symbol (lib_id "Device:R") '
        '(property "Reference" "R999") '
        '(property "Value" "10k")))',
        encoding="utf-8",
    )

    class FakeBackend:
        def parse_schematic_file(self, _path: Path) -> dict[str, object]:
            return {
                "symbols": [
                    {
                        "reference": "R201",
                        "value": "10k",
                        "footprint": "",
                        "lib_id": "Device:R",
                    }
                ]
            }

    monkeypatch.setattr(library_mod, "_active_schematic_file", lambda: sch_file)
    monkeypatch.setattr(library_mod, "project_schematic_files", lambda: [sch_file])
    monkeypatch.setattr(library_mod, "get_schematic_backend", lambda: FakeBackend())

    rows = library_mod._schematic_component_rows()

    assert [row["reference"] for row in rows] == ["R201"]


def test_component_rows_skip_internal_instance_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sch_file = tmp_path / "channel.kicad_sch"
    sch_file.write_text(
        '(kicad_sch (symbol (lib_id "Device:R") '
        '(property "Reference" "R201") '
        '(property "Value" "10k") '
        '(instances (path "/power" (reference "#PWR01") (unit 1)) '
        '(path "/channel" (reference "R301") (unit 1)))))',
        encoding="utf-8",
    )

    class FakeBackend:
        def parse_schematic_file(self, _path: Path) -> dict[str, object]:
            return {
                "symbols": [
                    {
                        "reference": "R201",
                        "value": "10k",
                        "footprint": "",
                        "lib_id": "Device:R",
                    }
                ]
            }

    monkeypatch.setattr(library_mod, "_active_schematic_file", lambda: sch_file)
    monkeypatch.setattr(library_mod, "project_schematic_files", lambda: [sch_file])
    monkeypatch.setattr(library_mod, "get_schematic_backend", lambda: FakeBackend())

    rows = library_mod._schematic_component_rows()

    assert {row["reference"] for row in rows} == {"R201", "R301"}
    assert all(not row["reference"].startswith("#") for row in rows)


def test_component_rows_propagate_exclude_from_bom_to_every_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sch_file = tmp_path / "channel.kicad_sch"
    sch_file.write_text(
        '(kicad_sch (symbol (lib_id "Device:R") '
        '(property "Reference" "R201") '
        '(property "Value" "10k") '
        '(property "Exclude from BOM" "yes") '
        '(instances (path "/a" (reference "R201") (unit 1)) '
        '(path "/b" (reference "R301") (unit 1)))))',
        encoding="utf-8",
    )

    class FakeBackend:
        def parse_schematic_file(self, _path: Path) -> dict[str, object]:
            return {
                "symbols": [
                    {
                        "reference": "R201",
                        "value": "10k",
                        "footprint": "",
                        "lib_id": "Device:R",
                    }
                ]
            }

    monkeypatch.setattr(library_mod, "_active_schematic_file", lambda: sch_file)
    monkeypatch.setattr(library_mod, "project_schematic_files", lambda: [sch_file])
    monkeypatch.setattr(library_mod, "get_schematic_backend", lambda: FakeBackend())

    rows = library_mod._schematic_component_rows()

    assert {row["reference"] for row in rows} == {"R201", "R301"}
    assert {row["populate"] for row in rows} == {"DNP"}
