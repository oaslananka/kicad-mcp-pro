"""Synthetic source provenance and fail-closed draft review state for #946."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from kicad_mcp.library.component_evidence_draft import (
    ComponentEvidenceDraft,
    ComponentEvidenceFact,
    ComponentFactCitation,
    ComponentSourceDocument,
    FactState,
)


def source(**overrides: object) -> ComponentSourceDocument:
    data: dict[str, object] = {
        "source_id": "doc-main",
        "source_locator": "test-fixture:synthetic-datasheet",
        "revision": "v1",
        "sha256": "a" * 64,
    }
    data.update(overrides)
    return ComponentSourceDocument.model_validate(data)


def cited_fact(**overrides: object) -> ComponentEvidenceFact:
    data: dict[str, object] = {
        "attribute": "electrical.maximum_voltage",
        "state": "cited",
        "value": "3.6 V",
        "citations": [{"source_id": "doc-main", "location": "page 4; table 2"}],
    }
    data.update(overrides)
    return ComponentEvidenceFact.model_validate(data)


def draft(**overrides: object) -> ComponentEvidenceDraft:
    data: dict[str, object] = {
        "schema_version": 0,
        "component_id": "example-mcu",
        "manufacturer": "Example Manufacturer",
        "mpn": "EXAMPLE-01",
        "source_documents": (source(),),
        "facts": (cited_fact(),),
    }
    data.update(overrides)
    return ComponentEvidenceDraft.model_validate(data)


def test_draft_roundtrip_preserves_identity_hash_and_location() -> None:
    record = draft()
    restored = ComponentEvidenceDraft.model_validate_json(record.model_dump_json())
    assert restored == record
    assert restored.facts[0].citations[0].location == "page 4; table 2"
    assert restored.source_documents[0].sha256 == "a" * 64
    assert restored.review_state == "draft"
    assert restored.schema_version == 0


@pytest.mark.parametrize("bad_sha", ["", "A" * 64, "f" * 63, "g" * 64])
def test_document_requires_exact_lowercase_sha256(bad_sha: str) -> None:
    with pytest.raises(ValidationError, match="sha256"):
        source(sha256=bad_sha)


@pytest.mark.parametrize(
    "change",
    [
        {"value": None},
        {"value": ""},
        {"citations": []},
        {"citations": [{"source_id": "doc-main", "location": "page 4"}] * 2},
    ],
)
def test_cited_facts_fail_closed_without_value_unique_citations(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        cited_fact(**change)


@pytest.mark.parametrize("state", ["unknown", "not_applicable"])
def test_unresolved_states_need_reason_and_no_asserted_value(state: str) -> None:
    fact = cited_fact(state=state, value=None, citations=[], reason="not yet established")
    assert fact.state == FactState(state)
    with pytest.raises(ValidationError):
        cited_fact(state=state, value="verified", reason="unreviewed")
    with pytest.raises(ValidationError):
        cited_fact(state=state, value=None, citations=[], reason=None)


def test_conflicts_are_not_silently_resolved() -> None:
    other = ComponentFactCitation(source_id="doc-main", location="page 9")
    first = ComponentFactCitation(source_id="doc-main", location="page 4")
    conflicting = cited_fact(
        state="conflicting", value=None, citations=[first, other], reason="inconsistent ranges"
    )
    assert conflicting.state is FactState.CONFLICTING
    with pytest.raises(ValidationError):
        cited_fact(state="conflicting", value="3.6 V", citations=[first, other], reason="dispute")
    with pytest.raises(ValidationError):
        cited_fact(state="conflicting", value=None, citations=[first], reason="dispute")


@pytest.mark.parametrize(
    "changed",
    [
        {"source_documents": (source(), source())},
        {"facts": (cited_fact(), cited_fact())},
        {"facts": (cited_fact(citations=[{"source_id": "missing", "location": "p.1"}]),)},
    ],
)
def test_cross_document_consistency_blocks_invalid_drafts(changed: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        draft(**changed)


@pytest.mark.parametrize("invalid_state", ["verified", "approved", "production_ready"])
def test_self_reported_review_cannot_grant_verification(invalid_state: str) -> None:
    with pytest.raises(ValidationError, match="review_state"):
        draft(review_state=invalid_state)


def test_rejects_unexpected_fields_and_schema_upgrade() -> None:
    with pytest.raises(ValidationError):
        draft(schema_version=1)
    with pytest.raises(ValidationError):
        draft(approved_by="pretend-human")


def test_generated_draft_schema_matches_source() -> None:
    schema = ComponentEvidenceDraft.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = (
        "https://raw.githubusercontent.com/oaslananka/kicad-mcp-pro/main/"
        "src/kicad_mcp/library/schemas/component-evidence-draft-v0.schema.json"
    )
    path = (
        Path(__file__).resolve().parents[2]
        / "src/kicad_mcp/library/schemas/component-evidence-draft-v0.schema.json"
    )
    assert json.loads(path.read_text(encoding="utf-8")) == schema


def test_unknown_reason_rejects_only_spaces() -> None:
    with pytest.raises(ValidationError, match="reason"):
        cited_fact(state="unknown", value=None, citations=[], reason="   ")


def test_conflicting_reason_rejects_only_spaces() -> None:
    citations = [
        {"source_id": "doc-main", "location": "p1"},
        {"source_id": "doc-main", "location": "p2"},
    ]
    with pytest.raises(ValidationError, match="reason"):
        cited_fact(state="conflicting", value=None, citations=citations, reason="   ")
