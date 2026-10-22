"""Issue #1370: kicad-sch-api must not write away labels or unknown metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.errors import SchematicWriteUnsafeError
from kicad_mcp.schematic.guarded_api_save import guarded_kicad_api_save

HEADER = """(kicad_sch
 (version 20260306) (generator "eeschema")
 (title_block (title "probe") (comment 1 "assembly note"))
 (global_label "VBAT" (at 1 2 0) (effects (font (size 1 1))))
 (text "Battery input" (at 2 2 0) (effects (font (size 1 1)) (justify left bottom)))
 """
TAIL = '(sheet_instances (path "/" (page "1")))\n)\n'
SYMBOL = """(symbol (lib_id "Device:R") (at 12 14 90)
 (property "Reference" "R1" (at 12 14 0))
 (property "Value" "10k" (at 12 15 0))
 (uuid "11111111-1111-4111-8111-111111111111"))
"""
SHEET = """(sheet (at 20 20) (size 30 20)
 (property "Sheetname" "Child" (at 20 20 0))
 (property "Sheetfile" "child.kicad_sch" (at 20 21 0))
 (uuid "22222222-2222-4222-8222-222222222222"))
"""


class StubSerializer:
    def __init__(self, content: str) -> None:
        self.content = content

    def save(self, path: Path, *, preserve_format: bool = True) -> None:
        assert preserve_format
        path.write_text(self.content, encoding="utf-8")


def _source() -> str:
    return HEADER + SYMBOL + TAIL


def test_selective_movement_preserves_lost_label_title_and_justification(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    broken = source.replace('(global_label "VBAT" (at 1 2 0) (effects (font (size 1 1))))', "")
    broken = broken.replace('(comment 1 "assembly note")', "")
    broken = broken.replace(" (justify left bottom)", "")
    broken = broken.replace("(at 12 14 90)", "(at 30 31 90)")
    assert guarded_kicad_api_save(StubSerializer(broken), file, moved_references=["R1"])
    saved = file.read_text()
    assert '(global_label "VBAT"' in saved
    assert '(comment 1 "assembly note")' in saved
    assert "(justify left bottom)" in saved
    assert "(at 30.000000 31.000000 90)" in saved


def test_ignores_numeric_int_to_float_reformatting_without_touching_source(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    proposed = source.replace("(at 12 14 90)", "(at 12.0 14.0 90.0)")
    assert not guarded_kicad_api_save(StubSerializer(proposed), file, moved_references=["R1"])
    assert file.read_text() == source


def test_moved_symbol_location_is_the_only_allowed_existing_change(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    moved = source.replace("(at 12 14 90)", "(at 30 31 90)")
    assert guarded_kicad_api_save(StubSerializer(moved), file, moved_references=["R1"])
    assert "(at 30.000000 31.000000 90)" in file.read_text()
    assert '(global_label "VBAT"' in file.read_text()


def test_refuses_unrequested_angle_change(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    changed = source.replace("(at 12 14 90)", "(at 30 31 180)")
    serializer = StubSerializer(changed)
    with pytest.raises(SchematicWriteUnsafeError):
        guarded_kicad_api_save(serializer, file, moved_references=["R1"])
    assert file.read_text() == source


def test_accepts_only_one_named_sheet(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    proposed = source.replace("(sheet_instances", SHEET + "(sheet_instances")
    assert guarded_kicad_api_save(StubSerializer(proposed), file, added_sheet_name="Child")
    assert 'Sheetname" "Child"' in file.read_text()


def test_rejects_other_sheet_even_when_one_expected(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    serializer = StubSerializer(source.replace("(sheet_instances", SHEET + "(sheet_instances"))
    with pytest.raises(SchematicWriteUnsafeError):
        guarded_kicad_api_save(
            serializer,
            file,
            added_sheet_name="Wrong",
        )
    assert file.read_text() == source


def test_true_noop_does_not_replace_file(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    before = file.stat().st_ino
    assert not guarded_kicad_api_save(StubSerializer(source), file)
    assert file.stat().st_ino == before


def test_concurrent_change_is_not_overwritten(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)

    class ConcurrentWriter(StubSerializer):
        def save(self, path: Path, *, preserve_format: bool = True) -> None:
            super().save(path, preserve_format=preserve_format)
            file.write_text(source.replace('"VBAT"', '"ChangedExternally"'))

    serializer = ConcurrentWriter(source)
    with pytest.raises(SchematicWriteUnsafeError, match="changed during serialization"):
        guarded_kicad_api_save(serializer, file)
    assert "ChangedExternally" in file.read_text()


def test_selective_move_rejects_nonexistent_reference(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    serializer = StubSerializer(source)
    with pytest.raises(SchematicWriteUnsafeError, match="reference is missing"):
        guarded_kicad_api_save(serializer, file, moved_references=["R404"])
    assert file.read_text() == source


def test_selective_move_rejects_changed_uuid(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    output = source.replace(
        "11111111-1111-4111-8111-111111111111",
        "33333333-3333-4333-8333-333333333333",
    )
    serializer = StubSerializer(output)
    with pytest.raises(SchematicWriteUnsafeError, match="identity changed"):
        guarded_kicad_api_save(serializer, file, moved_references=["R1"])
    assert file.read_text() == source


def test_selective_move_refuses_duplicate_reference_nodes(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source().replace(
        '(sheet_instances (path "/" (page "1")))',
        SYMBOL + '(sheet_instances (path "/" (page "1")))',
    )
    file.write_text(source)
    serializer = StubSerializer(source.replace("(at 12 14 90)", "(at 31 32 90)"))
    with pytest.raises(SchematicWriteUnsafeError, match="Duplicate symbol reference"):
        guarded_kicad_api_save(
            serializer,
            file,
            moved_references=["R1"],
        )
    assert file.read_text() == source


def test_selective_move_preserves_quoted_fake_symbol(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    fake = '(symbol (lib_id "Bad") (property "Reference" "R404") (at 1 1 0))'
    source = _source().replace(
        "(sheet_instances",
        f'(text "{fake.replace(chr(34), chr(92) + chr(34))}")\n(sheet_instances',
    )
    file.write_text(source)
    changed = source.replace("(at 12 14 90)", "(at 20 21 90)")
    assert guarded_kicad_api_save(StubSerializer(changed), file, moved_references=["R1"])
    assert fake.replace('"', '\\"') in file.read_text()


def test_staged_move_does_not_rewrite_unrelated_symbol_position(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    other = (
        SYMBOL.replace('"R1"', '"R2"')
        .replace(
            "11111111-1111-4111-8111-111111111111",
            "44444444-4444-4444-8444-444444444444",
        )
        .replace("(at 12 14 90)", "(at 40 40 90)")
    )
    source = _source().replace("(sheet_instances", other + "(sheet_instances")
    file.write_text(source)
    staged = source.replace("(at 12 14 90)", "(at 20 20 90)").replace(
        "(at 40 40 90)", "(at 99 99 90)"
    )
    assert guarded_kicad_api_save(StubSerializer(staged), file, moved_references=["R1"])
    saved = file.read_text()
    assert "(at 20.000000 20.000000 90)" in saved
    assert "(at 40 40 90)" in saved
    assert "(at 99 99 90)" not in saved


def _unit_source() -> tuple[str, str, str]:
    one = SYMBOL.replace('(lib_id "Device:R")', '(lib_id "Device:R") (unit 1)')
    two = (
        SYMBOL.replace('(lib_id "Device:R")', '(lib_id "Device:R") (unit 2)')
        .replace("(at 12 14 90)", "(at 51 53 90)")
        .replace("11111111-1111-4111-8111-111111111111", "99999999-9999-4999-8999-999999999999")
    )
    return HEADER + one + two + TAIL, one, two


def test_multiunit_symbol_only_transfers_changed_unit_coordinates(tmp_path: Path) -> None:
    """Both physical units share R1, but have distinct positions and UUIDs."""
    source, one, two = _unit_source()
    file = tmp_path / "multiunit.kicad_sch"
    file.write_text(source)
    staged = source.replace(
        one,
        one.replace("(at 12 14 90)", "(at 30 32 90)"),
    ).replace('(comment 1 "assembly note")', "")
    assert guarded_kicad_api_save(StubSerializer(staged), file, moved_references=["R1"])
    saved = file.read_text()
    assert "(unit 1)" in saved
    assert "(unit 2)" in saved
    assert "(at 30.000000 32.000000 90)" in saved
    assert two in saved
    assert '(comment 1 "assembly note")' in saved
    assert '(global_label "VBAT"' in saved


def test_multiunit_symbol_can_move_both_units_independently(tmp_path: Path) -> None:
    source, _one, _two = _unit_source()
    file = tmp_path / "multiunit.kicad_sch"
    file.write_text(source)
    staged = source.replace("(at 12 14 90)", "(at 30 32 90)").replace(
        "(at 51 53 90)", "(at 60 63 90)"
    )
    assert guarded_kicad_api_save(StubSerializer(staged), file, moved_references=["R1"])
    saved = file.read_text()
    assert "(at 30.000000 32.000000 90)" in saved
    assert "(at 60.000000 63.000000 90)" in saved


def test_multiunit_symbol_rejects_missing_serialized_unit(tmp_path: Path) -> None:
    source, _one, two = _unit_source()
    file = tmp_path / "multiunit.kicad_sch"
    file.write_text(source)
    serializer = StubSerializer(source.replace(two, ""))
    with pytest.raises(SchematicWriteUnsafeError, match="unit is missing"):
        guarded_kicad_api_save(serializer, file, moved_references=["R1"])
    assert file.read_text() == source


@pytest.mark.parametrize("unit", ["0", "-1", '"two"', "1.5"])
def test_multiunit_symbol_rejects_invalid_unit(tmp_path: Path, unit: str) -> None:
    source, one, _two = _unit_source()
    file = tmp_path / "multiunit.kicad_sch"
    mutated = source.replace(one, one.replace("(unit 1)", f"(unit {unit})"))
    file.write_text(mutated)
    serializer = StubSerializer(mutated)
    with pytest.raises(SchematicWriteUnsafeError, match="Invalid symbol unit"):
        guarded_kicad_api_save(serializer, file, moved_references=["R1"])
    assert file.read_text() == mutated


def test_multiunit_symbol_rejects_duplicate_unit(tmp_path: Path) -> None:
    source, _one, two = _unit_source()
    source = source.replace(two, two.replace("(unit 2)", "(unit 1)"))
    file = tmp_path / "multiunit.kicad_sch"
    file.write_text(source)
    serializer = StubSerializer(source)
    with pytest.raises(SchematicWriteUnsafeError, match="Duplicate symbol reference and unit"):
        guarded_kicad_api_save(serializer, file, moved_references=["R1"])
    assert file.read_text() == source


def test_unsafe_schematic_root_is_rejected_before_replacement(tmp_path: Path) -> None:
    file = tmp_path / "invalid.kicad_sch"
    original = "(kicad_sch (version 20260306))"
    file.write_text(original)
    serializer = StubSerializer("(different (version 20260306))")
    with pytest.raises(SchematicWriteUnsafeError, match="Missing KiCad schematic root"):
        guarded_kicad_api_save(serializer, file)
    assert file.read_text() == original


def test_unsafe_unbalanced_staged_content_is_rejected(tmp_path: Path) -> None:
    file = tmp_path / "invalid.kicad_sch"
    original = _source()
    file.write_text(original)
    serializer = StubSerializer("(kicad_sch (symbol")
    with pytest.raises(SchematicWriteUnsafeError, match="parse staged"):
        guarded_kicad_api_save(serializer, file)
    assert file.read_text() == original


def test_added_sheet_without_sheetname_is_rejected(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    unnamed = source.replace("(sheet_instances", "(sheet (at 2 3) (size 5 5))\n(sheet_instances")
    serializer = StubSerializer(unnamed)
    with pytest.raises(SchematicWriteUnsafeError, match="number or name"):
        guarded_kicad_api_save(serializer, file, added_sheet_name="Child")
    assert file.read_text() == source


def test_added_duplicate_named_sheets_are_rejected(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    duplicate = source.replace("(sheet_instances", SHEET + SHEET + "(sheet_instances")
    serializer = StubSerializer(duplicate)
    with pytest.raises(SchematicWriteUnsafeError, match="number or name"):
        guarded_kicad_api_save(serializer, file, added_sheet_name="Child")
    assert file.read_text() == source


def test_missing_requested_symbol_position_is_rejected(tmp_path: Path) -> None:
    file = tmp_path / "probe.kicad_sch"
    source = _source()
    file.write_text(source)
    without_position = source.replace("(at 12 14 90)", "")
    serializer = StubSerializer(without_position)
    with pytest.raises(SchematicWriteUnsafeError, match="exactly one direct symbol position"):
        guarded_kicad_api_save(serializer, file, moved_references=["R1"])
    assert file.read_text() == source


def test_selective_move_preserves_original_crlf_bytes(tmp_path: Path) -> None:
    file = tmp_path / "windows.kicad_sch"
    source = _source().replace("\n", "\r\n")
    original = source.encode("utf-8")
    file.write_bytes(original)
    staged = source.replace("(at 12 14 90)", "(at 30 31 90)")
    assert guarded_kicad_api_save(StubSerializer(staged), file, moved_references=["R1"])
    saved = file.read_bytes()
    expected = original.replace(b"(at 12 14 90)", b"(at 30.000000 31.000000 90)")
    assert saved == expected
    assert b"\r\r\n" not in saved
