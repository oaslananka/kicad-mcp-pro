"""Applying a preview must have independent DRC evidence and a native undo unit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


def _adapter() -> ModuleType:
    from kicad_mcp.tools import routing_manual_tracks

    return routing_manual_tracks


def _arrange(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accepted: bool = True,
) -> tuple[str, dict[str, Any]]:
    adapter = _adapter()
    board_text = "(kicad_pcb original)"
    revision = hashlib.sha256(board_text.encode()).hexdigest()
    candidate = {
        "status": "candidate",
        "boardRevision": revision,
        "candidateId": "a" * 64,
        "segments": [
            {
                "x1_mm": 1.0,
                "y1_mm": 2.0,
                "x2_mm": 5.0,
                "y2_mm": 2.0,
                "net_name": "MID",
                "layer": "F_Cu",
                "width_mm": 0.25,
            },
        ],
    }
    stats = {"begin": 0, "push": 0, "drop": 0, "write": 0, "preflight": 0}

    class Transaction:
        def begin(self) -> str:
            stats["begin"] += 1
            return (
                "Transaction group started. Use pcb_push_commit to apply "
                "or pcb_drop_commit to discard."
            )

        def push(self) -> str:
            stats["push"] += 1
            return "Transaction group committed successfully."

        def drop(self) -> str:
            stats["drop"] += 1
            return "Transaction group discarded successfully."

    monkeypatch.setattr(
        adapter, "_preview_route_between_pads", lambda *_args: json.dumps(candidate)
    )
    monkeypatch.setattr(
        adapter,
        "get_board",
        lambda: SimpleNamespace(get_as_string=lambda: board_text),
    )
    monkeypatch.setattr(
        adapter,
        "get_config",
        lambda: SimpleNamespace(
            project_file=Path("project.kicad_pro"), kicad_cli=Path("kicad-cli")
        ),
    )
    monkeypatch.setattr(adapter, "get_live_edit_service", lambda: Transaction())

    def check_preflight(*_args: object, **_kwargs: object) -> dict[str, int | bool]:
        stats["preflight"] += 1
        return {
            "accepted": accepted,
            "introducedViolations": 0 if accepted else 2,
            "unconnectedBefore": 2,
            "unconnectedAfter": 1,
        }

    def staged_write(*_args: object, **_kwargs: object) -> list[object]:
        stats["write"] += 1
        return []

    monkeypatch.setattr(adapter, "run_route_drc_preflight", check_preflight)
    monkeypatch.setattr(adapter, "execute_live_board_mutation", staged_write)
    return candidate["candidateId"], stats


def test_apply_candidate_refuses_wrong_candidate_without_touching_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _id, stats = _arrange(monkeypatch)
    result = json.loads(_adapter()._apply_route_candidate("wrong", "R1", "2", "R2", "1"))
    assert result["status"] == "refused"
    assert stats == {"begin": 0, "push": 0, "drop": 0, "write": 0, "preflight": 0}


def test_apply_candidate_refuses_drc_regressions_before_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id, stats = _arrange(monkeypatch, accepted=False)
    result = json.loads(_adapter()._apply_route_candidate(candidate_id, "R1", "2", "R2", "1"))
    assert result["status"] == "refused"
    assert result["introducedViolations"] == 2
    assert stats["preflight"] == 1
    assert stats["begin"] == stats["push"] == stats["write"] == stats["drop"] == 0


def test_apply_candidate_commits_once_but_does_not_save_without_user_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id, stats = _arrange(monkeypatch)
    result = json.loads(_adapter()._apply_route_candidate(candidate_id, "R1", "2", "R2", "1"))
    assert result["status"] == "applied"
    assert result["drcPreflightAccepted"] is True
    assert result["saved"] is False
    assert stats == {"begin": 1, "push": 1, "drop": 0, "write": 1, "preflight": 1}


def test_apply_candidate_drops_transaction_on_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id, stats = _arrange(monkeypatch)

    def broken_write(*_args: object, **_kwargs: object) -> None:
        stats["write"] += 1
        raise RuntimeError("Synthetic IPC write failure")

    monkeypatch.setattr(_adapter(), "execute_live_board_mutation", broken_write)
    result = json.loads(_adapter()._apply_route_candidate(candidate_id, "R1", "2", "R2", "1"))
    assert result["status"] == "refused"
    assert stats["begin"] == stats["drop"] == 1
    assert stats["push"] == 0


def test_apply_candidate_reports_recovery_when_native_publish_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id, stats = _arrange(monkeypatch)

    class AmbiguousPublish:
        def begin(self) -> str:
            stats["begin"] += 1
            return "Transaction group started."

        def push(self) -> str:
            stats["push"] += 1
            raise RuntimeError("Synthetic interrupted KiCad publish")

        def drop(self) -> str:
            raise AssertionError("Cannot safely drop after an ambiguous publish")

    monkeypatch.setattr(_adapter(), "get_live_edit_service", AmbiguousPublish)
    result = json.loads(_adapter()._apply_route_candidate(candidate_id, "R1", "2", "R2", "1"))
    assert result["status"] == "recovery_required"
    assert stats["begin"] == stats["push"] == 1


def test_apply_candidate_reports_recovery_when_native_drop_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id, stats = _arrange(monkeypatch)

    class AmbiguousDrop:
        def begin(self) -> str:
            stats["begin"] += 1
            return "Transaction group started."

        def drop(self) -> str:
            stats["drop"] += 1
            raise RuntimeError("Synthetic interrupted KiCad transaction drop")

    def broken_write(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Synthetic staged track write failure")

    monkeypatch.setattr(_adapter(), "get_live_edit_service", AmbiguousDrop)
    monkeypatch.setattr(_adapter(), "execute_live_board_mutation", broken_write)
    result = json.loads(_adapter()._apply_route_candidate(candidate_id, "R1", "2", "R2", "1"))
    assert result["status"] == "recovery_required"
    assert stats["begin"] == stats["drop"] == 1
