"""Path-free runtime evidence for native live PCB editing sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LiveEditOutcome = Literal["committed", "dropped", "aborted", "recovery_required"]
MutationExecutionState = Literal["completed", "interrupted", "failed"]


@dataclass(frozen=True, slots=True)
class LiveBoardIdentity:
    """Internal/public identity pair for one active KiCad board."""

    board_name: str
    internal_key: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class LiveMutationReceipt:
    """Normalized runtime evidence for one attempted live mutation."""

    mutation_id: str
    operation: str
    execution_state: MutationExecutionState
    recovery_required: bool
    recovery_succeeded: bool | None
    duplicate_application_detected: bool
    state_divergence_detected: bool
    corruption_detected: bool
    final_state_verified: bool


@dataclass(frozen=True, slots=True)
class LiveEditEvidence:
    """Sanitized terminal evidence for one native-live transaction."""

    schema_version: Literal["pcb-live-edit-session.v1"]
    board_fingerprint: str
    board_name: str
    outcome: LiveEditOutcome
    mutations: tuple[LiveMutationReceipt, ...]


__all__ = [
    "LiveBoardIdentity",
    "LiveEditEvidence",
    "LiveEditOutcome",
    "LiveMutationReceipt",
    "MutationExecutionState",
]
