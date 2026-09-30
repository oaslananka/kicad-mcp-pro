"""Append-only approval and waiver audit history for release evidence v1."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, field_validator

from .evidence_freshness import EvidenceRecord, EvidenceRecordKind
from .hardware_intent_contract import StrictContractModel
from .release_evidence_store import RELEASE_EVIDENCE_DIRNAME

RELEASE_APPROVAL_AUDIT_FILENAME = "release_approval_history-v1.db"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ReleaseApprovalAuditDecision(StrEnum):
    APPROVAL = "approval"
    WAIVER = "waiver"


class ReleaseApprovalAuditEvent(StrictContractModel):
    """One immutable human-decision event bound to an exact evidence snapshot."""

    schema_version: Literal[1]
    sequence: int = Field(ge=1)
    decision: ReleaseApprovalAuditDecision
    project_key: str = Field(min_length=1, max_length=128)
    contract_id: str = Field(min_length=3, max_length=120)
    contract_version: int = Field(ge=1)
    evidence_id: str = Field(min_length=3, max_length=128)
    evidence_sha256: str = Field(pattern=_SHA256_PATTERN)
    evidence_record: EvidenceRecord
    actor: str = Field(min_length=1, max_length=256)
    scope: str = Field(min_length=1, max_length=256)
    rationale: str = Field(min_length=1, max_length=2000)
    recorded_at: datetime
    previous_event_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    event_sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("recorded_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("recorded_at must carry explicit UTC timezone")
        return value


class ReleaseApprovalAuditIntegrityError(ValueError):
    """Raised when persisted append-only history fails integrity verification."""


def release_approval_audit_path(project_dir: Path) -> Path:
    return project_dir / RELEASE_EVIDENCE_DIRNAME / RELEASE_APPROVAL_AUDIT_FILENAME


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _timestamp(value: datetime) -> str:
    if value.utcoffset() != timedelta(0):
        raise ValueError("recorded_at must carry explicit UTC timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_evidence_record_json(record: EvidenceRecord) -> str:
    return _canonical_json(record.model_dump(mode="json"))


def evidence_record_sha256(record: EvidenceRecord) -> str:
    encoded = canonical_evidence_record_json(record).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decision_for_record(record: EvidenceRecord) -> ReleaseApprovalAuditDecision:
    if record.kind is EvidenceRecordKind.APPROVAL:
        return ReleaseApprovalAuditDecision.APPROVAL
    if record.kind is EvidenceRecordKind.WAIVER:
        return ReleaseApprovalAuditDecision.WAIVER
    raise ValueError("audit history accepts only approval or waiver EvidenceRecord values")


def _event_hash_payload(
    *,
    sequence: int,
    decision: ReleaseApprovalAuditDecision,
    project_key: str,
    contract_id: str,
    contract_version: int,
    evidence_id: str,
    evidence_sha256: str,
    evidence_record_json: str,
    actor: str,
    scope: str,
    rationale: str,
    recorded_at: str,
    previous_event_sha256: str | None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "sequence": sequence,
        "decision": decision.value,
        "project_key": project_key,
        "contract_id": contract_id,
        "contract_version": contract_version,
        "evidence_id": evidence_id,
        "evidence_sha256": evidence_sha256,
        "evidence_record_json": evidence_record_json,
        "actor": actor,
        "scope": scope,
        "rationale": rationale,
        "recorded_at": recorded_at,
        "previous_event_sha256": previous_event_sha256,
    }


def _event_sha256(**payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS release_approval_events (
            sequence INTEGER PRIMARY KEY,
            schema_version INTEGER NOT NULL CHECK (schema_version = 1),
            decision TEXT NOT NULL CHECK (decision IN ('approval', 'waiver')),
            project_key TEXT NOT NULL,
            contract_id TEXT NOT NULL,
            contract_version INTEGER NOT NULL CHECK (contract_version >= 1),
            evidence_id TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            evidence_record_json TEXT NOT NULL,
            actor TEXT NOT NULL,
            scope TEXT NOT NULL,
            rationale TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            previous_event_sha256 TEXT,
            event_sha256 TEXT NOT NULL UNIQUE
        );
        CREATE TRIGGER IF NOT EXISTS release_approval_events_no_update
        BEFORE UPDATE ON release_approval_events
        BEGIN
            SELECT RAISE(ABORT, 'release approval history is append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS release_approval_events_no_delete
        BEFORE DELETE ON release_approval_events
        BEGIN
            SELECT RAISE(ABORT, 'release approval history is append-only');
        END;
        """
    )
    return connection


def _rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(connection.execute("SELECT * FROM release_approval_events ORDER BY sequence"))


def _event_from_row(row: sqlite3.Row, expected_previous: str | None) -> ReleaseApprovalAuditEvent:
    sequence = int(row["sequence"])
    decision = ReleaseApprovalAuditDecision(str(row["decision"]))
    evidence_json = str(row["evidence_record_json"])
    try:
        evidence_payload = json.loads(evidence_json)
        record = EvidenceRecord.model_validate(evidence_payload)
    except ValueError as exc:
        raise ReleaseApprovalAuditIntegrityError(
            f"invalid embedded evidence at sequence {sequence}: {exc}"
        ) from exc

    canonical_json = canonical_evidence_record_json(record)
    digest = evidence_record_sha256(record)
    if canonical_json != evidence_json or digest != str(row["evidence_sha256"]):
        raise ReleaseApprovalAuditIntegrityError(
            f"evidence snapshot digest mismatch at sequence {sequence}"
        )
    if _decision_for_record(record) is not decision:
        raise ReleaseApprovalAuditIntegrityError(
            f"evidence kind does not match decision at sequence {sequence}"
        )
    record_binding = (
        record.project_key,
        record.contract_id,
        record.contract_version,
        record.evidence_id,
    )
    row_binding = (
        row["project_key"],
        row["contract_id"],
        row["contract_version"],
        row["evidence_id"],
    )
    if record_binding != row_binding:
        raise ReleaseApprovalAuditIntegrityError(
            f"evidence binding mismatch at sequence {sequence}"
        )
    previous = row["previous_event_sha256"]
    if previous != expected_previous:
        raise ReleaseApprovalAuditIntegrityError(
            f"event chain predecessor mismatch at sequence {sequence}"
        )

    payload = _event_hash_payload(
        sequence=sequence,
        decision=decision,
        project_key=str(row["project_key"]),
        contract_id=str(row["contract_id"]),
        contract_version=int(row["contract_version"]),
        evidence_id=str(row["evidence_id"]),
        evidence_sha256=digest,
        evidence_record_json=evidence_json,
        actor=str(row["actor"]),
        scope=str(row["scope"]),
        rationale=str(row["rationale"]),
        recorded_at=str(row["recorded_at"]),
        previous_event_sha256=previous,
    )
    event_hash = _event_sha256(**payload)
    if event_hash != row["event_sha256"]:
        raise ReleaseApprovalAuditIntegrityError(f"event hash mismatch at sequence {sequence}")
    try:
        recorded_at = datetime.fromisoformat(str(row["recorded_at"]).replace("Z", "+00:00"))
        return ReleaseApprovalAuditEvent(
            schema_version=1,
            sequence=sequence,
            decision=decision,
            project_key=str(row["project_key"]),
            contract_id=str(row["contract_id"]),
            contract_version=int(row["contract_version"]),
            evidence_id=str(row["evidence_id"]),
            evidence_sha256=digest,
            evidence_record=record,
            actor=str(row["actor"]),
            scope=str(row["scope"]),
            rationale=str(row["rationale"]),
            recorded_at=recorded_at,
            previous_event_sha256=previous,
            event_sha256=event_hash,
        )
    except ValueError as exc:
        raise ReleaseApprovalAuditIntegrityError(
            f"invalid audit event at sequence {sequence}: {exc}"
        ) from exc


def _verify_connection(connection: sqlite3.Connection) -> tuple[ReleaseApprovalAuditEvent, ...]:
    events: list[ReleaseApprovalAuditEvent] = []
    previous_hash: str | None = None
    expected_sequence = 1
    for row in _rows(connection):
        if int(row["sequence"]) != expected_sequence:
            raise ReleaseApprovalAuditIntegrityError(
                f"audit sequence gap: expected {expected_sequence}, got {row['sequence']}"
            )
        event = _event_from_row(row, previous_hash)
        events.append(event)
        previous_hash = event.event_sha256
        expected_sequence += 1
    return tuple(events)


def verify_release_approval_history(project_dir: Path) -> tuple[ReleaseApprovalAuditEvent, ...]:
    path = release_approval_audit_path(project_dir)
    if not path.is_file():
        return ()
    connection = _connect(path)
    try:
        return _verify_connection(connection)
    finally:
        connection.close()


def append_release_approval_event(
    project_dir: Path,
    *,
    evidence_record: EvidenceRecord,
    actor: str,
    scope: str,
    rationale: str,
    recorded_at: datetime | None = None,
) -> ReleaseApprovalAuditEvent:
    """Append one exact evidence-bound human decision after verifying prior history."""
    decision = _decision_for_record(evidence_record)
    actor = actor.strip()
    scope = scope.strip()
    rationale = rationale.strip()
    if not actor or not scope or not rationale:
        raise ValueError("actor, scope, and rationale must be non-empty")
    moment = recorded_at or datetime.now(UTC)
    recorded_text = _timestamp(moment)
    evidence_json = canonical_evidence_record_json(evidence_record)
    evidence_digest = evidence_record_sha256(evidence_record)
    contract_id = cast(str, evidence_record.contract_id)
    contract_version = cast(int, evidence_record.contract_version)

    path = release_approval_audit_path(project_dir)
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        events = _verify_connection(connection)
        sequence = len(events) + 1
        previous_hash = events[-1].event_sha256 if events else None
        payload = _event_hash_payload(
            sequence=sequence,
            decision=decision,
            project_key=evidence_record.project_key,
            contract_id=contract_id,
            contract_version=contract_version,
            evidence_id=evidence_record.evidence_id,
            evidence_sha256=evidence_digest,
            evidence_record_json=evidence_json,
            actor=actor,
            scope=scope,
            rationale=rationale,
            recorded_at=recorded_text,
            previous_event_sha256=previous_hash,
        )
        event_hash = _event_sha256(**payload)
        connection.execute(
            """
            INSERT INTO release_approval_events (
                sequence, schema_version, decision, project_key, contract_id,
                contract_version, evidence_id, evidence_sha256, evidence_record_json,
                actor, scope, rationale, recorded_at, previous_event_sha256, event_sha256
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sequence,
                decision.value,
                evidence_record.project_key,
                contract_id,
                contract_version,
                evidence_record.evidence_id,
                evidence_digest,
                evidence_json,
                actor,
                scope,
                rationale,
                recorded_text,
                previous_hash,
                event_hash,
            ),
        )
        event = _verify_connection(connection)[-1]
        connection.commit()
        return event
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
