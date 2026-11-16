"""Matched straight-pair candidate ID, write gate and atomic apply contract."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import routing_manual_tracks as adapter


def _args() -> dict[str, object]:
    return {
        "p_ref1": "R1",
        "p_pad1": "2",
        "p_ref2": "R2",
        "p_pad2": "1",
        "n_ref1": "R1",
        "n_pad1": "1",
        "n_ref2": "R2",
        "n_pad2": "2",
        "layer": "F_Cu",
        "width_mm": 0.25,
        "gap_mm": 0.5,
        "clearance_mm": 0.2,
        "max_skew_mm": 0.1,
    }


def _set_preview(monkeypatch: pytest.MonkeyPatch, *, n_y: float = 9.25) -> dict[str, int]:
    board_text = "(kicad_pcb stable read-only digest)"
    revision = hashlib.sha256(board_text.encode()).hexdigest()
    stats = {"preflight": 0, "mutation": 0, "begin": 0, "push": 0, "drop": 0}

    def preview(
        ref1: str, pad1: str, ref2: str, pad2: str, layer: str, width: float, clearance: float
    ) -> str:
        positive = pad1 == "2"
        net = "USB_D_P" if positive else "USB_D_N"
        y = 8.5 if positive else n_y
        return json.dumps(
            {
                "status": "candidate",
                "boardRevision": revision,
                "segments": [
                    {
                        "x1_mm": 10.95,
                        "y1_mm": y,
                        "x2_mm": 19.05,
                        "y2_mm": y,
                        "layer": layer,
                        "width_mm": width,
                        "net_name": net,
                    }
                ],
            }
        )

    class Transaction:
        def begin(self) -> str:
            stats["begin"] += 1
            return "Transaction group started."

        def push(self) -> str:
            stats["push"] += 1
            return "Transaction group committed successfully."

        def drop(self) -> str:
            stats["drop"] += 1
            return "Transaction group discarded successfully."

    def preflight(*_a: object, **kwargs: object) -> dict[str, int | bool]:
        assert kwargs["pair_nets"] == frozenset(("USB_D_P", "USB_D_N"))
        stats["preflight"] += 1
        return {
            "accepted": True,
            "introducedViolations": 0,
            "unconnectedBefore": 2,
            "unconnectedAfter": 0,
        }

    def mutation(*_a: object, **_kw: object) -> list[object]:
        stats["mutation"] += 1
        return []

    monkeypatch.setattr(adapter, "_preview_route_between_pads", preview)
    monkeypatch.setattr(
        adapter, "get_board", lambda: SimpleNamespace(get_as_string=lambda: board_text)
    )
    monkeypatch.setattr(
        adapter,
        "get_config",
        lambda: SimpleNamespace(
            project_file="fake",
            kicad_cli="fake",
        ),
    )
    monkeypatch.setattr(adapter, "run_route_drc_preflight", preflight)
    monkeypatch.setattr(adapter, "get_live_edit_service", Transaction)
    monkeypatch.setattr(adapter, "execute_live_board_mutation", mutation)
    return stats


def test_pair_preview_is_coupled_and_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = _set_preview(monkeypatch)
    preview = json.loads(adapter._preview_straight_differential_pair(**_args()))
    assert preview["status"] == "candidate"
    assert len(preview["candidateId"]) == 64
    assert preview["drcVerified"] is False
    assert preview["candidateOnly"] is True
    assert preview["geometry"]["skewMm"] == 0.0
    assert preview["geometry"]["gapMm"] == 0.5
    assert [s["net_name"] for s in preview["segments"]] == ["USB_D_P", "USB_D_N"]
    assert not any(stats.values())


def test_pair_preview_rejects_gap_without_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = _set_preview(monkeypatch, n_y=9.1)
    preview = json.loads(adapter._preview_straight_differential_pair(**_args()))
    assert preview["status"] == "refused"
    assert "gap" in preview["reason"]
    assert not any(stats.values())


def test_pair_apply_rejects_wrong_candidate_id_before_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _set_preview(monkeypatch)
    outcome = json.loads(adapter._apply_straight_differential_pair("wrong", **_args()))
    assert outcome["status"] == "refused"
    assert not any(stats.values())


def test_pair_apply_uses_one_native_undo_and_no_automatic_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _set_preview(monkeypatch)
    candidate = json.loads(adapter._preview_straight_differential_pair(**_args()))
    outcome = json.loads(
        adapter._apply_straight_differential_pair(candidate["candidateId"], **_args())
    )
    assert outcome["status"] == "applied"
    assert outcome["saved"] is False
    assert outcome["unconnectedBefore"] == 2
    assert outcome["unconnectedAfter"] == 0
    assert stats == {"preflight": 1, "mutation": 1, "begin": 1, "push": 1, "drop": 0}


def test_pair_apply_refuses_new_native_drc_findings_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _set_preview(monkeypatch)

    def regressed(*_args: object, **_kwargs: object) -> dict[str, bool | int]:
        stats["preflight"] += 1
        return {
            "accepted": False,
            "introducedViolations": 1,
            "unconnectedBefore": 2,
            "unconnectedAfter": 0,
        }

    monkeypatch.setattr(adapter, "run_route_drc_preflight", regressed)
    preview = json.loads(adapter._preview_straight_differential_pair(**_args()))
    result = json.loads(
        adapter._apply_straight_differential_pair(preview["candidateId"], **_args())
    )
    assert result["status"] == "refused"
    assert result["introducedViolations"] == 1
    assert stats == {"preflight": 1, "mutation": 0, "begin": 0, "push": 0, "drop": 0}


def test_pair_apply_rolls_back_two_lanes_on_native_stage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _set_preview(monkeypatch)

    def broken(*_args: object, **_kwargs: object) -> list[object]:
        stats["mutation"] += 1
        raise RuntimeError("Synthetic interrupted two-lane IPC stage")

    monkeypatch.setattr(adapter, "execute_live_board_mutation", broken)
    preview = json.loads(adapter._preview_straight_differential_pair(**_args()))
    result = json.loads(
        adapter._apply_straight_differential_pair(preview["candidateId"], **_args())
    )
    assert result["status"] == "refused"
    assert stats == {"preflight": 1, "mutation": 1, "begin": 1, "push": 0, "drop": 1}
