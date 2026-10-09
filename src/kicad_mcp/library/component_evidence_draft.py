"""Experimental #946 component fact/citation records; never production approvals.

This pure-data boundary does not fetch documents, verify extracted facts, certify
footprints, or issue human review decisions. KiCad/library verification remains
owned by the existing component-contract service and evidence gate.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from kicad_mcp.project.hardware_intent_contract import StrictContractModel

_IDENTIFIER = r"^[A-Za-z][A-Za-z0-9_.:-]*$"
_SHA256 = r"^[0-9a-f]{64}$"


class FactState(StrEnum):
    CITED = "cited"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    CONFLICTING = "conflicting"


class ComponentSourceDocument(StrictContractModel):
    """Reviewed source *identity*, not proof the referenced document was read."""

    source_id: str = Field(min_length=2, max_length=120, pattern=_IDENTIFIER)
    source_locator: str = Field(min_length=3, max_length=500)
    revision: str = Field(min_length=1, max_length=120)
    sha256: str = Field(pattern=_SHA256)


class ComponentFactCitation(StrictContractModel):
    source_id: str = Field(min_length=2, max_length=120, pattern=_IDENTIFIER)
    location: str = Field(min_length=1, max_length=200)


class ComponentEvidenceFact(StrictContractModel):
    attribute: str = Field(min_length=2, max_length=120, pattern=_IDENTIFIER)
    state: FactState
    value: str | None = Field(default=None, max_length=500)
    citations: tuple[ComponentFactCitation, ...] = ()
    reason: str | None = Field(default=None, min_length=3, max_length=500)

    @model_validator(mode="after")
    def require_provenance_or_explicit_uncertainty(self) -> Self:
        cited_locations = {(cite.source_id, cite.location) for cite in self.citations}
        if len(cited_locations) != len(self.citations):
            raise ValueError("duplicate fact citation")
        if self.state is FactState.CITED:
            if not self.value or not self.value.strip() or not self.citations:
                raise ValueError("cited fact requires value and source location")
        elif self.state is FactState.CONFLICTING:
            if self.value is not None or len(self.citations) < 2 or not self.reason:
                raise ValueError("conflicting fact needs multiple citations and reason, not value")
        elif self.value is not None or not self.reason:
            raise ValueError("unknown or not-applicable fact requires reason, not value")
        return self


class ComponentEvidenceDraft(StrictContractModel):
    """Metadata-only review intake. No verified/approved state exists in v0."""

    schema_version: Literal[0] = 0
    component_id: str = Field(min_length=2, max_length=120, pattern=_IDENTIFIER)
    manufacturer: str = Field(min_length=1, max_length=160)
    mpn: str = Field(min_length=1, max_length=160)
    source_documents: tuple[ComponentSourceDocument, ...] = Field(min_length=1)
    facts: tuple[ComponentEvidenceFact, ...] = Field(min_length=1)
    review_state: Literal["draft", "needs_human_review"] = "draft"

    @model_validator(mode="after")
    def validate_referenced_source_locations(self) -> Self:
        source_ids = [doc.source_id for doc in self.source_documents]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate source document ID")
        facts = [fact.attribute for fact in self.facts]
        if len(facts) != len(set(facts)):
            raise ValueError("duplicate component fact attribute")
        if any(
            citation.source_id not in source_ids
            for fact in self.facts
            for citation in fact.citations
        ):
            raise ValueError("fact references unknown source document")
        return self
