"""Structured provider results; successful adapters must supply exact provenance."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue, model_validator

from kicad_mcp.project.evidence_freshness import (
    EvidenceInputDigest,
    EvidenceRecord,
    EvidenceRecordKind,
)
from kicad_mcp.project.hardware_intent_contract import StrictContractModel

from .contracts import SHA256, ProviderErrorCode
from .manifest import ProviderManifest


# Revalidate even constructed/copied model instances returned across the provider boundary.
class ProviderProvenance(StrictContractModel):
    model_config = ConfigDict(revalidate_instances="always")

    provider_id: str
    provider_version: str
    source: str
    execution_id: str = Field(min_length=3, max_length=128)
    deterministic: bool
    input_sha256: str = Field(pattern=SHA256)
    output_sha256: str = Field(pattern=SHA256)


class ProviderError(StrictContractModel):
    model_config = ConfigDict(revalidate_instances="always")

    code: ProviderErrorCode
    message: str = Field(min_length=1, max_length=200)


class ProviderResult(StrictContractModel):
    # Provider output crosses a trust boundary even when already a model instance.
    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal[0] = 0
    request_id: str
    ok: bool
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    provenance: ProviderProvenance | None = None
    error: ProviderError | None = None

    @model_validator(mode="after")
    def check_outcome(self) -> ProviderResult:
        if self.ok and (self.error is not None or self.provenance is None):
            raise ValueError("successful result requires provenance and no error")
        if not self.ok and (self.error is None or self.provenance is not None or self.payload):
            raise ValueError("failure requires only a structured error")
        return self


def provider_evidence_handoff(
    result: ProviderResult,
    manifest: ProviderManifest,
    *,
    evidence_id: str,
    project_key: str,
    source_revision: str,
    source_sha256: str,
    captured_at: datetime,
    inputs: tuple[EvidenceInputDigest, ...],
    dependency_manifest_complete: bool,
) -> EvidenceRecord:
    """Create an UNVERIFIED measurement record using host-supplied source dependencies.

    Recording a provider result does not assert that KiCad/native verification passed.
    The caller must separately attach it to a matching Engineering Graph and run
    the normal #942 freshness and quality-gate assessment.
    """
    proof = result.provenance
    if not result.ok or proof is None:
        raise ValueError("cannot attach failed provider result as evidence")
    if (
        proof.provider_id != manifest.provider_id
        or proof.provider_version != manifest.provider_version
        or proof.source != manifest.provenance_source
        or proof.deterministic != manifest.deterministic
    ):
        raise ValueError("provider provenance/manifest mismatch")
    return EvidenceRecord(
        schema_version=1,
        evidence_id=evidence_id,
        kind=EvidenceRecordKind.MEASUREMENT,
        project_key=project_key,
        source_revision=source_revision,
        source_sha256=source_sha256,
        producer=manifest.provider_id,
        producer_version=manifest.provider_version,
        captured_at=captured_at,
        dependency_manifest_complete=dependency_manifest_complete,
        inputs=inputs,
        provenance_source=manifest.provenance_source,
    )
