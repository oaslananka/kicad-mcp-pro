from __future__ import annotations

import json

from kicad_mcp.models.tool_result import ArtifactRef, StateDelta, ToolResult


def test_tool_result_defaults() -> None:
    result = ToolResult()

    assert result.ok is True
    assert result.changed is False
    assert result.dry_run is False
    assert result.warnings == []
    assert result.errors == []
    assert result.artifacts == []
    assert result.state_delta == StateDelta()
    assert result.call_id


def test_success_factory_sets_name_and_changed() -> None:
    result = ToolResult.success(
        "export_gerbers",
        changed=True,
        artifacts=[ArtifactRef(path="out/demo.gbr", kind="gerber")],
    )

    assert result.ok is True
    assert result.changed is True
    assert result.tool_name == "export_gerbers"
    assert result.artifacts[0].kind == "gerber"


def test_failure_factory_sets_error() -> None:
    result = ToolResult.failure("sch_add_symbol", "symbol not found")

    assert result.ok is False
    assert result.changed is False
    assert result.errors == ["symbol not found"]


def test_dry_run_factory_sets_summary() -> None:
    result = ToolResult.dry_run_result("sch_add_label", "would add label")

    assert result.ok is True
    assert result.changed is False
    assert result.dry_run is True
    assert result.state_delta.summary == "[DRY-RUN] would add label"


def test_add_warning_and_error_mutate_result() -> None:
    result = ToolResult.success("pcb_add_track")

    result.add_warning("retry recommended")
    result.add_error("failed validation")

    assert result.warnings == ["retry recommended"]
    assert result.errors == ["failed validation"]
    assert result.ok is False


def test_to_mcp_text_round_trips_as_json() -> None:
    rollback_ref = "rollback-reference"
    result = ToolResult.success(
        "export_bom",
        rollback_token=rollback_ref,
        state_delta=StateDelta(
            pre_fingerprint="pre",
            post_fingerprint="post",
            changed_files=["bom.csv"],
            summary="exported BOM",
        ),
    )

    payload = json.loads(result.to_mcp_text())

    assert payload["ok"] is True
    assert payload["tool_name"] == "export_bom"
    assert payload["rollback_token"] == rollback_ref
    assert payload["state_delta"]["changed_files"] == ["bom.csv"]
