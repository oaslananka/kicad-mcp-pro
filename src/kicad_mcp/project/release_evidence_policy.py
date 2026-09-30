"""Release-evidence policy for HardwareIntentContract v1.

This pure-domain gate never turns metadata presence into engineering approval.
A release-blocking contract requires either fresh exact-revision engineering
proof or an explicit exact-revision waiver whose own approval evidence is fresh.
Unknown or stale proof fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
    EvidenceRecordKind,
    FreshnessAssessment,
)
from .hardware_intent_contract import HardwareIntentContract


class ContractReleaseEvidenceState(StrEnum):
    SATISFIED = "satisfied"
    WAIVED = "waived"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ContractReleaseEvidenceResult:
    contract_id: str
    contract_version: int
    state: ContractReleaseEvidenceState
    evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceGateResult:
    approved: bool
    contracts: tuple[ContractReleaseEvidenceResult, ...]

    @property
    def blocking(self) -> tuple[ContractReleaseEvidenceResult, ...]:
        return tuple(
            result
            for result in self.contracts
            if result.state is ContractReleaseEvidenceState.BLOCKED
        )

    @property
    def waived(self) -> tuple[ContractReleaseEvidenceResult, ...]:
        return tuple(
            result
            for result in self.contracts
            if result.state is ContractReleaseEvidenceState.WAIVED
        )


_ENGINEERING_PROOF_KINDS = frozenset(
    {
        EvidenceRecordKind.ARTIFACT,
        EvidenceRecordKind.VERIFICATION_RUN,
        EvidenceRecordKind.MEASUREMENT,
    }
)
_WAIVER_PROOF_KINDS = frozenset(
    {
        EvidenceRecordKind.APPROVAL,
        EvidenceRecordKind.WAIVER,
    }
)


def _unique_by_id(
    records: tuple[EvidenceRecord, ...],
    assessments: tuple[FreshnessAssessment, ...],
) -> tuple[dict[str, EvidenceRecord], dict[str, FreshnessAssessment]]:
    record_map: dict[str, EvidenceRecord] = {}
    for record in records:
        if record.evidence_id in record_map:
            raise ValueError(f"duplicate evidence ID: {record.evidence_id}")
        record_map[record.evidence_id] = record

    assessment_map: dict[str, FreshnessAssessment] = {}
    for assessment in assessments:
        if assessment.evidence_id in assessment_map:
            raise ValueError(f"duplicate freshness assessment: {assessment.evidence_id}")
        assessment_map[assessment.evidence_id] = assessment
    return record_map, assessment_map


def _freshness(
    evidence_id: str,
    assessments: dict[str, FreshnessAssessment],
) -> EvidenceFreshnessState:
    assessment = assessments.get(evidence_id)
    if assessment is None:
        return EvidenceFreshnessState.REQUIRES_RECHECK
    return assessment.state


def _bound_to_contract(
    record: EvidenceRecord,
    contract: HardwareIntentContract,
) -> bool:
    return (record.contract_id, record.contract_version) == (
        contract.contract_id,
        contract.contract_version,
    )


def _valid_waiver_evidence(
    contract: HardwareIntentContract,
    *,
    record_map: dict[str, EvidenceRecord],
    assessment_map: dict[str, FreshnessAssessment],
) -> tuple[str, ...]:
    valid: list[str] = []
    for waiver in contract.waivers:
        record = record_map.get(waiver.approval_evidence_ref)
        if record is None:
            continue
        if record.kind not in _WAIVER_PROOF_KINDS:
            continue
        if not _bound_to_contract(record, contract):
            continue
        if _freshness(record.evidence_id, assessment_map) is not EvidenceFreshnessState.STILL_VALID:
            continue
        valid.append(record.evidence_id)
    return tuple(sorted(valid))


def _blocking_reasons(
    proof_records: tuple[EvidenceRecord, ...],
    *,
    assessment_map: dict[str, FreshnessAssessment],
    has_declared_waiver: bool,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if not proof_records:
        reasons.add("required_evidence_missing")
    states = {_freshness(record.evidence_id, assessment_map) for record in proof_records}
    if EvidenceFreshnessState.INVALIDATED in states:
        reasons.add("required_evidence_invalidated")
    if EvidenceFreshnessState.REQUIRES_RECHECK in states:
        reasons.add("required_evidence_requires_recheck")
    if has_declared_waiver:
        reasons.add("waiver_approval_evidence_missing_or_stale")
    return tuple(sorted(reasons))


def evaluate_release_evidence(
    contracts: tuple[HardwareIntentContract, ...],
    records: tuple[EvidenceRecord, ...],
    assessments: tuple[FreshnessAssessment, ...],
) -> ReleaseEvidenceGateResult:
    """Evaluate exact-revision evidence for explicitly release-blocking contracts."""
    record_map, assessment_map = _unique_by_id(records, assessments)

    contract_keys: set[tuple[str, int]] = set()
    results: list[ContractReleaseEvidenceResult] = []
    for contract in sorted(contracts, key=lambda item: (item.contract_id, item.contract_version)):
        key = (contract.contract_id, contract.contract_version)
        if key in contract_keys:
            identity = f"{contract.contract_id}@{contract.contract_version}"
            raise ValueError(f"duplicate contract revision in release batch: {identity}")
        contract_keys.add(key)
        if not contract.release_blocking:
            continue

        proof_records = tuple(
            sorted(
                (
                    record
                    for record in records
                    if record.kind in _ENGINEERING_PROOF_KINDS
                    and _bound_to_contract(record, contract)
                ),
                key=lambda item: item.evidence_id,
            )
        )
        fresh_proof = tuple(
            record.evidence_id
            for record in proof_records
            if _freshness(record.evidence_id, assessment_map) is EvidenceFreshnessState.STILL_VALID
        )
        if fresh_proof:
            results.append(
                ContractReleaseEvidenceResult(
                    contract_id=contract.contract_id,
                    contract_version=contract.contract_version,
                    state=ContractReleaseEvidenceState.SATISFIED,
                    evidence_ids=fresh_proof,
                )
            )
            continue

        waiver_evidence = _valid_waiver_evidence(
            contract,
            record_map=record_map,
            assessment_map=assessment_map,
        )
        if waiver_evidence:
            results.append(
                ContractReleaseEvidenceResult(
                    contract_id=contract.contract_id,
                    contract_version=contract.contract_version,
                    state=ContractReleaseEvidenceState.WAIVED,
                    evidence_ids=waiver_evidence,
                    reason_codes=("explicit_reviewed_waiver",),
                )
            )
            continue

        results.append(
            ContractReleaseEvidenceResult(
                contract_id=contract.contract_id,
                contract_version=contract.contract_version,
                state=ContractReleaseEvidenceState.BLOCKED,
                evidence_ids=tuple(record.evidence_id for record in proof_records),
                reason_codes=_blocking_reasons(
                    proof_records,
                    assessment_map=assessment_map,
                    has_declared_waiver=bool(contract.waivers),
                ),
            )
        )

    ordered = tuple(results)
    return ReleaseEvidenceGateResult(
        approved=not any(
            result.state is ContractReleaseEvidenceState.BLOCKED for result in ordered
        ),
        contracts=ordered,
    )
