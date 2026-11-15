"""One-via candidate must be bound to board revision and pass native DRC before IPC."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import routing_one_via as adapter


def _params() -> dict[str, object]:
    return {
        "ref1": "R1",
        "pad1": "2",
        "ref2": "R2",
        "pad2": "1",
        "start_layer": "F_Cu",
        "end_layer": "B_Cu",
        "width_mm": 0.25,
        "via_diameter_mm": 0.8,
        "via_drill_mm": 0.4,
        "clearance_mm": 0.2,
    }


def _arrange(monkeypatch: pytest.MonkeyPatch, accept: bool = True) -> dict[str, int]:
    board = "(kicad_pcb immutable)"
    revision = hashlib.sha256(board.encode()).hexdigest()
    stats = {"preflight": 0, "publish": 0}
    preview = {
        "status": "candidate",
        "candidateId": "correct",
        "boardRevision": revision,
        "net": "MID",
        "segments": [
            {
                "x1_mm": 10.95,
                "y1_mm": 10,
                "x2_mm": 15,
                "y2_mm": 10,
                "layer": "F_Cu",
                "width_mm": 0.25,
                "net_name": "MID",
            },
            {
                "x1_mm": 15,
                "y1_mm": 10,
                "x2_mm": 19.05,
                "y2_mm": 10,
                "layer": "B_Cu",
                "width_mm": 0.25,
                "net_name": "MID",
            },
        ],
        "throughVia": {
            "x_mm": 15,
            "y_mm": 10,
            "diameter_mm": 0.8,
            "drill_mm": 0.4,
            "net_name": "MID",
        },
    }
    monkeypatch.setattr(adapter, "_preview_one_via", lambda *_args, **_kwargs: json.dumps(preview))
    monkeypatch.setattr(adapter, "get_board", lambda: SimpleNamespace(get_as_string=lambda: board))
    monkeypatch.setattr(
        adapter,
        "get_config",
        lambda: SimpleNamespace(project_file=Path("fake.kicad_pro"), kicad_cli=Path("fake-cli")),
    )

    def preflight(*args: object, **kwargs: object) -> dict[str, int | bool]:
        stats["preflight"] += 1
        assert kwargs["through_via"].x_mm == 15
        assert len(args[1]) == 2
        return {
            "accepted": accept,
            "introducedViolations": 0 if accept else 1,
            "unconnectedBefore": 1,
            "unconnectedAfter": 0,
        }

    def publish(*_args: object, **kwargs: object) -> str:
        stats["publish"] += 1
        assert kwargs["through_via"].diameter_mm == 0.8
        return json.dumps({"status": "applied", "committed": True, "saved": False})

    monkeypatch.setattr(adapter, "run_route_drc_preflight", preflight)
    monkeypatch.setattr(adapter, "_publish_route_specs", publish)
    return stats


def test_wrong_candidate_never_stages_or_runs_drc(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = _arrange(monkeypatch)
    result = json.loads(adapter._apply_one_via("wrong", **_params()))
    assert result["status"] == "refused"
    assert stats == {"preflight": 0, "publish": 0}


def test_drc_regression_refuses_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = _arrange(monkeypatch, accept=False)
    result = json.loads(adapter._apply_one_via("correct", **_params()))
    assert result["status"] == "refused"
    assert result["introducedViolations"] == 1
    assert stats == {"preflight": 1, "publish": 0}


def test_correct_candidate_passes_one_via_to_shared_atomic_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _arrange(monkeypatch)
    result = json.loads(adapter._apply_one_via("correct", **_params()))
    assert result["status"] == "applied"
    assert result["saved"] is False
    assert stats == {"preflight": 1, "publish": 1}
