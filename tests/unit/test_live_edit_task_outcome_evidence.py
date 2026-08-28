from __future__ import annotations

import json

import pytest

from kicad_mcp.evals.live_edit_evidence import mutation_evidence_from_live_edit
from kicad_mcp.pcb.live_edit_evidence import LiveEditEvidence, LiveMutationReceipt


def _evidence(*receipts: LiveMutationReceipt) -> LiveEditEvidence:
    return LiveEditEvidence(
        schema_version="pcb-live-edit-session.v1",
        board_fingerprint="f" * 64,
        board_name="demo.kicad_pcb",
        outcome="committed",
        mutations=receipts,
    )


def _receipt(**overrides: object) -> LiveMutationReceipt:
    payload: dict[str, object] = {
        "mutation_id": "live-mutation-1",
        "operation": "pcb_add_track",
        "execution_state": "completed",
        "recovery_required": False,
        "recovery_succeeded": None,
        "duplicate_application_detected": False,
        "state_divergence_detected": False,
        "corruption_detected": False,
        "final_state_verified": True,
    }
    payload.update(overrides)
    return LiveMutationReceipt(**payload)  # type: ignore[arg-type]


def test_committed_verified_mutation_maps_without_recovery() -> None:
    mapped = mutation_evidence_from_live_edit(_evidence(_receipt()))

    assert len(mapped) == 1
    mutation = mapped[0]
    assert mutation.mutation_id == "live-mutation-1"
    assert mutation.attempted is True
    assert mutation.execution_state == "completed"
    assert mutation.recovery_required is False
    assert mutation.recovery_succeeded is None
    assert mutation.final_state_verified is True


def test_interrupted_mutation_preserves_successful_recovery() -> None:
    mapped = mutation_evidence_from_live_edit(
        _evidence(
            _receipt(
                execution_state="interrupted",
                recovery_required=True,
                recovery_succeeded=True,
                final_state_verified=True,
            )
        )
    )

    mutation = mapped[0]
    assert mutation.execution_state == "interrupted"
    assert mutation.recovery_required is True
    assert mutation.recovery_succeeded is True
    assert mutation.final_state_verified is True


def test_unproven_recovery_remains_failed_evidence() -> None:
    mapped = mutation_evidence_from_live_edit(
        _evidence(
            _receipt(
                execution_state="interrupted",
                recovery_required=True,
                recovery_succeeded=False,
                final_state_verified=False,
            )
        )
    )

    mutation = mapped[0]
    assert mutation.recovery_required is True
    assert mutation.recovery_succeeded is False
    assert mutation.final_state_verified is False


@pytest.mark.parametrize(
    "field",
    [
        "duplicate_application_detected",
        "state_divergence_detected",
        "corruption_detected",
    ],
)
def test_integrity_incidents_are_mapped_verbatim(field: str) -> None:
    receipt = _receipt(**{field: True, "final_state_verified": False})

    mutation = mutation_evidence_from_live_edit(_evidence(receipt))[0]

    assert getattr(mutation, field) is True
    assert mutation.final_state_verified is False


def test_mapping_is_deterministic_and_drops_board_identity() -> None:
    evidence = LiveEditEvidence(
        schema_version="pcb-live-edit-session.v1",
        board_fingerprint="a" * 64,
        board_name="private-customer-board.kicad_pcb",
        outcome="committed",
        mutations=(_receipt(),),
    )

    first = mutation_evidence_from_live_edit(evidence)
    second = mutation_evidence_from_live_edit(evidence)
    rendered = json.dumps([item.model_dump(mode="json") for item in first], sort_keys=True)

    assert first == second
    assert "private-customer-board" not in rendered
    assert "a" * 64 not in rendered
    assert "pcb_add_track" not in rendered
