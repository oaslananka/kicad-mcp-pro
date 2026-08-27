"""Regression tests for publishable evaluation evidence sanitization."""

from __future__ import annotations

import pytest

from kicad_mcp.evals.evidence_sanitization import (
    EvidenceSanitizationError,
    validate_sanitized_evidence,
)


def test_task_outcome_summary_schema_name_is_not_misclassified_as_secret() -> None:
    validate_sanitized_evidence({"schema_version": "pcb-task-outcome-summary.v1"})


@pytest.mark.parametrize(
    "value",
    [
        "sk-" + "x" * 16,
        "token=" + "sk-" + "x" * 16,
        "Bearer " + "x" * 16,
    ],
)
def test_real_secret_shapes_remain_rejected(value: str) -> None:
    with pytest.raises(EvidenceSanitizationError, match="sensitive string"):
        validate_sanitized_evidence({"value": value})
