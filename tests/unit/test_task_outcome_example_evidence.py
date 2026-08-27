from __future__ import annotations

import json
from pathlib import Path

import kicad_mcp.evals as evals

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "task-outcomes" / "2026-08-28-native-live-example"


def test_committed_native_live_example_is_deterministic_and_insufficient() -> None:
    contract = evals.parse_benchmark_contract(
        json.loads((EVIDENCE / "contract.json").read_text(encoding="utf-8"))
    )
    attempt = evals.parse_attempt_record(
        json.loads((EVIDENCE / "attempt.json").read_text(encoding="utf-8"))
    )
    summary = evals.aggregate_task_outcomes(contract, [attempt])

    assert (EVIDENCE / "summary.json").read_text(
        encoding="utf-8"
    ) == evals.render_task_outcome_summary_json(summary)
    assert (EVIDENCE / "summary.txt").read_text(
        encoding="utf-8"
    ) == evals.render_task_outcome_summary_text(summary)

    assert summary.task_success.status == "insufficient_evidence"
    assert summary.mutation_recovery.status == "insufficient_evidence"
    assert summary.file_corruption_status == "insufficient_evidence"
    assert summary.required_drc_execution.status == "insufficient_evidence"
    assert summary.manufacturing_reproducibility.status == "insufficient_evidence"
    assert summary.mutation_attempts == 2
    assert summary.recovery_required_mutations == 1
    assert summary.successful_recoveries == 1
    assert summary.duplicate_application_incidents == 0
    assert summary.state_divergence_incidents == 0
    assert summary.file_corruption_incidents == 0


def test_committed_example_contains_no_private_runtime_identity() -> None:
    rendered = "\n".join(
        (EVIDENCE / name).read_text(encoding="utf-8")
        for name in ("contract.json", "attempt.json", "summary.json", "summary.txt", "README.md")
    )
    lowered = rendered.casefold()

    assert "/home/" not in lowered
    assert "c:\\users\\" not in lowered
    assert "private/workspaces" not in lowered
    assert "board_fingerprint" not in lowered
    assert "fixture.kicad_pcb" not in lowered
