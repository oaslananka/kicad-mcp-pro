from __future__ import annotations

from kicad_mcp.pcb.live_edit_evidence import LiveEditEvidence, LiveMutationReceipt


def test_runtime_evidence_is_path_free_and_immutable() -> None:
    receipt = LiveMutationReceipt(
        mutation_id="m1",
        operation="pcb_add_track",
        execution_state="completed",
        recovery_required=False,
        recovery_succeeded=None,
        duplicate_application_detected=False,
        state_divergence_detected=False,
        corruption_detected=False,
        final_state_verified=True,
    )
    evidence = LiveEditEvidence(
        schema_version="pcb-live-edit-session.v1",
        board_fingerprint="a" * 64,
        board_name="demo.kicad_pcb",
        outcome="committed",
        mutations=(receipt,),
    )

    assert evidence.board_fingerprint == "a" * 64
    assert evidence.mutations == (receipt,)
    assert "/home/" not in repr(evidence)
