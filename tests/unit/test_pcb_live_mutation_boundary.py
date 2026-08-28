from __future__ import annotations

import ast
from pathlib import Path

import pytest

from kicad_mcp.pcb.live_edit_runtime import (
    REVIEWED_LIVE_MUTATIONS,
    execute_live_board_mutation,
    reset_live_edit_service,
)

EXPECTED_REVIEWED = {
    "pcb_add_track",
    "pcb_add_tracks_bulk",
    "pcb_add_via",
    "pcb_add_blind_via",
    "pcb_add_microvia",
    "pcb_add_segment",
    "pcb_add_circle",
    "pcb_add_rectangle",
    "pcb_set_board_outline",
    "pcb_add_text",
    "pcb_delete_items",
    "pcb_save",
    "pcb_refill_zones",
    "pcb_move_footprint",
    "pcb_set_footprint_layer",
    "pcb_add_zone",
    "pcb_set_keepout_zone",
    "pcb_add_teardrops",
    "route_single_track",
    "route_from_pad_to_pad",
    "pdn_generate_power_plane",
    "pcb_set_origin",
    "pcb_set_title_block_info",
}

PARTICIPATING = {
    "pcb_add_track",
    "pcb_add_via",
    "pcb_delete_items",
    "pcb_move_footprint",
    "pcb_set_footprint_layer",
}


def _calls_named(path: Path, name: str) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]


def test_reviewed_live_mutation_inventory_is_complete_and_single_sourced() -> None:
    assert set(REVIEWED_LIVE_MUTATIONS) == EXPECTED_REVIEWED
    assert {name for name, participates in REVIEWED_LIVE_MUTATIONS.items() if participates} == (
        PARTICIPATING
    )


def test_reviewed_mutation_modules_do_not_use_legacy_board_transaction() -> None:
    for relative in (
        "src/kicad_mcp/tools/pcb.py",
        "src/kicad_mcp/tools/routing.py",
        "src/kicad_mcp/tools/power_integrity.py",
    ):
        path = Path(relative)
        assert _calls_named(path, "board_transaction") == [], relative


def test_non_participating_runtime_operation_is_rejected_before_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.pcb import live_edit_runtime
    from kicad_mcp.pcb.transaction_lifecycle import PcbTransactionLifecycleService

    class Board:
        name = "demo.kicad_pcb"

        def __init__(self) -> None:
            self.state = "before"
            self.commit = object()

        def get_project(self):
            from types import SimpleNamespace

            return SimpleNamespace(path="/workspace/demo/demo.kicad_pro", name="demo")

        def get_as_string(self) -> str:
            return self.state

        def begin_commit(self):
            return self.commit

        def drop_commit(self, commit) -> None:
            assert commit is self.commit
            self.state = "before"

    board = Board()
    service = PcbTransactionLifecycleService(
        get_board=lambda: board,
        run_mutation=lambda _operation, command: command(),
        connection_errors=(OSError,),
    )
    monkeypatch.setattr(live_edit_runtime, "_SERVICE", service)
    assert service.begin().startswith("Transaction group started.")
    effects: list[str] = []

    with pytest.raises(RuntimeError, match="does not participate"):
        execute_live_board_mutation(
            "pcb_add_text",
            lambda _board: effects.append("mutated"),
            verifier=None,
        )

    assert effects == []
    assert service.drop() == "Transaction group discarded successfully."
    reset_live_edit_service()
