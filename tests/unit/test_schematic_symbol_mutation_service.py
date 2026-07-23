from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kicad_mcp.schematic.symbol_mutation import SchematicSymbolMutationService


class _TransactionRecorder:
    def __init__(self, current: str = "aaSYMBOLzz") -> None:
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


def _service(
    *,
    events: list[tuple[str, tuple[object, ...]]] | None = None,
    transaction: _TransactionRecorder | None = None,
    match: tuple[str, int, int, dict[str, Any]] | None = (
        "SYMBOL",
        2,
        8,
        {"x": 1.0, "y": 2.0},
    ),
    snap_result: tuple[float, float] = (10.16, 20.32),
    snap_message: str = "Snapped to the schematic grid.",
) -> SchematicSymbolMutationService:
    records = events if events is not None else []
    tx = transaction or _TransactionRecorder()

    def update_property(reference: str, field: str, value: str) -> str:
        records.append(("update_property", (reference, field, value)))
        return f"Updated {reference}.{field}."

    def set_dnp(reference: str, enabled: bool, reason: str | None) -> str:
        records.append(("set_dnp", (reference, enabled, reason)))
        return f"Set {reference} DNP={enabled}."

    def reload_schematic() -> str:
        records.append(("reload", ()))
        return "Reloaded schematic."

    def snap_point(x_mm: float, y_mm: float, enabled: bool) -> tuple[float, float]:
        records.append(("snap_point", (x_mm, y_mm, enabled)))
        return snap_result

    def snap_notice(
        original: tuple[float, float],
        snapped: tuple[float, float],
    ) -> str:
        records.append(("snap_notice", (original, snapped)))
        return snap_message

    def find_symbol(
        current: str,
        reference: str,
    ) -> tuple[str, int, int, dict[str, Any]] | None:
        records.append(("find_symbol", (current, reference)))
        return match

    def shift_symbol(block: str, *, dx_mm: float, dy_mm: float) -> str:
        records.append(("shift_symbol", (block, dx_mm, dy_mm)))
        return "SHIFTED"

    return SchematicSymbolMutationService(
        update_symbol_property=update_property,
        set_symbol_dnp=set_dnp,
        reload_schematic=reload_schematic,
        snap_point=snap_point,
        snap_notice=snap_notice,
        transactional_write=tx,
        find_placed_symbol_block=find_symbol,
        shift_symbol_block=shift_symbol,
    )


def test_update_properties_preserves_backend_then_reload_result() -> None:
    events: list[tuple[str, tuple[object, ...]]] = []
    service = _service(events=events)

    assert service.update_properties("R1", "Value", "10k") == (
        "Updated R1.Value.\nReloaded schematic."
    )
    assert events == [
        ("update_property", ("R1", "Value", "10k")),
        ("reload", ()),
    ]


def test_set_dnp_preserves_reason_and_reload_order() -> None:
    events: list[tuple[str, tuple[object, ...]]] = []
    service = _service(events=events)

    assert service.set_dnp("R2", False, "variant") == ("Set R2 DNP=False.\nReloaded schematic.")
    assert events == [
        ("set_dnp", ("R2", False, "variant")),
        ("reload", ()),
    ]


def test_move_symbol_preserves_transaction_shift_and_snap_notice() -> None:
    events: list[tuple[str, tuple[object, ...]]] = []
    transaction = _TransactionRecorder()
    service = _service(events=events, transaction=transaction)

    assert service.move_symbol("U1", 10.0, 20.0, True) == (
        "Reloaded schematic.\n"
        "Moved symbol 'U1' to (10.16, 20.32) mm.\n"
        "Snapped to the schematic grid."
    )
    assert transaction.calls == [False]
    assert transaction.updated == "aaSHIFTEDzz"
    assert events == [
        ("snap_point", (10.0, 20.0, True)),
        ("snap_notice", ((10.0, 20.0), (10.16, 20.32))),
        ("find_symbol", ("aaSYMBOLzz", "U1")),
        ("shift_symbol", ("SYMBOL", 9.16, 18.32)),
        ("reload", ()),
    ]


def test_move_symbol_omits_empty_snap_notice() -> None:
    service = _service(snap_result=(5.0, 6.0), snap_message="")

    assert service.move_symbol("U1", 5.0, 6.0, False) == (
        "Reloaded schematic.\nMoved symbol 'U1' to (5.00, 6.00) mm."
    )


def test_move_symbol_preserves_missing_reference_as_result_without_reload() -> None:
    events: list[tuple[str, tuple[object, ...]]] = []
    transaction = _TransactionRecorder()
    service = _service(events=events, transaction=transaction, match=None)

    assert service.move_symbol("R404", 1.0, 2.0, True) == (
        "Reference 'R404' was not found in the schematic."
    )
    assert transaction.calls == [False]
    assert transaction.updated is None
    assert ("reload", ()) not in events
