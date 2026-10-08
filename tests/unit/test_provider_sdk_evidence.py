"""Provider result -> #942 EvidenceRecord handoff never manufactures KiCad verification."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kicad_mcp.project.evidence_freshness import EvidenceInputDigest, EvidenceRecordKind
from kicad_mcp.providers import (
    ProviderFamily,
    ProviderManifest,
    ProviderOperation,
    ProviderProvenance,
    ProviderResult,
    provider_evidence_handoff,
)


def test_attaches_only_a_measurement_with_host_owned_inputs() -> None:
    manifest = ProviderManifest(
        sdk_version="0-experimental", provider_id="fixture-solver",
        provider_version="0.1.0", family=ProviderFamily.SOLVER,
        capabilities=("solver.dc",),
        operations=(ProviderOperation(name="solve", capability="solver.dc"),),
        deterministic=False, provenance_source="solver:fixture",
        healthcheck="ready", license_id="MIT", distribution_notes="Dummy",
    )
    result = ProviderResult(
        request_id="run-001", ok=True, payload={"voltage": 3.3},
        provenance=ProviderProvenance(
            provider_id="fixture-solver", provider_version="0.1.0",
            source="solver:fixture", execution_id="run-001",
            deterministic=False, input_sha256="a" * 64, output_sha256="b" * 64,
        ),
    )
    entries = (EvidenceInputDigest(entity_id="project:input", sha256="c" * 64),)
    evidence = provider_evidence_handoff(
        result, manifest, evidence_id="provider-measurement-001",
        project_key="fixture", source_revision="git:abc", source_sha256="d" * 64,
        captured_at=datetime.now(UTC), inputs=entries,
        dependency_manifest_complete=False,
    )
    assert evidence.kind is EvidenceRecordKind.MEASUREMENT
    assert evidence.dependency_manifest_complete is False
    assert evidence.inputs == entries
    assert evidence.producer == "fixture-solver"
    assert evidence.provenance_source == "solver:fixture"

    bad = result.model_copy(update={
        "provenance": result.provenance.model_copy(update={"provider_id": "forged"})
    })
    with pytest.raises(ValueError, match="mismatch"):
        provider_evidence_handoff(
            bad, manifest, evidence_id="provider-measurement-002",
            project_key="fixture", source_revision="git:abc", source_sha256="d" * 64,
            captured_at=datetime.now(UTC), inputs=entries,
            dependency_manifest_complete=False,
        )
    with pytest.raises(ValueError, match="failed"):
        provider_evidence_handoff(
            ProviderResult.model_validate({
                "request_id": "run-001", "ok": False,
                "error": {"code": "provider_failure", "message": "failed"},
            }),
            manifest, evidence_id="provider-measurement-003",
            project_key="fixture", source_revision="git:abc", source_sha256="d" * 64,
            captured_at=datetime.now(UTC), inputs=entries,
            dependency_manifest_complete=False,
        )


def test_strict_result_envelope_rejects_missing_provenance() -> None:
    with pytest.raises(ValidationError, match="provenance"):
        ProviderResult(request_id="req-001", ok=True)
    with pytest.raises(ValidationError, match="structured error"):
        ProviderResult(request_id="req-001", ok=False)
