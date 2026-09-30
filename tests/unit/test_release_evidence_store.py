"""Project-local HardwareIntentContract/EvidenceRecord sidecar loading."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import kicad_mcp.project.release_evidence_store as store_module
from kicad_mcp.ir.engineering_graph import (
    EngineeringGraph,
    GraphEntity,
    GraphEntityKind,
    canonical_entity_id,
)
from kicad_mcp.project.evidence_current_state import canonical_graph_entity_sha256
from kicad_mcp.project.release_evidence_store import (
    EVIDENCE_RECORD_STORE_FILENAME,
    HARDWARE_INTENT_STORE_FILENAME,
    RELEASE_EVIDENCE_DIRNAME,
    load_evidence_records,
    load_hardware_intent_contracts,
    resolve_project_release_evidence,
)

H = "a" * 64


def _contract(*, release_blocking: bool = True) -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": "INTENT-USB-SI",
        "contract_version": 1,
        "requirement_id": "REQ-USB-SI",
        "applicability": {"kind": "net", "key": "USB_DP"},
        "severity": "blocking" if release_blocking else "warning",
        "release_blocking": release_blocking,
        "verification": [{"method_ref": "native-check", "evidence_classes": ["drc"]}],
        "quantity_range": {"maximum": {"value": "90", "unit": "ohm"}},
    }


def _evidence(evidence_id: str = "EVID-USB-1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "kind": "evidence_artifact",
        "project_key": "fixture",
        "source_revision": "rev-1",
        "source_sha256": H,
        "producer": "native-check",
        "producer_version": "10.0.3",
        "captured_at": datetime(2026, 9, 30, 15, 0, tzinfo=UTC).isoformat(),
        "dependency_manifest_complete": True,
        "inputs": [{"entity_id": "fixture:net:USB_DP", "sha256": H}],
        "contract_id": "INTENT-USB-SI",
        "contract_version": 1,
        "provenance_source": "native-fixture",
    }


def _graph(*, revision: int | None = None) -> tuple[EngineeringGraph, str]:
    graph = EngineeringGraph(project_key="fixture")
    entity_id = canonical_entity_id("fixture", GraphEntityKind.NET, "USB_DP")
    attributes: dict[str, object] = {"name": "USB_DP"}
    if revision is not None:
        attributes["revision"] = revision
    graph.add_entity(
        GraphEntity(
            entity_id=entity_id,
            kind=GraphEntityKind.NET,
            stable_key="USB_DP",
            attributes=attributes,
        )
    )
    return graph, entity_id


def _write(project: Path, name: str, payload: object) -> None:
    root = project / RELEASE_EVIDENCE_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(payload), encoding="utf-8")


def test_absent_contract_sidecar_preserves_legacy_projects(tmp_path: Path) -> None:
    resolved = resolve_project_release_evidence(tmp_path)
    assert not resolved.adopted
    assert resolved.approved
    assert resolved.gate is None


def test_versioned_contract_and_evidence_stores_roundtrip(tmp_path: Path) -> None:
    _write(
        tmp_path,
        HARDWARE_INTENT_STORE_FILENAME,
        {"schema_version": 1, "contracts": [_contract()]},
    )
    _write(
        tmp_path,
        EVIDENCE_RECORD_STORE_FILENAME,
        {"schema_version": 1, "records": [_evidence()]},
    )
    contracts = load_hardware_intent_contracts(tmp_path)
    records = load_evidence_records(tmp_path)
    assert contracts[0].contract_id == "INTENT-USB-SI"
    assert records[0].evidence_id == "EVID-USB-1"


def test_release_blocking_contract_never_passes_without_current_native_resolution(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        HARDWARE_INTENT_STORE_FILENAME,
        {"schema_version": 1, "contracts": [_contract()]},
    )
    _write(
        tmp_path,
        EVIDENCE_RECORD_STORE_FILENAME,
        {"schema_version": 1, "records": [_evidence()]},
    )
    resolved = resolve_project_release_evidence(tmp_path)
    assert resolved.adopted
    assert not resolved.approved
    assert resolved.gate is not None
    assert resolved.gate.blocking[0].reason_codes == ("required_evidence_requires_recheck",)


def test_missing_evidence_sidecar_blocks_adopted_release_contract(tmp_path: Path) -> None:
    _write(
        tmp_path,
        HARDWARE_INTENT_STORE_FILENAME,
        {"schema_version": 1, "contracts": [_contract()]},
    )
    resolved = resolve_project_release_evidence(tmp_path)
    assert not resolved.approved
    assert resolved.gate is not None
    assert resolved.gate.blocking[0].reason_codes == ("required_evidence_missing",)


def test_nonblocking_contract_does_not_create_release_block(tmp_path: Path) -> None:
    _write(
        tmp_path,
        HARDWARE_INTENT_STORE_FILENAME,
        {"schema_version": 1, "contracts": [_contract(release_blocking=False)]},
    )
    resolved = resolve_project_release_evidence(tmp_path)
    assert resolved.adopted
    assert resolved.approved
    assert resolved.gate is not None
    assert resolved.gate.contracts == ()


def test_malformed_contract_or_evidence_metadata_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, HARDWARE_INTENT_STORE_FILENAME, {"schema_version": 7})
    bad_contract = resolve_project_release_evidence(tmp_path)
    assert not bad_contract.approved
    assert bad_contract.errors
    assert "hardware_intent_contract_store_invalid" in bad_contract.errors[0]

    _write(
        tmp_path,
        HARDWARE_INTENT_STORE_FILENAME,
        {"schema_version": 1, "contracts": [_contract()]},
    )
    _write(tmp_path, EVIDENCE_RECORD_STORE_FILENAME, {"schema_version": 1, "records": "bad"})
    bad_evidence = resolve_project_release_evidence(tmp_path)
    assert not bad_evidence.approved
    assert bad_evidence.errors
    assert "evidence_record_store_invalid" in bad_evidence.errors[0]


def test_direct_evidence_loader_returns_empty_when_sidecar_is_absent(tmp_path: Path) -> None:
    assert load_evidence_records(tmp_path) == ()


def test_direct_contract_loader_returns_empty_when_sidecar_is_absent(tmp_path: Path) -> None:
    assert load_hardware_intent_contracts(tmp_path) == ()


def test_trusted_current_graph_can_establish_exact_freshness(tmp_path: Path) -> None:
    graph, entity_id = _graph()
    evidence = _evidence()
    evidence["inputs"] = [
        {
            "entity_id": entity_id,
            "sha256": canonical_graph_entity_sha256(graph.entities[entity_id]),
        }
    ]
    _write(
        tmp_path,
        HARDWARE_INTENT_STORE_FILENAME,
        {"schema_version": 1, "contracts": [_contract()]},
    )
    _write(
        tmp_path,
        EVIDENCE_RECORD_STORE_FILENAME,
        {"schema_version": 1, "records": [evidence]},
    )

    resolved = resolve_project_release_evidence(
        tmp_path,
        current_graph=graph,
        current_source_sha256=H,
    )
    assert resolved.approved
    assert resolved.gate is not None
    assert resolved.gate.contracts[0].state.value == "satisfied"


def test_trusted_current_graph_change_invalidates_release_proof(tmp_path: Path) -> None:
    graph, entity_id = _graph(revision=1)
    original = graph.entities[entity_id]
    evidence = _evidence()
    evidence["inputs"] = [
        {"entity_id": entity_id, "sha256": canonical_graph_entity_sha256(original)}
    ]
    _write(
        tmp_path,
        HARDWARE_INTENT_STORE_FILENAME,
        {"schema_version": 1, "contracts": [_contract()]},
    )
    _write(
        tmp_path,
        EVIDENCE_RECORD_STORE_FILENAME,
        {"schema_version": 1, "records": [evidence]},
    )

    graph.entities[entity_id] = GraphEntity(
        entity_id=entity_id,
        kind=GraphEntityKind.NET,
        stable_key="USB_DP",
        attributes={"name": "USB_DP", "revision": 2},
    )
    resolved = resolve_project_release_evidence(
        tmp_path,
        current_graph=graph,
        current_source_sha256=H,
    )
    assert not resolved.approved
    assert resolved.gate is not None
    assert "required_evidence_invalidated" in resolved.gate.blocking[0].reason_codes


def test_shared_dependency_hashes_are_precomputed_once(tmp_path: Path, monkeypatch) -> None:
    graph, entity_id = _graph()
    digest = canonical_graph_entity_sha256(graph.entities[entity_id])
    first = _evidence("EVID-USB-1")
    second_record = _evidence("EVID-USB-2")
    first["inputs"] = [{"entity_id": entity_id, "sha256": digest}]
    second_record["inputs"] = [{"entity_id": entity_id, "sha256": digest}]
    _write(
        tmp_path,
        HARDWARE_INTENT_STORE_FILENAME,
        {"schema_version": 1, "contracts": [_contract()]},
    )
    _write(
        tmp_path,
        EVIDENCE_RECORD_STORE_FILENAME,
        {"schema_version": 1, "records": [first, second_record]},
    )

    calls = 0
    original = store_module.graph_entity_hashes

    def counted(current_graph: EngineeringGraph, entity_ids: tuple[str, ...]):
        nonlocal calls
        calls += 1
        return original(current_graph, entity_ids)

    monkeypatch.setattr(store_module, "graph_entity_hashes", counted)
    resolved = resolve_project_release_evidence(
        tmp_path,
        current_graph=graph,
        current_source_sha256=H,
    )

    assert resolved.approved
    assert calls == 1
