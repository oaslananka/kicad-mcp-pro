"""Append-only release approval and waiver audit history for #942."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

import kicad_mcp.project.release_approval_audit as audit_module
from kicad_mcp.project.evidence_freshness import EvidenceRecord
from kicad_mcp.project.release_approval_audit import (
    ReleaseApprovalAuditDecision,
    ReleaseApprovalAuditEvent,
    ReleaseApprovalAuditIntegrityError,
    append_release_approval_event,
    canonical_evidence_record_json,
    evidence_record_sha256,
    release_approval_audit_path,
    verify_release_approval_history,
)

H1 = "a" * 64
H2 = "b" * 64


def _record(
    evidence_id: str = "APPROVAL-1",
    *,
    kind: str = "approval",
    source_sha256: str = H1,
    contract_version: int = 1,
) -> EvidenceRecord:
    return EvidenceRecord.model_validate(
        {
            "schema_version": 1,
            "evidence_id": evidence_id,
            "kind": kind,
            "project_key": "fixture",
            "source_revision": "rev-1",
            "source_sha256": source_sha256,
            "producer": "human-review",
            "producer_version": "1",
            "captured_at": datetime(2026, 9, 30, 20, 0, tzinfo=UTC),
            "dependency_manifest_complete": True,
            "inputs": [{"entity_id": "fixture:intent_contract:INTENT-USB-SI", "sha256": H1}],
            "contract_id": "INTENT-USB-SI",
            "contract_version": contract_version,
            "provenance_source": "review-board",
        }
    )


def _append(project_dir: Path, record: EvidenceRecord | None = None):
    return append_release_approval_event(
        project_dir,
        evidence_record=record or _record(),
        actor="hardware-lead",
        scope="release:hardware",
        rationale="Reviewed for release",
        recorded_at=datetime(2026, 9, 30, 21, 0, tzinfo=UTC),
    )


def _drop_guard(path: Path, trigger: str) -> None:
    if trigger == "release_approval_events_no_update":
        statement = "DROP TRIGGER release_approval_events_no_update"
    elif trigger == "release_approval_events_no_delete":
        statement = "DROP TRIGGER release_approval_events_no_delete"
    else:
        raise ValueError(f"unsupported audit trigger: {trigger}")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement)
        connection.commit()


def _mutate(path: Path, sql: str, parameters: tuple[object, ...] = ()) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(sql, parameters)
        connection.commit()


def _rewrite_event_with_valid_hash(path: Path, *, recorded_at: str) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM release_approval_events WHERE sequence = 1"
        ).fetchone()
        assert row is not None
        payload = {
            "schema_version": 1,
            "sequence": row["sequence"],
            "decision": row["decision"],
            "project_key": row["project_key"],
            "contract_id": row["contract_id"],
            "contract_version": row["contract_version"],
            "evidence_id": row["evidence_id"],
            "evidence_sha256": row["evidence_sha256"],
            "evidence_record_json": row["evidence_record_json"],
            "actor": row["actor"],
            "scope": row["scope"],
            "rationale": row["rationale"],
            "recorded_at": recorded_at,
            "previous_event_sha256": row["previous_event_sha256"],
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        event_hash = hashlib.sha256(encoded).hexdigest()
        connection.execute(
            "UPDATE release_approval_events "
            "SET recorded_at = ?, event_sha256 = ? WHERE sequence = 1",
            (recorded_at, event_hash),
        )
        connection.commit()


def test_append_approval_creates_exact_bound_history(tmp_path: Path) -> None:
    record = _record()
    event = _append(tmp_path, record)
    assert event.sequence == 1
    assert event.decision is ReleaseApprovalAuditDecision.APPROVAL
    assert event.contract_id == record.contract_id
    assert event.contract_version == record.contract_version
    assert event.evidence_id == record.evidence_id
    assert event.evidence_sha256 == evidence_record_sha256(record)
    assert event.evidence_record == record
    assert event.previous_event_sha256 is None
    assert release_approval_audit_path(tmp_path).is_file()


def test_append_waiver_links_hash_chain(tmp_path: Path) -> None:
    first = _append(tmp_path)
    waiver = _record("WAIVER-1", kind="waiver")
    second = _append(tmp_path, waiver)
    assert second.sequence == 2
    assert second.decision is ReleaseApprovalAuditDecision.WAIVER
    assert second.previous_event_sha256 == first.event_sha256
    assert [event.evidence_id for event in verify_release_approval_history(tmp_path)] == [
        "APPROVAL-1",
        "WAIVER-1",
    ]


def test_non_approval_evidence_is_rejected(tmp_path: Path) -> None:
    record = _record(kind="evidence_artifact")
    with pytest.raises(ValueError, match="only approval or waiver"):
        _append(tmp_path, record)


def test_actor_scope_and_rationale_are_required(tmp_path: Path) -> None:
    for field in ("actor", "scope", "rationale"):
        kwargs = {
            "evidence_record": _record(),
            "actor": "hardware-lead",
            "scope": "release:hardware",
            "rationale": "Reviewed",
        }
        kwargs[field] = "   "
        with pytest.raises(ValueError, match="must be non-empty"):
            append_release_approval_event(tmp_path, **kwargs)


def test_recorded_at_requires_explicit_utc(tmp_path: Path) -> None:
    non_utc = timezone(timedelta(hours=3))
    record = _record()
    recorded_at = datetime(2026, 9, 30, 23, 0, tzinfo=non_utc)
    with pytest.raises(ValueError, match="explicit UTC"):
        append_release_approval_event(
            tmp_path,
            evidence_record=record,
            actor="hardware-lead",
            scope="release:hardware",
            rationale="Reviewed",
            recorded_at=recorded_at,
        )


def test_update_and_delete_are_blocked_by_sqlite_guards(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    with closing(sqlite3.connect(path)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE release_approval_events SET actor = 'other' WHERE sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM release_approval_events WHERE sequence = 1")


def test_event_field_tampering_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    _mutate(path, "UPDATE release_approval_events SET actor = 'tampered' WHERE sequence = 1")
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="event hash mismatch"):
        verify_release_approval_history(tmp_path)


def test_evidence_snapshot_tampering_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT evidence_record_json FROM release_approval_events WHERE sequence = 1"
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
    payload["producer"] = "tampered"
    _mutate(
        path,
        "UPDATE release_approval_events SET evidence_record_json = ? WHERE sequence = 1",
        (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
    )
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="snapshot digest mismatch"):
        verify_release_approval_history(tmp_path)


def test_chain_predecessor_tampering_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    _append(tmp_path, _record("WAIVER-1", kind="waiver"))
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    _mutate(
        path,
        "UPDATE release_approval_events SET previous_event_sha256 = ? WHERE sequence = 2",
        (H2,),
    )
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="predecessor mismatch"):
        verify_release_approval_history(tmp_path)


def test_sequence_gap_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    _append(tmp_path, _record("WAIVER-1", kind="waiver"))
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_delete")
    _mutate(path, "DELETE FROM release_approval_events WHERE sequence = 1")
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="sequence gap"):
        verify_release_approval_history(tmp_path)


def test_stale_evidence_snapshot_remains_auditable_after_newer_decision(tmp_path: Path) -> None:
    old = _record(source_sha256=H1)
    _append(tmp_path, old)
    _append(tmp_path, _record("APPROVAL-2", source_sha256=H2))
    history = verify_release_approval_history(tmp_path)
    assert history[0].evidence_record.source_sha256 == H1
    assert history[0].evidence_sha256 == evidence_record_sha256(old)
    assert history[1].evidence_record.source_sha256 == H2


def test_history_reopens_and_verifies_across_connections(tmp_path: Path) -> None:
    event = _append(tmp_path)
    loaded = verify_release_approval_history(tmp_path)
    assert loaded == (event,)
    assert loaded[0].evidence_record.model_dump(mode="json") == json.loads(
        canonical_evidence_record_json(_record())
    )


def test_append_refuses_to_extend_tampered_history(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    _mutate(path, "UPDATE release_approval_events SET scope = 'tampered' WHERE sequence = 1")
    waiver = _record("WAIVER-1", kind="waiver")
    with pytest.raises(ReleaseApprovalAuditIntegrityError):
        _append(tmp_path, waiver)


def test_missing_history_is_empty(tmp_path: Path) -> None:
    assert verify_release_approval_history(tmp_path) == ()


def test_default_recorded_at_is_explicit_utc(tmp_path: Path) -> None:
    event = append_release_approval_event(
        tmp_path,
        evidence_record=_record(),
        actor="hardware-lead",
        scope="release:hardware",
        rationale="Reviewed",
    )
    assert event.recorded_at.utcoffset() == timedelta(0)


def test_event_model_rejects_non_utc_timestamp(tmp_path: Path) -> None:
    event = _append(tmp_path)
    payload = event.model_dump()
    payload["recorded_at"] = datetime(2026, 9, 30, 23, 0, tzinfo=timezone(timedelta(hours=3)))
    with pytest.raises(ValueError, match="explicit UTC"):
        ReleaseApprovalAuditEvent.model_validate(payload)


def test_invalid_embedded_evidence_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    _mutate(
        path,
        "UPDATE release_approval_events SET evidence_record_json = ? WHERE sequence = 1",
        ("{",),
    )
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="invalid embedded evidence"):
        verify_release_approval_history(tmp_path)


def test_stored_evidence_digest_tampering_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    _mutate(
        path,
        "UPDATE release_approval_events SET evidence_sha256 = ? WHERE sequence = 1",
        (H2,),
    )
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="snapshot digest mismatch"):
        verify_release_approval_history(tmp_path)


def test_decision_kind_tampering_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    _mutate(path, "UPDATE release_approval_events SET decision = 'waiver' WHERE sequence = 1")
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="kind does not match"):
        verify_release_approval_history(tmp_path)


def test_evidence_binding_tampering_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    _mutate(path, "UPDATE release_approval_events SET project_key = 'other' WHERE sequence = 1")
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="binding mismatch"):
        verify_release_approval_history(tmp_path)


def test_rehashed_but_invalid_event_payload_is_detected(tmp_path: Path) -> None:
    _append(tmp_path)
    path = release_approval_audit_path(tmp_path)
    _drop_guard(path, "release_approval_events_no_update")
    _rewrite_event_with_valid_hash(path, recorded_at="not-a-date")
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="invalid audit event"):
        verify_release_approval_history(tmp_path)


def test_failed_post_insert_verification_rolls_back_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_verify = audit_module._verify_connection
    calls = 0

    def fail_second_verification(
        connection: sqlite3.Connection,
    ) -> tuple[ReleaseApprovalAuditEvent, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ReleaseApprovalAuditIntegrityError("forced post-insert verification failure")
        return real_verify(connection)

    monkeypatch.setattr(audit_module, "_verify_connection", fail_second_verification)
    with pytest.raises(ReleaseApprovalAuditIntegrityError, match="forced post-insert"):
        _append(tmp_path)

    monkeypatch.setattr(audit_module, "_verify_connection", real_verify)
    assert verify_release_approval_history(tmp_path) == ()
