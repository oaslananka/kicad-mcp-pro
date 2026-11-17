"""Via and its two copper segments must publish through exactly one native undo."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from kicad_mcp.routing.manual_tracks import TrackSpec, ViaSpec
from kicad_mcp.tools import routing_manual_tracks as adapter


def test_one_through_via_is_one_transaction_not_three_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "(kicad_pcb immutable stage)"
    revision = hashlib.sha256(text.encode()).hexdigest()
    stats = {"begin": 0, "push": 0, "drop": 0, "mutation": 0, "item_count": 0, "via_count": 0}
    monkeypatch.setattr(adapter, "get_board", lambda: SimpleNamespace(get_as_string=lambda: text))

    class Tx:
        def begin(self) -> str:
            stats["begin"] += 1
            return "Transaction group started."

        def push(self) -> str:
            stats["push"] += 1
            return "Transaction group committed successfully."

        def drop(self) -> str:
            stats["drop"] += 1
            return "Transaction group discarded successfully."

    monkeypatch.setattr(adapter, "get_live_edit_service", Tx)

    def execute(_name: str, callback: object, *, verifier: object) -> list[object]:
        stats["mutation"] += 1

        def create(items: list[object]) -> list[object]:
            stats["item_count"] = len(items)
            stats["via_count"] = sum(type(i).__name__ == "Via" for i in items)
            return items

        board = SimpleNamespace(create_items=create)
        callback(board)
        return []

    monkeypatch.setattr(adapter, "execute_live_board_mutation", execute)
    tracks = [
        TrackSpec(10.95, 10, 15, 10, "F_Cu", 0.25, "MID"),
        TrackSpec(15, 10, 19.05, 10, "B_Cu", 0.25, "MID"),
    ]
    via = ViaSpec(15, 10, 0.8, 0.4, "MID")
    evidence = {
        "accepted": True,
        "introducedViolations": 0,
        "unconnectedBefore": 1,
        "unconnectedAfter": 0,
    }
    result = json.loads(
        adapter._publish_route_specs(
            tracks,
            revision,
            evidence,
            "via-candidate",
            through_via=via,
        )
    )
    assert result["status"] == "applied"
    assert result["saved"] is False
    assert stats == {
        "begin": 1,
        "push": 1,
        "drop": 0,
        "mutation": 1,
        "item_count": 3,
        "via_count": 1,
    }
