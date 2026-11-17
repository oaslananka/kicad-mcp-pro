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


def test_preview_refusal_is_never_promoted_into_an_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _arrange(monkeypatch)
    monkeypatch.setattr(
        adapter,
        "_preview_one_via",
        lambda *_a, **_kw: json.dumps({"status": "refused", "reason": "No safe route"}),
    )
    outcome = json.loads(adapter._apply_one_via("correct", **_params()))
    assert outcome["status"] == "refused"
    assert "No safe route" in outcome["reason"]
    assert stats == {"preflight": 0, "publish": 0}


def test_apply_never_runs_native_drc_if_board_revision_has_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _arrange(monkeypatch)
    monkeypatch.setattr(
        adapter,
        "get_board",
        lambda: SimpleNamespace(get_as_string=lambda: "(kicad_pcb changed externally)"),
    )
    result = json.loads(adapter._apply_one_via("correct", **_params()))
    assert result["status"] == "refused"
    assert "changed" in result["reason"].lower()
    assert stats == {"preflight": 0, "publish": 0}


def test_apply_refuses_when_native_project_rules_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _arrange(monkeypatch)
    monkeypatch.setattr(
        adapter,
        "get_config",
        lambda: SimpleNamespace(project_file=None, kicad_cli=Path("fake-cli")),
    )
    result = json.loads(adapter._apply_one_via("correct", **_params()))
    assert result["status"] == "refused"
    assert "project rules unavailable" in result["reason"]
    assert stats == {"preflight": 0, "publish": 0}


def test_apply_refuses_native_drc_engine_errors_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.pcb.route_drc_preflight import RoutePreflightError

    stats = _arrange(monkeypatch)

    def broken(*_args: object, **_kwargs: object) -> dict:
        stats["preflight"] += 1
        raise RoutePreflightError("Native CLI unavailable")

    monkeypatch.setattr(adapter, "run_route_drc_preflight", broken)
    result = json.loads(adapter._apply_one_via("correct", **_params()))
    assert result["status"] == "refused"
    assert "Native CLI unavailable" in result["reason"]
    assert stats == {"preflight": 1, "publish": 0}


def test_apply_refuses_if_board_changes_during_native_drc_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _arrange(monkeypatch)
    reads = iter(["(kicad_pcb immutable)", "(kicad_pcb edited during DRC)"])
    monkeypatch.setattr(
        adapter,
        "get_board",
        lambda: SimpleNamespace(get_as_string=lambda: next(reads)),
    )
    result = json.loads(adapter._apply_one_via("correct", **_params()))
    assert result["status"] == "refused"
    assert "changed during" in result["reason"]
    assert stats == {"preflight": 1, "publish": 0}


def test_apply_preserves_native_publisher_refusal_without_claiming_geometry_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _arrange(monkeypatch)

    def refused(*_args: object, **_kwargs: object) -> str:
        stats["publish"] += 1
        return json.dumps(
            {"status": "refused", "committed": False, "reason": "Native undo unavailable"}
        )

    monkeypatch.setattr(adapter, "_publish_route_specs", refused)
    result = json.loads(adapter._apply_one_via("correct", **_params()))
    assert result["status"] == "refused"
    assert result["committed"] is False
    assert "warning" not in result
    assert "viaGeometry" not in result
    assert stats == {"preflight": 1, "publish": 1}


@pytest.mark.parametrize("candidate_id", [None, 42, [], {}])
def test_nonstring_candidate_id_never_reaches_drc_or_native_write(
    monkeypatch: pytest.MonkeyPatch,
    candidate_id: object,
) -> None:
    stats = _arrange(monkeypatch)
    result = json.loads(adapter._apply_one_via(candidate_id, **_params()))
    assert result["status"] == "refused"
    assert "candidate ID" in result["reason"]
    assert stats == {"preflight": 0, "publish": 0}


def test_apply_refuses_malformed_candidate_without_native_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = _arrange(monkeypatch)
    monkeypatch.setattr(
        adapter,
        "_preview_one_via",
        lambda *_a, **_kw: json.dumps({"status": "candidate", "candidateId": "correct"}),
    )
    result = json.loads(adapter._apply_one_via("correct", **_params()))
    assert result["status"] == "refused"
    assert stats == {"preflight": 0, "publish": 0}
