"""One-way adapter from native-live runtime evidence to task-outcome KPI evidence."""

from __future__ import annotations

from ..pcb.live_edit_evidence import LiveEditEvidence
from .task_outcomes import MutationEvidence


def mutation_evidence_from_live_edit(
    evidence: LiveEditEvidence,
) -> tuple[MutationEvidence, ...]:
    """Convert sanitized runtime mutation receipts into the canonical KPI schema."""
    return tuple(
        MutationEvidence(
            mutation_id=receipt.mutation_id,
            execution_state=receipt.execution_state,
            recovery_required=receipt.recovery_required,
            recovery_succeeded=receipt.recovery_succeeded,
            duplicate_application_detected=receipt.duplicate_application_detected,
            state_divergence_detected=receipt.state_divergence_detected,
            corruption_detected=receipt.corruption_detected,
            final_state_verified=receipt.final_state_verified,
        )
        for receipt in evidence.mutations
    )


__all__ = ["mutation_evidence_from_live_edit"]
