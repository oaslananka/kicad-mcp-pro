"""Read-only coupled USB route candidate and DRC-first atomic write contracts."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import routing_coupled_pair as adapter


def _args() -> dict[str, object]:
    return dict(
        p_ref1="R1",
        p_pad1="2",
        p_ref2="R2",
        p_pad2="1",
        n_ref1="R1",
        n_pad1="1",
        n_ref2="R2",
        n_pad2="2",
        layer="F_Cu",
        width_mm=0.25,
        gap_mm=0.5,
        clearance_mm=0.2,
        max_skew_mm=0.1,
    )


def _arrange(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    text = "(kicad_pcb stable paired board)"
    revision = hashlib.sha256(text.encode()).hexdigest()
    stats = {"preflight": 0, "publish": 0}
    segments = [
        {
            "x1_mm": 10.95,
            "y1_mm": 8.5,
            "x2_mm": 13.0,
            "y2_mm": 8.5,
            "layer": "F_Cu",
            "width_mm": 0.25,
            "net_name": "USB_D_P",
        },
        {
            "x1_mm": 13.0,
            "y1_mm": 8.5,
            "x2_mm": 14.0,
            "y2_mm": 7.5,
            "layer": "F_Cu",
            "width_mm": 0.25,
            "net_name": "USB_D_P",
        },
        {
            "x1_mm": 10.95,
            "y1_mm": 9.25,
            "x2_mm": 13.0,
            "y2_mm": 9.25,
            "layer": "F_Cu",
            "width_mm": 0.25,
            "net_name": "USB_D_N",
        },
        {
            "x1_mm": 13.0,
            "y1_mm": 9.25,
            "x2_mm": 14.0,
            "y2_mm": 8.25,
            "layer": "F_Cu",
            "width_mm": 0.25,
            "net_name": "USB_D_N",
        },
    ]

    def preview(**_kwargs: object) -> str:
        return json.dumps(
            {
                "status": "candidate",
                "boardRevision": revision,
                "candidateId": "correct-hash",
                "segments": segments,
                "netPlus": "USB_D_P",
                "netMinus": "USB_D_N",
                "geometry": {"skewMm": 0.0, "minCopperGapMm": 0.5},
            }
        )

    def preflight(*_a: object, **kwargs: object) -> dict[str, int | bool]:
        stats["preflight"] += 1
        assert kwargs["pair_nets"] == frozenset({"USB_D_P", "USB_D_N"})
        return {
            "accepted": True,
            "introducedViolations": 0,
            "unconnectedBefore": 2,
            "unconnectedAfter": 0,
        }

    def publish(*_a: object, **_kwargs: object) -> str:
        stats["publish"] += 1
        return json.dumps({"status": "applied", "committed": True, "saved": False})

    monkeypatch.setattr(adapter, "_preview_coupled_pair", preview)
    monkeypatch.setattr(adapter, "get_board", lambda: SimpleNamespace(get_as_string=lambda: text))
    monkeypatch.setattr(
        adapter,
        "get_config",
        lambda: SimpleNamespace(project_file="fake_pro", kicad_cli="fake_cli"),
    )
    monkeypatch.setattr(adapter, "run_route_drc_preflight", preflight)
    monkeypatch.setattr(adapter, "_publish_route_specs", publish)
    return stats


def test_stale_candidate_never_calls_native_drc_or_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = _arrange(monkeypatch)
    response = json.loads(adapter._apply_coupled_pair("WRONG", **_args()))
    assert response["status"] == "refused"
    assert stats == {"preflight": 0, "publish": 0}


def test_two_lane_native_drc_must_accept_before_atomic_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _arrange(monkeypatch)
    response = json.loads(adapter._apply_coupled_pair("correct-hash", **_args()))
    assert response["status"] == "applied"
    assert response["saved"] is False
    assert stats == {"preflight": 1, "publish": 1}


def test_new_native_drc_violation_refuses_before_write(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = _arrange(monkeypatch)

    def reject(*_a: object, **_kwargs: object) -> dict[str, int | bool]:
        stats["preflight"] += 1
        return {
            "accepted": False,
            "introducedViolations": 1,
            "unconnectedBefore": 2,
            "unconnectedAfter": 0,
        }

    monkeypatch.setattr(adapter, "run_route_drc_preflight", reject)
    response = json.loads(adapter._apply_coupled_pair("correct-hash", **_args()))
    assert response["status"] == "refused"
    assert response["introducedViolations"] == 1
    assert stats == {"preflight": 1, "publish": 0}
