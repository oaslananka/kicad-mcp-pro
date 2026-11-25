"""The file-backed listing index is content-bound, bounded and project-scoped."""

from pathlib import Path

import pytest

from kicad_mcp.pcb import footprint_index as board_file


def _footprint(stamp: str, reference: str, x: int) -> str:
    return (
        '(footprint "Device:R" (layer "F.Cu") '
        f'(uuid "{stamp}") (at {x} 20 90) '
        f'(property "Reference" "{reference}") (property "Value" "10k") '
        '(property "Note" "quoted (footprint fake)"))'
    )


A = "10000000-0000-0000-0000-100000000001"
B = "10000000-0000-0000-0000-100000000002"


def _board(*footprints: str) -> str:
    return "(kicad_pcb (version 20241229) " + " ".join(footprints) + ")"


def test_native_footprint_index_updates_only_changed_objects(tmp_path: Path) -> None:
    index = board_file.FileFootprintIndex()
    path = tmp_path / "board.kicad_pcb"
    initial = _board(_footprint(A, "R1", 10), _footprint(B, "R2", 15))
    first = index.refresh(path, initial)
    assert first is not None
    assert first.work_units == 2
    assert first.records[A].x_mm == 10
    assert index.refresh(path, initial).work_units == 0
    changed = _board(_footprint(A, "R1", 11), _footprint(B, "R2", 15))
    second = index.refresh(path, changed)
    assert second.work_units == 1
    assert second.records[A].x_mm == 11
    assert second.records[B] is first.records[B]
    clean = board_file.FileFootprintIndex().refresh(path, changed)
    assert second.records == clean.records
    switched = index.refresh(tmp_path / "other.kicad_pcb", changed)
    assert switched.work_units == 2


def test_removal_and_unknown_identity_do_not_reuse_previous_records(tmp_path: Path) -> None:
    index = board_file.FileFootprintIndex()
    path = tmp_path / "board.kicad_pcb"
    index.refresh(path, _board(_footprint(A, "R1", 10), _footprint(B, "R2", 15)))
    removed = index.refresh(path, _board(_footprint(B, "R2", 15)))
    assert set(removed.records) == {B}
    assert removed.work_units == 0
    assert index.refresh(path, "(kicad_pcb (version 20990101))") is None
    assert index.refresh(path, _board(_footprint(B, "R2", 15))).work_units == 1


@pytest.mark.parametrize(
    "bad",
    [
        _board(_footprint(A, "R1", 10), _footprint(A, "R2", 15)),
        _board(_footprint(A, "R1", 10))[:-1],
        _board(_footprint(A, "R1", 10)) + '(footprint "outside")',
    ],
)
def test_invalid_native_inventory_is_never_reused(tmp_path: Path, bad: str) -> None:
    index = board_file.FileFootprintIndex()
    path = tmp_path / "board.kicad_pcb"
    valid = _board(_footprint(A, "R1", 10))
    index.refresh(path, valid)
    with pytest.raises(ValueError):
        index.refresh(path, bad)
    assert index.refresh(path, valid).work_units == 1


def test_duplicate_references_remain_distinct_by_native_uuid(tmp_path: Path) -> None:
    index = board_file.FileFootprintIndex()
    result = index.refresh(
        tmp_path / "board.kicad_pcb",
        _board(_footprint(A, "REF**", 10), _footprint(B, "REF**", 15)),
    )
    assert result is not None
    assert set(result.records) == {A, B}
    assert [row.reference for row in result.records.values()] == ["REF**", "REF**"]


def test_version_change_and_missing_uuid_discard_reusable_records(tmp_path: Path) -> None:
    index = board_file.FileFootprintIndex()
    path = tmp_path / "board.kicad_pcb"
    initial = _board(_footprint(A, "R1", 10))
    first = index.refresh(path, initial)
    assert first is not None
    upgraded = index.refresh(path, initial.replace("20241229", "20260206"))
    assert upgraded is not None
    assert upgraded.work_units == 1
    legacy = initial.replace(f'(uuid "{A}")', "")
    assert index.refresh(path, legacy) is None
    restored = index.refresh(path, initial)
    assert restored is not None
    assert restored.work_units == 1


def test_file_backed_listing_uses_current_native_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.tools import pcb

    path = tmp_path / "board.kicad_pcb"
    original = _board(_footprint(A, "REF**", 10), _footprint(B, "REF**", 15))
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pcb, "_configured_board_file", lambda: path)
    index = board_file.FileFootprintIndex()

    def read() -> str:
        return pcb._file_backed_footprints(
            OSError("IPC unavailable"),
            page=1,
            page_size=10,
            filter_layer="",
            index=index,
        )

    first = read()
    assert "2 total" in first
    assert f"id=file:footprint:{A}" in first
    assert f"id=file:footprint:{B}" in first
    assert "(10.00, 20.00)" in first
    path.write_text(original.replace("(at 10 20 90)", "(at 11 20 90)"), encoding="utf-8")
    updated = read()
    assert "(11.00, 20.00)" in updated
    assert "(10.00, 20.00)" not in updated
    path.write_text(original[:-1], encoding="utf-8")
    assert "inventory unavailable" in read()
    path.unlink()
    assert "missing" in read()


def test_representative_board_decodes_only_changed_footprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Count actual decoder calls at representative synthetic scale, not wall-clock latency."""
    count = 1125
    footprints = [
        f'(footprint "Test:R" (uuid "10000000-0000-0000-0000-{i:012d}") '
        f'(layer "F.Cu") (at {i} 20) (property "Reference" "R{i}") '
        '(property "Value" "10k"))'
        for i in range(1, count + 1)
    ]
    # Represent board-level scanning separately from footprint decoding.
    tracks = '(segment (start 0 0) (end 1 1) (width 0.25) (layer "F.Cu") (net 1))' * 25386
    text = "(kicad_pcb (version 20241229) " + "".join(footprints) + tracks + ")"
    path = tmp_path / "board.kicad_pcb"
    index = board_file.FileFootprintIndex()
    decode = board_file._native_list_record
    calls = 0

    def counted(block: str, block_sha256: str) -> board_file.FootprintListRecord | None:
        nonlocal calls
        calls += 1
        return decode(block, block_sha256)

    monkeypatch.setattr(board_file, "_native_list_record", counted)
    first = index.refresh(path, text)
    assert first is not None
    assert len(first.records) == calls == first.work_units == count
    warm = index.refresh(path, text)
    assert warm is not None
    assert warm.work_units == 0
    assert calls == count
    changed = text.replace("(at 17 20)", "(at 17.1 20)", 1)
    updated = index.refresh(path, changed)
    assert updated is not None
    assert updated.work_units == 1
    assert calls == count + 1
    stamp = "10000000-0000-0000-0000-000000000017"
    assert updated.records[stamp].x_mm == 17.1
    assert all(updated.records[key] is row for key, row in first.records.items() if key != stamp)
    nonfootprint = changed.replace("(end 1 1)", "(end 2 1)", 1)
    track_edit = index.refresh(path, nonfootprint)
    assert track_edit is not None
    assert track_edit.work_units == 0
    assert calls == count + 1
    assert track_edit.records == updated.records
    clean = board_file.FileFootprintIndex().refresh(path, nonfootprint)
    assert clean is not None
    assert clean.records == updated.records
    assert clean.work_units == count
    assert calls == 2 * count + 1


def test_physical_snapshot_distinguishes_placement_from_unknown_changes(tmp_path: Path) -> None:
    index = board_file.FileFootprintIndex()
    path = tmp_path / "board.kicad_pcb"
    original = _board(_footprint(A, "REF**", 10), _footprint(B, "REF**", 15))
    first = index.refresh(path, original)
    moved = index.refresh(path, original.replace("(at 10 20 90)", "(at 11 20 90)"))
    assert first is not None
    assert moved is not None
    assert first.board_context_sha256 == moved.board_context_sha256
    assert first.records[A].nonplacement_sha256 == moved.records[A].nonplacement_sha256
    assert first.records[A].block_sha256 != moved.records[A].block_sha256
    assert moved.records[B] is first.records[B]
    assert moved.work_units == 1
    changed = index.refresh(path, original.replace("(at 10 20 90)", "(at 10 20 45)"))
    assert changed is not None
    assert changed.records[A].nonplacement_sha256 != first.records[A].nonplacement_sha256
    track = index.refresh(path, original[:-1] + "(segment (start 0 0) (end 1 1)))")
    assert track is not None
    assert track.board_context_sha256 != first.board_context_sha256
    assert track.records == first.records


def test_native_footprint_properties_decode_escaped_values(tmp_path: Path) -> None:
    text = _board(_footprint(A, "R1", 10)).replace(
        '(property "Value" "10k")', r'(property "Value" "A\"B\\C\nD")'
    )
    result = board_file.FileFootprintIndex().refresh(tmp_path / "board.kicad_pcb", text)
    assert result is not None
    assert result.records[A].value == 'A"B\\C\nD'


def test_nul_content_is_not_indexed(tmp_path: Path) -> None:
    index = board_file.FileFootprintIndex()
    path = tmp_path / "board.kicad_pcb"
    valid = _board(_footprint(A, "R1", 10))
    assert index.refresh(path, valid).work_units == 1
    assert index.refresh(path, valid.replace("R1", "R1\0")) is None
    assert index.refresh(path, valid).work_units == 1
