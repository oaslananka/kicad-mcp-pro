from __future__ import annotations

import json
from pathlib import Path

from kicad_mcp.tools.schematic import (
    SCHEMATIC_BACKEND_CAPABILITY_MATRIX,
    SCHEMATIC_PUBLIC_TOOL_NAMES,
    _extract_uuid,
    _reload_schematic,
    get_schematic_backend,
    parse_schematic_file,
    transactional_write,
    update_symbol_property,
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
