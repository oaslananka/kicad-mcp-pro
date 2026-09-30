"""Release-blocking evidence policy for #942."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kicad_mcp.project.evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
    FreshnessAssessment,
)
from kicad_mcp.project.hardware_intent_contract import HardwareIntentContract
from kicad_mcp.project.release_evidence_policy import (
    ContractReleaseEvidenceState,
    evaluate_release_evidence,
)

H = "a" * 64


def _contract(
    *,
    contract_id: str = "INTENT-USB-SI",
    version: int = 1,
    release_blocking: bool = True,
    waivers: list[dict[str, object]] | None = None,
) -> HardwareIntentContract:
    return HardwareIntentContract.model_validate(
        {
            "schema_version": 1,
            "contract_id": contract_id,
            "contract_version": version,
            "requirement_id": f"REQ-{contract_id}",
            "applicability": {"kind": "net", "key": "USB_DP"},
            "severity": "blocking" if release_blocking else "warning",
            "release_blocking": release_blocking,
            "verification": [{"method_ref": "native-check", "evidence_classes": ["drc"]}],
            "quantity_range": {
                "maximum": {"value": "90", "unit": "ohm"},
            },
            "waivers": waivers or [],
        }
    )


def _record(
    evidence_id: str = "EVID-USB-1",
    *,
    kind: str = "evidence_artifact",
    contract_id: str = "INTENT-USB-SI",
    version: int = 1,
) -> EvidenceRecord:
    return EvidenceRecord.model_validate(
        {
            "schema_version": 1,
            "evidence_id": evidence_id,
            "kind": kind,
            "project_key": "fixture",
            "source_revision": "rev-1",
            "source_sha256": H,
            "producer": "native-check",
            "producer_version": "10.0.3",
            "captured_at": datetime(2026, 9, 30, 15, 0, tzinfo=UTC),
            "dependency_manifest_complete": True,
            "inputs": [{"entity_id": "fixture:net:USB_DP", "sha256": H}],
            "contract_id": contract_id,
            "contract_version": version,
            "provenance_source": "fixture-native-result",
        }
    )


def _assessment(
    evidence_id: str = "EVID-USB-1",
    state: EvidenceFreshnessState = EvidenceFreshnessState.STILL_VALID,
) -> FreshnessAssessment:
    return FreshnessAssessment(evidence_id=evidence_id, state=state)


def test_fresh_exact_revision_evidence_allows_release_contract() -> None:
    result = evaluate_release_evidence((_contract(),), (_record(),), (_assessment(),))
    assert result.approved
    assert result.blocking == ()
    assert result.contracts[0].state is ContractReleaseEvidenceState.SATISFIED


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (EvidenceFreshnessState.INVALIDATED, "required_evidence_invalidated"),
        (EvidenceFreshnessState.REQUIRES_RECHECK, "required_evidence_requires_recheck"),
    ],
)
def test_stale_or_unresolved_required_evidence_blocks(
    state: EvidenceFreshnessState, reason: str
) -> None:
    result = evaluate_release_evidence((_contract(),), (_record(),), (_assessment(state=state),))
    assert not result.approved
    assert result.blocking[0].reason_codes == (reason,)


def test_missing_evidence_or_missing_assessment_blocks() -> None:
    missing = evaluate_release_evidence((_contract(),), (), ())
    assert not missing.approved
    assert missing.blocking[0].reason_codes == ("required_evidence_missing",)

    unknown = evaluate_release_evidence((_contract(),), (_record(),), ())
    assert not unknown.approved
    assert unknown.blocking[0].reason_codes == ("required_evidence_requires_recheck",)


def test_exact_fresh_reviewed_waiver_can_override_stale_proof() -> None:
    waiver_id = "WAIVER-EVID-1"
    contract = _contract(
        waivers=[
            {
                "waiver_id": "WAIVER-1",
                "contract_id": "INTENT-USB-SI",
                "contract_version": 1,
                "reason": "Reviewed temporary lab exception",
                "approved_by": "hardware-lead",
                "approval_evidence_ref": waiver_id,
            }
        ]
    )
    proof = _record()
    waiver_record = _record(waiver_id, kind="waiver")
    result = evaluate_release_evidence(
        (contract,),
        (proof, waiver_record),
        (
            _assessment(state=EvidenceFreshnessState.INVALIDATED),
            _assessment(waiver_id),
        ),
    )
    assert result.approved
    assert result.waived[0].state is ContractReleaseEvidenceState.WAIVED
    assert result.waived[0].evidence_ids == (waiver_id,)


def test_stale_wrong_revision_or_unreferenced_approval_does_not_waive() -> None:
    waiver_id = "WAIVER-EVID-1"
    contract = _contract(
        waivers=[
            {
                "waiver_id": "WAIVER-1",
                "contract_id": "INTENT-USB-SI",
                "contract_version": 1,
                "reason": "Temporary exception",
                "approved_by": "hardware-lead",
                "approval_evidence_ref": waiver_id,
            }
        ]
    )
    stale = evaluate_release_evidence(
        (contract,),
        (_record(waiver_id, kind="waiver"),),
        (_assessment(waiver_id, EvidenceFreshnessState.REQUIRES_RECHECK),),
    )
    assert not stale.approved
    assert "waiver_approval_evidence_missing_or_stale" in stale.blocking[0].reason_codes

    wrong_revision = _record(waiver_id, kind="waiver", version=2)
    wrong = evaluate_release_evidence((contract,), (wrong_revision,), (_assessment(waiver_id),))
    assert not wrong.approved

    approval_only = _record("APPROVAL-1", kind="approval")
    unreferenced = evaluate_release_evidence(
        (contract,), (approval_only,), (_assessment("APPROVAL-1"),)
    )
    assert not unreferenced.approved


def test_nonblocking_contract_is_not_a_release_gate() -> None:
    result = evaluate_release_evidence((_contract(release_blocking=False),), (), ())
    assert result.approved
    assert result.contracts == ()


def test_exact_contract_revision_is_required() -> None:
    result = evaluate_release_evidence(
        (_contract(version=2),),
        (_record(version=1),),
        (_assessment(),),
    )
    assert not result.approved
    assert result.blocking[0].reason_codes == ("required_evidence_missing",)


def test_multiple_contracts_fail_if_any_release_blocker_is_unproven() -> None:
    a = _contract(contract_id="INTENT-A")
    b = _contract(contract_id="INTENT-B")
    proof_a = _record(contract_id="INTENT-A")
    result = evaluate_release_evidence((b, a), (proof_a,), (_assessment(),))
    assert not result.approved
    assert [item.contract_id for item in result.contracts] == ["INTENT-A", "INTENT-B"]
    assert result.contracts[0].state is ContractReleaseEvidenceState.SATISFIED
    assert result.contracts[1].state is ContractReleaseEvidenceState.BLOCKED


def test_duplicate_record_assessment_and_contract_revisions_fail_closed() -> None:
    contract = _contract()
    rec = _record()
    assessment = _assessment()
    contracts = (contract,)
    duplicate_records = (rec, rec)
    assessments = (assessment,)
    with pytest.raises(ValueError, match="duplicate evidence ID"):
        evaluate_release_evidence(contracts, duplicate_records, assessments)

    records = (rec,)
    duplicate_assessments = (assessment, assessment)
    with pytest.raises(ValueError, match="duplicate freshness assessment"):
        evaluate_release_evidence(contracts, records, duplicate_assessments)

    duplicate_contracts = (contract, contract)
    with pytest.raises(ValueError, match="duplicate contract revision"):
        evaluate_release_evidence(duplicate_contracts, records, assessments)


def test_non_waiver_record_cannot_satisfy_waiver_reference() -> None:
    waiver_id = "WAIVER-EVID-1"
    contract = _contract(
        waivers=[
            {
                "waiver_id": "WAIVER-1",
                "contract_id": "INTENT-USB-SI",
                "contract_version": 1,
                "reason": "Temporary exception",
                "approved_by": "hardware-lead",
                "approval_evidence_ref": waiver_id,
            }
        ]
    )
    artifact = _record(waiver_id, kind="evidence_artifact", version=2)
    result = evaluate_release_evidence((contract,), (artifact,), (_assessment(waiver_id),))
    assert not result.approved
    assert "waiver_approval_evidence_missing_or_stale" in result.blocking[0].reason_codes
