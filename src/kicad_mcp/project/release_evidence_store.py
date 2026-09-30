"""Versioned project-local release evidence sidecars for #942.

The store is metadata only. It never authenticates native truth. Until a trusted
current-state resolver supplies exact freshness assessments, persisted evidence
records are conservatively classified as requires_recheck.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..ir.engineering_graph import EngineeringGraph
from .evidence_current_state import assess_evidence_current_state, graph_entity_hashes
from .evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
    FreshnessAssessment,
    InvalidationReason,
)
from .hardware_intent_contract import HardwareIntentContract, StrictContractModel
from .release_evidence_policy import ReleaseEvidenceGateResult, evaluate_release_evidence

RELEASE_EVIDENCE_DIRNAME = ".kicad-mcp"
HARDWARE_INTENT_STORE_FILENAME = "hardware_intent_contracts-v1.json"
EVIDENCE_RECORD_STORE_FILENAME = "evidence_records-v1.json"


class HardwareIntentContractStore(StrictContractModel):
    schema_version: Literal[1]
    contracts: tuple[HardwareIntentContract, ...] = ()


class EvidenceRecordStore(StrictContractModel):
    schema_version: Literal[1]
    records: tuple[EvidenceRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectReleaseEvidenceResolution:
    adopted: bool
    gate: ReleaseEvidenceGateResult | None = None
    errors: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        if self.errors:
            return False
        if not self.adopted:
            return True
        return self.gate is not None and self.gate.approved


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _contracts_path(project_dir: Path) -> Path:
    return project_dir / RELEASE_EVIDENCE_DIRNAME / HARDWARE_INTENT_STORE_FILENAME


def _evidence_path(project_dir: Path) -> Path:
    return project_dir / RELEASE_EVIDENCE_DIRNAME / EVIDENCE_RECORD_STORE_FILENAME


def load_hardware_intent_contracts(project_dir: Path) -> tuple[HardwareIntentContract, ...]:
    path = _contracts_path(project_dir)
    if not path.is_file():
        return ()
    payload = HardwareIntentContractStore.model_validate(_load_json(path))
    return payload.contracts


def load_evidence_records(project_dir: Path) -> tuple[EvidenceRecord, ...]:
    path = _evidence_path(project_dir)
    if not path.is_file():
        return ()
    payload = EvidenceRecordStore.model_validate(_load_json(path))
    return payload.records


def unresolved_current_state_assessments(
    records: tuple[EvidenceRecord, ...],
) -> tuple[FreshnessAssessment, ...]:
    """Fail closed until a trusted current Engineering Graph/hash resolver is supplied."""
    return tuple(
        FreshnessAssessment(
            evidence_id=record.evidence_id,
            state=EvidenceFreshnessState.REQUIRES_RECHECK,
            reasons=(
                InvalidationReason(
                    code="current_native_dependency_hashes_not_resolved",
                    entity_id="",
                ),
            ),
        )
        for record in records
    )


def resolve_project_release_evidence(
    project_dir: Path,
    *,
    current_graph: EngineeringGraph | None = None,
    current_source_sha256: str | None = None,
) -> ProjectReleaseEvidenceResolution:
    """Load v1 metadata; only trusted current graph/source inputs can establish freshness."""
    contract_path = _contracts_path(project_dir)
    if not contract_path.is_file():
        return ProjectReleaseEvidenceResolution(adopted=False)

    try:
        contracts = load_hardware_intent_contracts(project_dir)
    except (OSError, ValueError) as exc:
        return ProjectReleaseEvidenceResolution(
            adopted=True,
            errors=(f"hardware_intent_contract_store_invalid: {exc}",),
        )

    if not any(contract.release_blocking for contract in contracts):
        return ProjectReleaseEvidenceResolution(
            adopted=True,
            gate=evaluate_release_evidence(contracts, (), ()),
        )

    try:
        records = load_evidence_records(project_dir)
    except (OSError, ValueError) as exc:
        return ProjectReleaseEvidenceResolution(
            adopted=True,
            errors=(f"evidence_record_store_invalid: {exc}",),
        )

    if current_graph is not None:
        dependency_ids = tuple(entry.entity_id for record in records for entry in record.inputs)
        current_hashes, _missing = graph_entity_hashes(current_graph, dependency_ids)
        assessments = tuple(
            assess_evidence_current_state(
                record,
                graph=current_graph,
                current_source_sha256=current_source_sha256,
                current_hashes=current_hashes,
            )
            for record in records
        )
    else:
        assessments = unresolved_current_state_assessments(records)
    gate = evaluate_release_evidence(contracts, records, assessments)
    return ProjectReleaseEvidenceResolution(adopted=True, gate=gate)
