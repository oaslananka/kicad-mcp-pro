"""Live KiCad pad-to-footprint mapping regressions for issue #501."""

from __future__ import annotations

from types import SimpleNamespace

from kicad_mcp.pcb.pad_mapping import (
    footprint_pads,
    map_pads_to_footprints,
)


def _pad(pad_id: str | None, number: str = "1") -> object:
    identifier = SimpleNamespace(value=pad_id) if pad_id is not None else SimpleNamespace()
    return SimpleNamespace(id=identifier, number=number)


def _footprint(reference: str, pads: list[object]) -> object:
    return SimpleNamespace(
        reference_field=SimpleNamespace(text=SimpleNamespace(value=reference)),
        definition=SimpleNamespace(pads=pads),
    )


def test_map_pads_uses_official_footprint_definition_pad_ids() -> None:
    board_pad = _pad("pad-1")
    footprint_pad = _pad("pad-1")

    mapped = map_pads_to_footprints([board_pad], [_footprint("U1", [footprint_pad])])

    assert len(mapped) == 1
    assert mapped[0].pad is board_pad
    assert mapped[0].pad_id == "pad-1"
    assert mapped[0].reference == "U1"


def test_map_pads_deduplicates_duplicate_board_pad_ids() -> None:
    first = _pad("pad-1")
    duplicate = _pad("pad-1")

    mapped = map_pads_to_footprints([first, duplicate], [_footprint("U1", [_pad("pad-1")])])

    assert [(item.pad, item.reference) for item in mapped] == [(first, "U1")]


def test_map_pads_marks_conflicting_or_missing_ids_unmapped() -> None:
    conflict = _pad("shared")
    missing = _pad(None, number="2")
    footprints = [
        _footprint("U1", [_pad("shared")]),
        _footprint("U2", [_pad("shared")]),
    ]

    mapped = map_pads_to_footprints([conflict, missing], footprints)

    assert [(item.pad_id, item.reference) for item in mapped] == [
        ("shared", None),
        (None, None),
    ]


def test_footprint_pads_reads_definition_pads_and_ignores_unsupported_surfaces() -> None:
    pads = [_pad("p1"), _pad("p2")]

    assert footprint_pads(_footprint("U1", pads)) == pads
    assert footprint_pads(SimpleNamespace()) == []
