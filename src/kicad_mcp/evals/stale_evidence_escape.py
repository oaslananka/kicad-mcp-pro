"""Deterministic #942 stale-evidence escape regression corpus and report."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..ir.engineering_graph import (
    EngineeringGraph,
    GraphEdgeKind,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    GraphProvenanceKind,
    canonical_entity_id,
)
from ..project.evidence_freshness import (
    EvidenceFreshnessState,
    EvidenceRecord,
    FreshnessAssessment,
    assess_evidence_freshness,
    attach_evidence_record,
    evidence_graph_id,
)
from ..project.hardware_intent_contract import HardwareIntentContract, StrictContractModel
from ..project.release_evidence_policy import (
    ContractReleaseEvidenceState,
    evaluate_release_evidence,
)

STALE_EVIDENCE_ESCAPE_SCHEMA_VERSION = 1
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
STALE_EVIDENCE_ESCAPE_CORPUS_PATH = (
    _REPOSITORY_ROOT / "evals/evidence_freshness/stale_escape_cases.json"
)
_REFERENCE_PROJECT = "usb-layout-fixture"
_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_D = "d" * 64
_E = "e" * 64


class StaleEvidenceScenario(StrEnum):
    UNRELATED_COMPONENT_EDIT = "unrelated_component_edit"
    USB_ENTITY_EDIT = "usb_entity_edit"
    STACKUP_ENTITY_EDIT = "stackup_entity_edit"
    CONTRACT_ENTITY_EDIT = "contract_entity_edit"
    USB_HASH_CHANGE = "usb_hash_change"
    UNKNOWN_MUTATION_SCOPE = "unknown_mutation_scope"
    MISSING_STACKUP_HASH = "missing_stackup_hash"
    MISSING_FRESHNESS_ASSESSMENT = "missing_freshness_assessment"
    DEPENDENCY_EDGE_REMOVED = "dependency_edge_removed"
    TAMPERED_EVIDENCE_RECORD = "tampered_evidence_record"
    FRESH_REVIEWED_WAIVER = "fresh_reviewed_waiver"
    STALE_REVIEWED_WAIVER = "stale_reviewed_waiver"


class StaleEvidenceEscapeCase(StrictContractModel):
    case_id: str = Field(min_length=1, max_length=128)
    scenario: StaleEvidenceScenario
    must_block: bool
    expected_primary_freshness: EvidenceFreshnessState
    expected_waiver_freshness: EvidenceFreshnessState | None = None
    expected_release_state: ContractReleaseEvidenceState
    expected_reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_expectations(self) -> StaleEvidenceEscapeCase:
        needs_waiver = self.scenario in {
            StaleEvidenceScenario.FRESH_REVIEWED_WAIVER,
            StaleEvidenceScenario.STALE_REVIEWED_WAIVER,
        }
        if needs_waiver != (self.expected_waiver_freshness is not None):
            raise ValueError("waiver scenarios require expected_waiver_freshness")
        if self.must_block != (self.expected_release_state is ContractReleaseEvidenceState.BLOCKED):
            raise ValueError("must_block must match blocked expected release state")
        return self


class StaleEvidenceEscapeCorpus(StrictContractModel):
    schema_version: Literal[1]
    target_escape_rate: float = Field(ge=0.0, le=1.0)
    cases: tuple[StaleEvidenceEscapeCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cases(self) -> StaleEvidenceEscapeCorpus:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("duplicate stale-evidence escape case ID")
        if not any(case.must_block for case in self.cases):
            raise ValueError("corpus requires at least one must-block case")
        return self


class StaleEvidenceEscapeCaseResult(StrictContractModel):
    case_id: str
    scenario: StaleEvidenceScenario
    must_block: bool
    primary_freshness: EvidenceFreshnessState
    waiver_freshness: EvidenceFreshnessState | None = None
    release_approved: bool
    release_state: ContractReleaseEvidenceState
    reason_codes: tuple[str, ...] = ()
    escaped: bool
    passed: bool


class StaleEvidenceEscapeReport(StrictContractModel):
    schema_version: Literal[1]
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_escape_rate: float = Field(ge=0.0, le=1.0)
    total_cases: int = Field(ge=1)
    stale_cases: int = Field(ge=1)
    escape_count: int = Field(ge=0)
    escape_rate: float = Field(ge=0.0, le=1.0)
    target_met: bool
    all_expectations_met: bool
    cases: tuple[StaleEvidenceEscapeCaseResult, ...]


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_stale_evidence_escape_corpus() -> StaleEvidenceEscapeCorpus:
    """Load the single maintained repository corpus from its fixed path."""
    return StaleEvidenceEscapeCorpus.model_validate_json(
        STALE_EVIDENCE_ESCAPE_CORPUS_PATH.read_text(encoding="utf-8")
    )


def stale_evidence_escape_corpus_sha256(corpus: StaleEvidenceEscapeCorpus) -> str:
    canonical = _canonical_json(corpus.model_dump(mode="json")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _entity(graph: EngineeringGraph, kind: GraphEntityKind, key: str) -> str:
    entity_id = canonical_entity_id(graph.project_key, kind, key)
    graph.add_entity(GraphEntity(entity_id=entity_id, kind=kind, stable_key=key))
    return entity_id


def _copy(graph: EngineeringGraph) -> EngineeringGraph:
    return EngineeringGraph.from_document(graph.to_document())


def _mutate_entity(graph: EngineeringGraph, entity_id: str) -> EngineeringGraph:
    after = _copy(graph)
    original = after.entities[entity_id]
    after.entities[entity_id] = GraphEntity(
        entity_id=original.entity_id,
        kind=original.kind,
        stable_key=original.stable_key,
        attributes={"edited": "golden-mutation"},
        provenance=original.provenance,
        native_links=original.native_links,
    )
    return after


def _provenance() -> GraphProvenance:
    return GraphProvenance(GraphProvenanceKind.TOOL_GENERATED, source="native-oracle")


def _proof_record(ids: dict[str, str]) -> EvidenceRecord:
    hashes = {ids["contract"]: _C, ids["stackup"]: _B, ids["usb"]: _A}
    return EvidenceRecord.model_validate(
        {
            "schema_version": 1,
            "evidence_id": "EVID-USB-Z0",
            "kind": "evidence_artifact",
            "project_key": _REFERENCE_PROJECT,
            "source_revision": "board-revision-17",
            "source_sha256": _D,
            "producer": "kicad-cli-drc",
            "producer_version": "10.0.3",
            "captured_at": "2026-09-30T12:00:00Z",
            "dependency_manifest_complete": True,
            "inputs": [
                {"entity_id": entity_id, "sha256": digest}
                for entity_id, digest in sorted(hashes.items())
            ],
            "contract_id": "INTENT-USB-SI",
            "contract_version": 1,
            "provenance_source": "native-drc-fixture-17",
        }
    )


def _waiver_record(ids: dict[str, str]) -> EvidenceRecord:
    return EvidenceRecord.model_validate(
        {
            "schema_version": 1,
            "evidence_id": "WAIVER-EVID-USB-1",
            "kind": "waiver",
            "project_key": _REFERENCE_PROJECT,
            "source_revision": "board-revision-17",
            "source_sha256": _D,
            "producer": "review-board",
            "producer_version": "1",
            "captured_at": "2026-09-30T12:05:00Z",
            "dependency_manifest_complete": True,
            "inputs": [{"entity_id": ids["contract"], "sha256": _C}],
            "contract_id": "INTENT-USB-SI",
            "contract_version": 1,
            "provenance_source": "review-board-fixture",
        }
    )


def _contract(*, with_waiver: bool) -> HardwareIntentContract:
    waivers: list[dict[str, object]] = []
    if with_waiver:
        waivers.append(
            {
                "waiver_id": "WAIVER-USB-1",
                "contract_id": "INTENT-USB-SI",
                "contract_version": 1,
                "reason": "Reviewed temporary fixture exception",
                "approved_by": "hardware-lead",
                "approval_evidence_ref": "WAIVER-EVID-USB-1",
            }
        )
    return HardwareIntentContract.model_validate(
        {
            "schema_version": 1,
            "contract_id": "INTENT-USB-SI",
            "contract_version": 1,
            "requirement_id": "REQ-USB-SI",
            "applicability": {"kind": "net", "key": "USB_DP"},
            "severity": "blocking",
            "release_blocking": True,
            "verification": [{"method_ref": "native-check", "evidence_classes": ["drc"]}],
            "quantity_range": {"maximum": {"value": "90", "unit": "ohm"}},
            "waivers": waivers,
        }
    )


def _reference_fixture(
    *, with_waiver: bool
) -> tuple[
    EngineeringGraph,
    HardwareIntentContract,
    tuple[EvidenceRecord, ...],
    dict[str, str],
    dict[str, str],
]:
    graph = EngineeringGraph(project_key=_REFERENCE_PROJECT)
    ids = {
        "usb": _entity(graph, GraphEntityKind.NET, "USB_DP"),
        "stackup": _entity(graph, GraphEntityKind.CONSTRAINT, "PCB_STACKUP"),
        "u8": _entity(graph, GraphEntityKind.COMPONENT, "U8"),
        "contract": _entity(graph, GraphEntityKind.INTENT_CONTRACT, "INTENT-USB-SI"),
    }
    proof = _proof_record(ids)
    attach_evidence_record(graph, proof, provenance=_provenance())
    records: list[EvidenceRecord] = [proof]
    if with_waiver:
        waiver = _waiver_record(ids)
        attach_evidence_record(graph, waiver, provenance=_provenance())
        records.append(waiver)
    hashes = {ids["usb"]: _A, ids["stackup"]: _B, ids["contract"]: _C}
    return graph, _contract(with_waiver=with_waiver), tuple(records), hashes, ids


def _scenario_state(
    case: StaleEvidenceEscapeCase,
) -> tuple[
    EngineeringGraph,
    EngineeringGraph,
    HardwareIntentContract,
    tuple[EvidenceRecord, ...],
    dict[str, str],
    bool,
]:
    with_waiver = case.scenario in {
        StaleEvidenceScenario.FRESH_REVIEWED_WAIVER,
        StaleEvidenceScenario.STALE_REVIEWED_WAIVER,
    }
    before, contract, records, hashes, ids = _reference_fixture(with_waiver=with_waiver)
    after = _copy(before)
    mutation_scope_known = True

    if case.scenario is StaleEvidenceScenario.UNRELATED_COMPONENT_EDIT:
        after = _mutate_entity(before, ids["u8"])
    elif case.scenario in {
        StaleEvidenceScenario.USB_ENTITY_EDIT,
        StaleEvidenceScenario.FRESH_REVIEWED_WAIVER,
        StaleEvidenceScenario.STALE_REVIEWED_WAIVER,
    }:
        after = _mutate_entity(before, ids["usb"])
    elif case.scenario is StaleEvidenceScenario.STACKUP_ENTITY_EDIT:
        after = _mutate_entity(before, ids["stackup"])
    elif case.scenario is StaleEvidenceScenario.CONTRACT_ENTITY_EDIT:
        after = _mutate_entity(before, ids["contract"])
    elif case.scenario is StaleEvidenceScenario.USB_HASH_CHANGE:
        hashes[ids["usb"]] = _E
    elif case.scenario is StaleEvidenceScenario.UNKNOWN_MUTATION_SCOPE:
        mutation_scope_known = False
    elif case.scenario is StaleEvidenceScenario.MISSING_STACKUP_HASH:
        hashes.pop(ids["stackup"])
    elif case.scenario is StaleEvidenceScenario.DEPENDENCY_EDGE_REMOVED:
        after.edges = {
            edge
            for edge in after.edges
            if not (
                edge.source_id == evidence_graph_id(records[0])
                and edge.kind is GraphEdgeKind.DEPENDS_ON
                and edge.target_id == ids["stackup"]
            )
        }
    elif case.scenario is StaleEvidenceScenario.TAMPERED_EVIDENCE_RECORD:
        for graph in (before, after):
            evidence_id = evidence_graph_id(records[0])
            stored = graph.entities[evidence_id]
            graph.entities[evidence_id] = GraphEntity(
                entity_id=stored.entity_id,
                kind=stored.kind,
                stable_key=stored.stable_key,
                attributes={"record": {"tampered": True}},
                provenance=stored.provenance,
                native_links=stored.native_links,
            )
    if case.scenario is StaleEvidenceScenario.STALE_REVIEWED_WAIVER:
        hashes.pop(ids["contract"])

    return before, after, contract, records, hashes, mutation_scope_known


def evaluate_stale_evidence_escape_case(
    case: StaleEvidenceEscapeCase,
) -> StaleEvidenceEscapeCaseResult:
    before, after, contract, records, hashes, mutation_scope_known = _scenario_state(case)
    assessments = tuple(
        assess_evidence_freshness(
            record,
            before=before,
            after=after,
            current_hashes=hashes,
            mutation_scope_known=mutation_scope_known,
        )
        for record in records
    )
    assessment_map: dict[str, FreshnessAssessment] = {
        assessment.evidence_id: assessment for assessment in assessments
    }
    proof = records[0]
    waiver = records[1] if len(records) > 1 else None
    gate_assessments = assessments
    if case.scenario is StaleEvidenceScenario.MISSING_FRESHNESS_ASSESSMENT:
        gate_assessments = tuple(
            assessment for assessment in assessments if assessment.evidence_id != proof.evidence_id
        )
    gate = evaluate_release_evidence((contract,), records, gate_assessments)
    release = gate.contracts[0]
    reason_codes = tuple(release.reason_codes)
    primary_freshness = assessment_map[proof.evidence_id].state
    waiver_freshness = assessment_map[waiver.evidence_id].state if waiver is not None else None
    escaped = case.must_block and gate.approved
    passed = (
        primary_freshness is case.expected_primary_freshness
        and waiver_freshness is case.expected_waiver_freshness
        and release.state is case.expected_release_state
        and reason_codes == case.expected_reason_codes
        and not escaped
    )
    return StaleEvidenceEscapeCaseResult(
        case_id=case.case_id,
        scenario=case.scenario,
        must_block=case.must_block,
        primary_freshness=primary_freshness,
        waiver_freshness=waiver_freshness,
        release_approved=gate.approved,
        release_state=release.state,
        reason_codes=reason_codes,
        escaped=escaped,
        passed=passed,
    )


def build_stale_evidence_escape_report(
    corpus: StaleEvidenceEscapeCorpus,
) -> StaleEvidenceEscapeReport:
    results = tuple(evaluate_stale_evidence_escape_case(case) for case in corpus.cases)
    stale_cases = sum(result.must_block for result in results)
    escape_count = sum(result.escaped for result in results)
    escape_rate = escape_count / stale_cases
    return StaleEvidenceEscapeReport(
        schema_version=STALE_EVIDENCE_ESCAPE_SCHEMA_VERSION,
        corpus_sha256=stale_evidence_escape_corpus_sha256(corpus),
        target_escape_rate=corpus.target_escape_rate,
        total_cases=len(results),
        stale_cases=stale_cases,
        escape_count=escape_count,
        escape_rate=escape_rate,
        target_met=escape_rate <= corpus.target_escape_rate,
        all_expectations_met=all(result.passed for result in results),
        cases=results,
    )


def render_stale_evidence_escape_report_json(
    report: StaleEvidenceEscapeReport,
) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
