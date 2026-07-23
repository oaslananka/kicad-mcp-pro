from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from kicad_mcp.schematic.destructive_edit import SchematicDestructiveEditService


class _TransactionRecorder:
    def __init__(self, current: str) -> None:
        self.current = current
        self.calls: list[bool] = []
        self.updated: str | None = None

    def __call__(
        self,
        mutator: Callable[[str], str],
        *,
        allow_node_loss: bool = False,
    ) -> str:
        self.calls.append(allow_node_loss)
        self.updated = mutator(self.current)
        return self.updated


def _simple_extract_block(content: str, start: int) -> tuple[str, int]:
    end = content.index(")", start) + 1
    return content[start:end], end - start


def _fmt_mm(value: float) -> str:
    return f"{value:g}"


def _service(
    *,
    current: str,
    transaction: _TransactionRecorder | None = None,
    wire_records: list[dict[str, Any]] | None = None,
    wire_blocks: Mapping[str, dict[str, Any]] | None = None,
    symbol_matches: Mapping[str, list[tuple[str, int, int, dict[str, Any]]]] | None = None,
    symbol_blocks: Mapping[str, dict[str, Any]] | None = None,
    label_blocks: Mapping[str, dict[str, Any]] | None = None,
    snap_result: tuple[float, float] | None = None,
    snap_message: str = "",
    justify_calls: list[tuple[str, str]] | None = None,
) -> tuple[SchematicDestructiveEditService, _TransactionRecorder]:
    tx = transaction or _TransactionRecorder(current)
    justify_records = justify_calls if justify_calls is not None else []

    def read_text(_path: Path) -> str:
        return current

    def parse_wire(block: str) -> dict[str, Any] | None:
        return (wire_blocks or {}).get(block)

    def find_symbols(
        _content: str,
        reference: str,
    ) -> list[tuple[str, int, int, dict[str, Any]]]:
        return list((symbol_matches or {}).get(reference, []))

    def parse_symbol(block: str) -> dict[str, Any] | None:
        return (symbol_blocks or {}).get(block)

    def parse_label(block: str) -> dict[str, Any] | None:
        return (label_blocks or {}).get(block)

    def normalize_justify(value: str | None) -> str | None:
        if value is None or value.strip().casefold() in {"", "none"}:
            return None
        return " ".join(value.strip().casefold().split())

    def set_justify(block: str, justify: str) -> str:
        justify_records.append((block, justify))
        return f"{block}[justify={justify}]"

    return (
        SchematicDestructiveEditService(
            active_schematic_file=lambda: Path("demo.kicad_sch"),
            read_schematic_text=read_text,
            extract_wires=lambda _content: list(wire_records or []),
            wire_id_matches=lambda actual, requested: (
                actual.casefold() == requested.casefold()
                or actual.casefold().startswith(requested.casefold())
                or requested.casefold().startswith(actual.casefold())
            ),
            wire_signature=lambda x1, y1, x2, y2: (
                float(x1),
                float(y1),
                float(x2),
                float(y2),
            ),
            extract_block=_simple_extract_block,
            parse_wire_block=parse_wire,
            format_mm=_fmt_mm,
            transactional_write=tx,
            reload_schematic=lambda: "Reloaded schematic.",
            find_placed_symbol_blocks=find_symbols,
            symbol_connection_points=lambda parsed: set(parsed.get("points", set())),
            parse_symbol_block=parse_symbol,
            coordinate_key=lambda x, y: (round(float(x), 4), round(float(y), 4)),
            parse_label_block=parse_label,
            snap_point=lambda x, y, enabled: snap_result if enabled and snap_result else (x, y),
            snap_notice=lambda _original, _snapped: snap_message,
            normalize_label_justify=normalize_justify,
            set_label_justify=set_justify,
        ),
        tx,
    )


def test_delete_wire_preserves_prefix_matching_and_destructive_transaction() -> None:
    current = "aa(wire-a)bb"
    record = {"uuid": "abc123", "x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0}
    service, transaction = _service(
        current=current,
        wire_records=[record],
        wire_blocks={"(wire-a)": record},
    )

    assert service.delete_wire("abc") == (
        "Reloaded schematic.\nDeleted wire 'abc123' from (1, 2) to (3, 4)."
    )
    assert transaction.calls == [True]
    assert transaction.updated == "aabb"


def test_delete_wire_preserves_missing_and_ambiguous_results() -> None:
    missing, missing_tx = _service(current="plain")
    assert missing.delete_wire("missing") == (
        "Wire 'missing' was not found in the active schematic."
    )
    assert missing_tx.calls == []

    ambiguous, ambiguous_tx = _service(
        current="plain",
        wire_records=[
            {"uuid": "abcd-1", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
            {"uuid": "abcd-2", "x1": 1, "y1": 1, "x2": 2, "y2": 2},
        ],
    )
    assert ambiguous.delete_wire("abcd") == (
        "Wire identifier 'abcd' is ambiguous. Matching UUIDs: abcd-1, abcd-2"
    )
    assert ambiguous_tx.calls == []


def test_delete_symbol_removes_matching_symbols_and_attached_wires() -> None:
    current = "aa(symbol-r1)bb(wire-attached)cc(wire-other)dd"
    symbol = {"reference": "R1", "points": {(1.0, 2.0)}}
    attached = {"x1": 1.0, "y1": 2.0, "x2": 5.0, "y2": 6.0}
    other = {"x1": 7.0, "y1": 8.0, "x2": 9.0, "y2": 10.0}
    service, transaction = _service(
        current=current,
        symbol_matches={"R1": [("(symbol-r1)", 2, 13, symbol)]},
        symbol_blocks={"(symbol-r1)": symbol},
        wire_blocks={"(wire-attached)": attached, "(wire-other)": other},
    )

    assert service.delete_symbol("R1") == (
        "Reloaded schematic.\nDeleted 1 symbol block(s) for 'R1' and 1 directly connected wire(s)."
    )
    assert transaction.calls == [True]
    assert transaction.updated == "aabbcc(wire-other)dd"


def test_delete_symbol_preserves_missing_reference_result() -> None:
    service, transaction = _service(current="plain")

    assert service.delete_symbol("R404") == ("Reference 'R404' was not found in the schematic.")
    assert transaction.calls == [True]
    assert transaction.updated is None


def test_delete_label_matches_raw_or_grid_snapped_coordinates() -> None:
    current = "aa(label-vcc)bb"
    service, transaction = _service(
        current=current,
        label_blocks={"(label-vcc)": {"name": "VCC", "x": 50.8, "y": 50.8}},
        snap_result=(50.8, 50.8),
    )

    assert service.delete_label("VCC", 50.0, 50.0) == (
        "Reloaded schematic.\nDeleted 1 label(s) 'VCC' at (50, 50)."
    )
    assert transaction.calls == [True]
    assert transaction.updated == "aabb"


def test_delete_label_preserves_missing_result() -> None:
    service, transaction = _service(current="aa(label-gnd)bb")

    assert service.delete_label("GND", 1.0, 2.0) == ("No label 'GND' found near (1, 2).")
    assert transaction.calls == [True]
    assert transaction.updated is None


def test_move_label_preserves_rotation_snap_notice_and_normal_transaction() -> None:
    current = "aa(label-vcc (at 1 2 90))bb"
    block = "(label-vcc (at 1 2 90)"
    service, transaction = _service(
        current=current,
        label_blocks={block: {"name": "VCC", "x": 1.0, "y": 2.0, "rotation": 90}},
        snap_result=(10.16, 20.32),
        snap_message="Grid snap: (10.0, 20.0) -> (10.16, 20.32)",
    )

    assert service.move_label("VCC", 1.0, 2.0, 10.0, 20.0, None, True) == (
        "Reloaded schematic.\n"
        "Moved label 'VCC' to (10.16, 20.32) mm.\n"
        "Grid snap: (10.0, 20.0) -> (10.16, 20.32)"
    )
    assert transaction.calls == [False]
    assert "(at 10.16 20.32 90)" in str(transaction.updated)


def test_move_label_preserves_missing_result_without_reload() -> None:
    service, transaction = _service(current="plain")

    assert service.move_label("NOPE", 1.0, 2.0, 3.0, 4.0, 0, False) == (
        "No label 'NOPE' found near (1, 2)."
    )
    assert transaction.calls == [False]
    assert transaction.updated is None


def test_modify_label_preserves_normalization_and_result() -> None:
    current = "aa(label-vcc)bb"
    justify_calls: list[tuple[str, str]] = []
    service, transaction = _service(
        current=current,
        label_blocks={"(label-vcc)": {"name": "VCC", "x": 1.0, "y": 2.0}},
        justify_calls=justify_calls,
    )

    assert service.modify_label("VCC", 1.0, 2.0, "LEFT   TOP") == (
        "Reloaded schematic.\nSet justify='left top' on label 'VCC' at (1, 2)."
    )
    assert transaction.calls == [False]
    assert justify_calls == [("(label-vcc)", "left top")]


def test_modify_label_preserves_centered_and_missing_results() -> None:
    centered, _transaction = _service(
        current="aa(label-vcc)bb",
        label_blocks={"(label-vcc)": {"name": "VCC", "x": 1.0, "y": 2.0}},
    )
    assert centered.modify_label("VCC", 1.0, 2.0, "none") == (
        "Reloaded schematic.\nSet justify='none (centered)' on label 'VCC' at (1, 2)."
    )

    missing, missing_tx = _service(current="plain")
    assert missing.modify_label("NOPE", 1.0, 2.0, "left") == ("No label 'NOPE' found near (1, 2).")
    assert missing_tx.calls == [False]
