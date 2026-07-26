from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from kicad_mcp.schematic.lifecycle_authoring import SchematicLifecycleAuthoringService


def _service(
    tmp_path: Path,
    *,
    parsed: dict[str, Any] | None = None,
    snap_result: tuple[float, float] = (10.0, 20.0),
    snap_note: str = "",
) -> tuple[
    SchematicLifecycleAuthoringService,
    list[tuple[str, Any]],
    list[str],
]:
    schematic = tmp_path / "demo.kicad_sch"
    schematic.write_text(
        "(kicad_sch\n"
        '\t(property "Reference" "R?")\n'
        '\t(property "Reference" "U?")\n'
        '\t(property "Reference" "R12")\n'
        "\t(sheet_instances)\n"
        ")",
        encoding="utf-8",
    )
    parsed_value = parsed or {"symbols": []}
    calls: list[tuple[str, Any]] = []
    writes: list[str] = []

    def place_symbol_block(**kwargs: object) -> str:
        calls.append(("place_symbol_block", kwargs))
        return f"SYMBOL({kwargs['reference']},{kwargs['value']},{kwargs['x']},{kwargs['y']})"

    def append_before_sheet_instances(content: str, block: str) -> str:
        return content.replace("\t(sheet_instances)", f"\t{block}\n\t(sheet_instances)", 1)

    def transactional_write(mutator: Callable[[str], str]) -> str:
        current = schematic.read_text(encoding="utf-8")
        updated = mutator(current)
        writes.append(updated)
        return str(schematic)

    def sort_symbols(symbols: list[dict[str, Any]], order: str) -> None:
        calls.append(("sort_symbols", order))
        symbols.sort(key=lambda symbol: str(symbol["reference"]), reverse=True)

    service = SchematicLifecycleAuthoringService(
        snap_point=lambda x, y, enabled: snap_result,
        snap_notice=lambda before, after: snap_note,
        next_reference=lambda prefix: "JP4",
        place_symbol_block=place_symbol_block,
        append_before_sheet_instances=append_before_sheet_instances,
        transactional_write=transactional_write,
        reload_schematic=lambda: "Reloaded",
        active_schematic_file=lambda: schematic,
        parse_schematic=lambda path: parsed_value,
        sort_symbols_for_annotation=sort_symbols,
    )
    return service, calls, writes


@pytest.mark.parametrize("pins", [1, 4])
def test_add_jumper_rejects_unsupported_pin_counts(tmp_path: Path, pins: int) -> None:
    service, _calls, writes = _service(tmp_path)

    with pytest.raises(ValueError, match="Only 2-pin and 3-pin jumpers are supported"):
        service.add_jumper(10.0, 20.0, pins=pins)

    assert writes == []


def test_add_jumper_preserves_snap_placement_transaction_and_response(tmp_path: Path) -> None:
    service, calls, writes = _service(
        tmp_path,
        snap_result=(30.0, 40.0),
        snap_note="Snapped to schematic grid.",
    )

    result = service.add_jumper(
        30.2,
        40.3,
        pins=3,
        open_by_default=False,
        snap_to_grid=True,
    )

    assert calls == [
        (
            "place_symbol_block",
            {
                "lib_id": "Jumper:Jumper_3_Closed",
                "x": 30.0,
                "y": 40.0,
                "reference": "JP4",
                "value": "Jumper_3_Closed",
            },
        )
    ]
    assert len(writes) == 1
    assert "SYMBOL(JP4,Jumper_3_Closed,30.0,40.0)" in writes[0]
    assert result == (
        "Added jumper 'JP4' (Jumper_3_Closed) at (30.00, 40.00) mm.\n"
        "Reloaded\nSnapped to schematic grid."
    )


def test_add_jumper_omits_empty_snap_note(tmp_path: Path) -> None:
    service, _calls, _writes = _service(tmp_path, snap_result=(10.0, 20.0), snap_note="")

    result = service.add_jumper(10.0, 20.0)

    assert result == "Added jumper 'JP4' (Jumper_2_Open) at (10.00, 20.00) mm.\nReloaded"


def test_annotate_sorts_allocates_prefix_counters_and_writes(tmp_path: Path) -> None:
    parsed = {
        "symbols": [
            {"reference": "R?"},
            {"reference": "U?"},
            {"reference": "R12"},
        ]
    }
    service, calls, writes = _service(tmp_path, parsed=parsed)

    result = service.annotate(start_number=10, order="sheet")

    assert calls == [("sort_symbols", "sheet")]
    assert len(writes) == 1
    assert '(property "Reference" "R11")' in writes[0]
    assert '(property "Reference" "U10")' in writes[0]
    assert result == "Annotated 3 symbol(s).\nReloaded"


def test_annotate_preserves_pydantic_validation(tmp_path: Path) -> None:
    service, _calls, writes = _service(tmp_path)

    with pytest.raises(ValidationError):
        service.annotate(start_number=0, order="alpha")
    with pytest.raises(ValidationError):
        service.annotate(start_number=1, order="diagonal")

    assert writes == []


def test_reload_delegates_directly(tmp_path: Path) -> None:
    service, _calls, _writes = _service(tmp_path)

    assert service.reload() == "Reloaded"
