from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from kicad_mcp.models.state import (
    AgentRunState,
    BoardState,
    CapabilityState,
    ManufacturingState,
    ProjectState,
    SchematicState,
    VerificationState,
    WorkspaceState,
)


def test_workspace_state_defaults_are_serializable() -> None:
    state = WorkspaceState()
    payload = json.loads(state.model_dump_json())

    assert payload["profile"] == "minimal"
    assert payload["ipc_available"] is False
    assert payload["cli_available"] is False
    assert payload["timestamp"]


def test_schematic_state_from_path_hashes_content(tmp_path) -> None:
    path = tmp_path / "demo.kicad_sch"
    content = b"(kicad_sch (version 20231120))"
    path.write_bytes(content)

    state = SchematicState.from_path(path)

    assert state.sch_path == str(path)
    assert state.content_hash == hashlib.sha256(content).hexdigest()


def test_schematic_state_from_missing_path_has_no_hash(tmp_path) -> None:
    path = tmp_path / "missing.kicad_sch"

    state = SchematicState.from_path(path)

    assert state.sch_path == str(path)
    assert state.content_hash is None


def test_board_state_from_path_hashes_content(tmp_path) -> None:
    path = tmp_path / "demo.kicad_pcb"
    content = b"(kicad_pcb)"
    path.write_bytes(content)

    state = BoardState.from_path(path)

    assert state.pcb_path == str(path)
    assert state.content_hash == hashlib.sha256(content).hexdigest()


def test_board_state_from_missing_path_has_no_hash(tmp_path) -> None:
    path = tmp_path / "missing.kicad_pcb"

    state = BoardState.from_path(path)

    assert state.pcb_path == str(path)
    assert state.content_hash is None


def test_project_state_content_fingerprint_is_deterministic() -> None:
    schematic = SchematicState(sch_path="a.kicad_sch", content_hash="b" * 64)
    board = BoardState(pcb_path="a.kicad_pcb", content_hash="a" * 64)
    first = ProjectState(schematic=schematic, board=board)
    second = ProjectState(schematic=schematic, board=board)

    assert first.content_fingerprint() == second.content_fingerprint()
    assert (
        first.content_fingerprint() == hashlib.sha256(f"{'a' * 64}|{'b' * 64}".encode()).hexdigest()
    )


def test_project_state_empty_fingerprint_is_sha256_of_empty_string() -> None:
    state = ProjectState()

    assert state.content_fingerprint() == hashlib.sha256(b"").hexdigest()


def test_agent_run_state_records_tools_and_summarizes() -> None:
    run = AgentRunState()

    run.record_tool_call("sch_add_symbol")
    run.journal_entries.append("entry-1")
    run.current_phase = "edit"
    run.warning_count = 1

    summary = run.to_summary()
    assert summary["run_id"] == run.run_id
    assert summary["tool_calls_count"] == 1
    assert summary["journal_entries_count"] == 1
    assert summary["current_phase"] == "edit"
    assert summary["warning_count"] == 1


def test_snapshot_models_are_frozen() -> None:
    state = WorkspaceState(profile="minimal")

    with pytest.raises(ValidationError):
        state.profile = "agent_full"


def test_runtime_state_is_mutable() -> None:
    state = AgentRunState(current_phase="init")

    state.current_phase = "validate"

    assert state.current_phase == "validate"


def test_auxiliary_state_models_construct() -> None:
    manufacturing = ManufacturingState(
        output_dir="out",
        gerber_count=2,
        drill_files=["demo.drl"],
        approved_by="operator",
    )
    verification = VerificationState(gate_passed=True, erc_errors=0, drc_errors=0)
    capability = CapabilityState(
        kicad_cli_path="/usr/bin/kicad-cli",
        kicad_cli_version="10.0.0",
    )

    assert manufacturing.gerber_count == 2
    assert verification.gate_passed is True
    assert capability.profile == "minimal"
