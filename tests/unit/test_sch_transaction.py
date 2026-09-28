"""Tests for the transactional schematic plan workflow (issue #155)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.models.sch_transaction import (
    PlannedLabel as Label,
)
from kicad_mcp.models.sch_transaction import (
    PlanValidationError,
    compute_plan_id,
    insert_labels,
    plan_changes,
    plan_from_spec,
)

MINIMAL_SCH = """(kicad_sch (version 20240101) (generator "test") (paper "A4")
  (title_block (title "Transaction Test"))
)
"""


def _expect_equal(actual: object, expected: object) -> None:
    """Fail explicitly so regression checks remain active under optimized Python."""
    if actual != expected:
        pytest.fail(f"expected {expected!r}, got {actual!r}")


SUBCIRCUIT_SPEC = {
    "title": "RC output stage",
    "components": [
        {"reference": "R1", "lib_id": "Device:R", "value": "10k"},
        {"reference": "C1", "lib_id": "Device:C", "value": "100n"},
    ],
    "labels": [
        {"text": "VIN", "x": 50, "y": 40},
        {"text": "VOUT", "x": 100, "y": 40},
        {"text": "GND", "x": 75, "y": 60},
    ],
    "nets": ["VIN", "VOUT", "GND"],
}


def test_plan_from_spec_validates() -> None:
    plan = plan_from_spec(SUBCIRCUIT_SPEC)
    assert len(plan.components) == 2
    assert len(plan.labels) == 3
    assert plan.title == "RC output stage"


def test_empty_plan_rejected() -> None:
    with pytest.raises(PlanValidationError):
        plan_from_spec({"title": "empty"})


def test_component_requires_reference_and_lib_id() -> None:
    with pytest.raises(PlanValidationError):
        plan_from_spec({"components": [{"reference": "R1"}]})


def test_plan_id_is_deterministic() -> None:
    assert compute_plan_id(SUBCIRCUIT_SPEC) == compute_plan_id(dict(SUBCIRCUIT_SPEC))
    assert compute_plan_id(SUBCIRCUIT_SPEC) != compute_plan_id({"labels": [{"text": "X"}]})


def test_plan_changes_lists_components_and_labels() -> None:
    changes = plan_changes(plan_from_spec(SUBCIRCUIT_SPEC))
    actions = [change["action"] for change in changes]
    assert actions.count("add_component") == 2
    assert actions.count("add_label") == 3


def test_insert_labels_keeps_balance() -> None:
    out = insert_labels(MINIMAL_SCH, (Label("NET1", 1, 2), Label("NET2", 3, 4)))
    assert out.count("(") == out.count(")")
    assert '"NET1"' in out and '"NET2"' in out
    # Original closing structure is preserved.
    assert out.rstrip().endswith(")")


@pytest.mark.anyio
async def test_full_plan_lifecycle(tmp_path: Path) -> None:
    from kicad_mcp.server import create_server
    from tests.conftest import call_tool_text

    (tmp_path / "test.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "test.kicad_pcb").write_text("", encoding="utf-8")
    sch_file = tmp_path / "test.kicad_sch"
    sch_file.write_text(MINIMAL_SCH, encoding="utf-8")

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(tmp_path)})

    # 1. Plan
    planned = json.loads(
        await call_tool_text(
            server, "sch_plan_from_spec", {"spec_json": json.dumps(SUBCIRCUIT_SPEC)}
        )
    )
    plan_id = planned["plan_id"]
    assert planned["change_count"] == 5

    # 2. Preview does not write.
    before = sch_file.read_text(encoding="utf-8")
    preview = json.loads(await call_tool_text(server, "sch_preview_plan", {"plan_id": plan_id}))
    assert len(preview["changes"]) == 5
    assert sch_file.read_text(encoding="utf-8") == before

    # 3. Apply writes labels + creates a checkpoint.
    applied = json.loads(await call_tool_text(server, "sch_apply_plan", {"plan_id": plan_id}))
    assert applied["status"] == "applied"
    assert applied["labels_added"] == 3
    after_apply = sch_file.read_text(encoding="utf-8")
    assert '"VIN"' in after_apply and '"VOUT"' in after_apply and '"GND"' in after_apply
    assert Path(applied["checkpoint"]).is_dir()

    # 4. Verify fails closed because the plan's components were never placed.
    verified = json.loads(await call_tool_text(server, "sch_verify_plan", {"plan_id": plan_id}))
    _expect_equal(verified["connectivity"], "fail")
    assert verified["missing_labels"] == []
    _expect_equal(verified["missing_components"], ["R1", "C1"])
    _expect_equal(verified["unconnected_labels"], ["VIN", "VOUT", "GND"])
    _expect_equal(verified["connectivity_error"], None)
    assert verified["erc"] in {"available", "unavailable"}

    # 5. Rollback restores the original schematic.
    rolled = json.loads(await call_tool_text(server, "sch_rollback_plan", {"plan_id": plan_id}))
    assert rolled["status"] == "rolled_back"
    assert sch_file.read_text(encoding="utf-8") == before


@pytest.mark.anyio
async def test_verify_plan_fails_for_present_but_unconnected_label(tmp_path: Path) -> None:
    from kicad_mcp.server import create_server
    from tests.conftest import call_tool_text

    (tmp_path / "test.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "test.kicad_pcb").write_text("", encoding="utf-8")
    (tmp_path / "test.kicad_sch").write_text(MINIMAL_SCH, encoding="utf-8")

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(tmp_path)})
    spec = {"title": "floating", "labels": [{"text": "FLOATING", "x": 50, "y": 40}]}
    planned = json.loads(
        await call_tool_text(server, "sch_plan_from_spec", {"spec_json": json.dumps(spec)})
    )
    await call_tool_text(server, "sch_apply_plan", {"plan_id": planned["plan_id"]})

    verified = json.loads(
        await call_tool_text(server, "sch_verify_plan", {"plan_id": planned["plan_id"]})
    )

    _expect_equal(verified["missing_labels"], [])
    _expect_equal(verified["missing_components"], [])
    _expect_equal(verified["unconnected_labels"], ["FLOATING"])
    _expect_equal(verified["connectivity"], "fail")


@pytest.mark.anyio
async def test_verify_plan_accepts_present_label_with_connectivity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.server import create_server
    from kicad_mcp.tools import schematic as schematic_mod
    from tests.conftest import call_tool_text

    (tmp_path / "test.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "test.kicad_pcb").write_text("", encoding="utf-8")
    (tmp_path / "test.kicad_sch").write_text(MINIMAL_SCH, encoding="utf-8")

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(tmp_path)})
    spec = {"title": "connected", "labels": [{"text": "NET1", "x": 50, "y": 40}]}
    planned = json.loads(
        await call_tool_text(server, "sch_plan_from_spec", {"spec_json": json.dumps(spec)})
    )
    await call_tool_text(server, "sch_apply_plan", {"plan_id": planned["plan_id"]})
    monkeypatch.setattr(
        schematic_mod,
        "build_connectivity_groups",
        lambda _path: [{"names": ["NET1"], "points": [(50.0, 40.0), (60.0, 40.0)], "pins": []}],
    )

    verified = json.loads(
        await call_tool_text(server, "sch_verify_plan", {"plan_id": planned["plan_id"]})
    )

    _expect_equal(verified["unconnected_labels"], [])
    _expect_equal(verified["connectivity_error"], None)
    _expect_equal(verified["connectivity"], "pass")


@pytest.mark.anyio
async def test_verify_plan_fails_closed_when_connectivity_analysis_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.server import create_server
    from kicad_mcp.tools import schematic as schematic_mod
    from tests.conftest import call_tool_text

    (tmp_path / "test.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "test.kicad_pcb").write_text("", encoding="utf-8")
    (tmp_path / "test.kicad_sch").write_text(MINIMAL_SCH, encoding="utf-8")

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(tmp_path)})
    spec = {"title": "unavailable", "labels": [{"text": "NET1", "x": 50, "y": 40}]}
    planned = json.loads(
        await call_tool_text(server, "sch_plan_from_spec", {"spec_json": json.dumps(spec)})
    )
    await call_tool_text(server, "sch_apply_plan", {"plan_id": planned["plan_id"]})

    def _raise_connectivity(_path: Path) -> list[dict[str, object]]:
        raise RuntimeError("synthetic connectivity failure")

    monkeypatch.setattr(schematic_mod, "build_connectivity_groups", _raise_connectivity)
    verified = json.loads(
        await call_tool_text(server, "sch_verify_plan", {"plan_id": planned["plan_id"]})
    )

    _expect_equal(verified["unconnected_labels"], [])
    _expect_equal(verified["connectivity_error"], "synthetic connectivity failure")
    _expect_equal(verified["connectivity"], "fail")


@pytest.mark.anyio
async def test_verify_plan_does_not_accept_same_label_at_wrong_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.server import create_server
    from kicad_mcp.tools import schematic as schematic_mod
    from tests.conftest import call_tool_text

    (tmp_path / "test.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "test.kicad_pcb").write_text("", encoding="utf-8")
    (tmp_path / "test.kicad_sch").write_text(MINIMAL_SCH, encoding="utf-8")

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(tmp_path)})
    spec = {"title": "positioned", "labels": [{"text": "NET1", "x": 50, "y": 40}]}
    planned = json.loads(
        await call_tool_text(server, "sch_plan_from_spec", {"spec_json": json.dumps(spec)})
    )
    await call_tool_text(server, "sch_apply_plan", {"plan_id": planned["plan_id"]})

    monkeypatch.setattr(
        schematic_mod,
        "parse_schematic_file",
        lambda _path: {
            "labels": [{"name": "NET1", "x": 60.0, "y": 40.0}],
            "symbols": [],
        },
    )
    monkeypatch.setattr(
        schematic_mod,
        "build_connectivity_groups",
        lambda _path: [
            {
                "names": ["NET1"],
                "points": [(60.0, 40.0), (70.0, 40.0)],
                "pins": [],
            }
        ],
    )

    verified = json.loads(
        await call_tool_text(server, "sch_verify_plan", {"plan_id": planned["plan_id"]})
    )

    _expect_equal(verified["missing_labels"], ["NET1"])
    _expect_equal(verified["unconnected_labels"], [])
    _expect_equal(verified["connectivity_error"], None)
    _expect_equal(verified["connectivity"], "fail")
