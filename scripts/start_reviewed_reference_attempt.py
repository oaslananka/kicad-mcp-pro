#!/usr/bin/env python3
"""Operator-gated, non-retry initial schematic benchmark phase invocation.

Uses the existing preflight and exact reviewed Claude phase runner. This
creates only a private phase receipt, not a scored attempt or success claim.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kicad_mcp.evals.reference_agent_runner import ReferenceAgentWorkspace
from kicad_mcp.evals.reference_corpus import _parse_agent_log
from scripts.check_reference_board_attempt_readiness import BOARD_IDS, ROOT, preflight

_SCHEMA = "reference-initial-phase-execution.v1"
_RECEIPT = "schematic-execution-receipt.json"


def _invoke_existing_runner(argv: list[str]) -> int:
    from scripts.run_reference_board_agent import main

    return main(argv)


def _render(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n"


def _result(
    status: str, *, reason_codes: list[str] | None = None, attempt_id: str | None = None
) -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA,
        "status": status,
        "attempt_id": attempt_id,
        "reason_codes": sorted(reason_codes or []),
        "counts_as_task_success": False,
        "published_attempt_record": False,
    }


def _safe_scratch_path(root: Path, workspace: ReferenceAgentWorkspace) -> bool:
    """Block symlink escapes even for previously-created parent directories."""
    parts = (
        root / ".dev-tools",
        root / ".dev-tools/reference-agent-runs",
        root / ".dev-tools/reference-agent-runs" / workspace.board_id,
        workspace.scratch_dir.parent,
        workspace.scratch_dir,
    )
    return not any(path.is_symlink() for path in parts)


def start_reviewed_attempt(
    *,
    root: Path,
    board_id: str,
    attempt_number: int,
    execute: bool,
    cost_acknowledged: bool,
    runner: Callable[[list[str]], int] = _invoke_existing_runner,
) -> dict[str, Any]:
    """Plan, or reserve and start exactly one *initial schematic* phase."""
    try:
        checked = preflight(
            root=root, board_id=board_id, attempt_number=attempt_number, phase_name="schematic"
        )
        workspace = ReferenceAgentWorkspace.for_reviewed_attempt(
            checkout_dir=root, board_id=board_id, attempt_number=attempt_number
        )
    except (OSError, ValueError):
        return _result("blocked", reason_codes=["invalid_reviewed_attempt"])

    if checked["status"] != "ready":
        return _result(
            "blocked", reason_codes=checked["blocking_reasons"], attempt_id=workspace.attempt_id
        )
    if not execute:
        return _result("ready_for_explicit_execution", attempt_id=workspace.attempt_id)
    if not cost_acknowledged:
        return _result(
            "blocked",
            reason_codes=["operator_cost_acknowledgement_required"],
            attempt_id=workspace.attempt_id,
        )
    if not _safe_scratch_path(root.resolve(), workspace):
        return _result(
            "blocked", reason_codes=["unsafe_scratch_path"], attempt_id=workspace.attempt_id
        )
    # mkdir with exist_ok=False is the reservation. Two operators attempting
    # the same ID must never both start a paid/mutating agent session.
    try:
        workspace.scratch_dir.parent.mkdir(parents=True, exist_ok=True)
        workspace.scratch_dir.mkdir(exist_ok=False)
    except FileExistsError:
        return _result(
            "blocked",
            reason_codes=["attempt_identity_already_used"],
            attempt_id=workspace.attempt_id,
        )
    except OSError:
        return _result(
            "blocked",
            reason_codes=["workspace_reservation_failed"],
            attempt_id=workspace.attempt_id,
        )

    receipt = workspace.scratch_dir / _RECEIPT
    evidence = {
        "schema_version": _SCHEMA,
        "board_id": board_id,
        "benchmark_version": "v1",
        "attempt_id": workspace.attempt_id,
        "phase": "schematic",
        "source_revision": checked["source_revision"],
        "reviewed_input_sha256": checked["reviewed_input_sha256"],
        "started_at": datetime.now(UTC).isoformat(),
        "state": "started",
        "counts_as_task_success": False,
        "published_attempt_record": False,
    }
    # If interrupted, the started receipt remains on disk; reruns refuse the
    # reserved attempt ID. No automatic retry for possibly-mutating sessions.
    try:
        with receipt.open("x", encoding="utf-8") as handle:
            handle.write(_render(evidence))
    except OSError:
        return _result(
            "blocked",
            reason_codes=["receipt_reservation_failed"],
            attempt_id=workspace.attempt_id,
        )
    state = "executor_failed"
    try:
        # The existing executor prints its own sanitized summary. Suppress
        # intermediate messages and raw exception content to keep this public
        # wrapper's output strictly bounded and safe.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exit_code = runner(
                [
                    "--board-id",
                    board_id,
                    "--attempt-number",
                    str(attempt_number),
                    "--phase",
                    "schematic",
                ]
            )
        if exit_code == 0:
            # Validate the publication-safe event sequence, not merely the
            # existence of a log that an interrupted runner might have left.
            _parse_agent_log(workspace.agent_log_path, workspace.attempt_id)
            state = "executor_returned_success_with_log"
    except Exception:
        # No exception or provider error text is placed in the public receipt.
        state = "executor_failed"
    evidence["state"] = state
    evidence["ended_at"] = datetime.now(UTC).isoformat()
    tmp_receipt = workspace.scratch_dir / (_RECEIPT + ".pending")
    try:
        with tmp_receipt.open("x", encoding="utf-8") as handle:
            handle.write(_render(evidence))
        os.replace(tmp_receipt, receipt)
    except OSError:
        # Leave the original 'started' reservation in place for human recovery.
        return _result(
            "needs_manual_review",
            reason_codes=["phase_receipt_finalize_failed"],
            attempt_id=workspace.attempt_id,
        )
    if state == "executor_returned_success_with_log":
        return _result("phase_finished_needs_evidence_review", attempt_id=workspace.attempt_id)
    return _result(
        "phase_failed_needs_evidence_review",
        reason_codes=["executor_failed"],
        attempt_id=workspace.attempt_id,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", choices=BOARD_IDS, required=True)
    parser.add_argument("--attempt-number", type=int, choices=range(1, 1000), required=True)
    parser.add_argument(
        "--execute", action="store_true", help="Run one provider session with a private reservation"
    )
    parser.add_argument(
        "--acknowledge-provider-cost",
        action="store_true",
        help="Explicit human approval for paid/mutating agent execution",
    )
    args = parser.parse_args(argv)
    report = start_reviewed_attempt(
        root=ROOT,
        board_id=args.board_id,
        attempt_number=args.attempt_number,
        execute=args.execute,
        cost_acknowledged=args.acknowledge_provider_cost,
    )
    print(_render(report), end="")
    return (
        0
        if report["status"]
        in {"ready_for_explicit_execution", "phase_finished_needs_evidence_review"}
        else 2
    )


if __name__ == "__main__":
    sys.exit(main())
