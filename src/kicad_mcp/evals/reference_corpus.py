"""Publication contracts for complete real-board reference-corpus evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .evidence_sanitization import validate_sanitized_evidence
from .reference_board_quality import (
    BoardQualityContract,
    parse_quality_contract,
    parse_quality_score,
    score_reference_board_attempt,
)
from .task_outcome_scoring import (
    TaskOutcomeScoringError,
    TaskOutcomeSummary,
    aggregate_task_outcomes,
)
from .task_outcomes import (
    AttemptRecord,
    BenchmarkContract,
    parse_attempt_record,
    parse_benchmark_contract,
)

REFERENCE_BOARD_SCHEMA_VERSION: Literal["pcb-reference-board.v1"] = "pcb-reference-board.v1"
REFERENCE_AGENT_LOG_SCHEMA_VERSION: Literal["pcb-reference-agent-log.v1"] = (
    "pcb-reference-agent-log.v1"
)
REFERENCE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
SPECIFICATION_FILE = "specification.md"
ORIGINAL_PROMPT_FILE = "original-prompt.md"
BENCHMARK_FILE = "benchmark.json"
QUALITY_GATES_FILE = "quality-gates.json"
QUALITY_SCORE_FILE = "board-quality-score.json"
ATTEMPT_MANIFEST_FILE = "attempt-manifest.json"
ATTEMPT_RECORD_FILE = "attempt.json"
AGENT_LOG_FILE = "agent-log.jsonl"
ATTEMPTS_DIRECTORY = "attempts"

ScalarDetail = str | int | float | bool | None


class ReferenceCorpusError(ValueError):
    """Raised when publishable reference-corpus evidence violates its contract."""


class _ReferenceEvidenceModel(BaseModel):
    """Strict immutable base for publishable reference-corpus metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReferenceAttemptEntry(_ReferenceEvidenceModel):
    """One manifest entry mapping an attempt id to its canonical directory."""

    attempt_id: str = Field(pattern=REFERENCE_IDENTIFIER_PATTERN)
    directory: str = Field(min_length=1, max_length=512)
    evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_canonical_directory(self) -> ReferenceAttemptEntry:
        if self.directory != f"attempts/{self.attempt_id}":
            raise ValueError("attempt directory must use canonical attempts/<attempt-id> form")
        return self


class ReferenceBoardManifest(_ReferenceEvidenceModel):
    """Strict publication ledger for one maintained reference board."""

    schema_version: Literal["pcb-reference-board.v1"] = REFERENCE_BOARD_SCHEMA_VERSION
    board_id: str = Field(pattern=REFERENCE_IDENTIFIER_PATTERN)
    benchmark_id: str = Field(min_length=1, max_length=128)
    benchmark_version: str = Field(min_length=1, max_length=128)
    reference_inputs_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    attempts: tuple[ReferenceAttemptEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_unique_attempt_entries(self) -> ReferenceBoardManifest:
        attempt_ids = [entry.attempt_id for entry in self.attempts]
        directories = [entry.directory for entry in self.attempts]
        if len(attempt_ids) != len(set(attempt_ids)) or len(directories) != len(set(directories)):
            raise ValueError("reference manifest attempt ids and directories must be unique")
        return self


class ReferenceAgentLogEvent(_ReferenceEvidenceModel):
    """One sanitized ordered event in a publishable agent action log."""

    schema_version: Literal["pcb-reference-agent-log.v1"] = REFERENCE_AGENT_LOG_SCHEMA_VERSION
    attempt_id: str = Field(pattern=REFERENCE_IDENTIFIER_PATTERN)
    sequence: int = Field(ge=1)
    timestamp: datetime
    event_type: Literal["agent", "tool_call", "tool_result", "workflow", "validation", "recovery"]
    name: str = Field(min_length=1, max_length=128)
    status: Literal["started", "completed", "failed", "observed"]
    details: dict[str, ScalarDetail] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_publishable_event(self) -> ReferenceAgentLogEvent:
        if self.timestamp.utcoffset() is None:
            raise ValueError("reference agent log timestamps must be timezone-aware")
        validate_sanitized_evidence(self.model_dump(mode="json"))
        return self


@dataclass(frozen=True, slots=True)
class ValidatedReferenceBoardBundle:
    """Validated reference-board publication evidence and canonical aggregate."""

    root: Path
    manifest: ReferenceBoardManifest
    contract: BenchmarkContract
    attempts: tuple[AttemptRecord, ...]
    summary: TaskOutcomeSummary


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReferenceCorpusError("attempt evidence file must be readable") from exc
    return digest.hexdigest()


def compute_reference_inputs_digest(root: Path) -> str:
    """Return the deterministic digest for canonical reference-board inputs."""
    input_files = (SPECIFICATION_FILE, ORIGINAL_PROMPT_FILE, BENCHMARK_FILE, QUALITY_GATES_FILE)
    tree_digest = hashlib.sha256()
    for name in input_files:
        path = root / name
        _require_regular_file(path, name)
        tree_digest.update(name.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(_sha256_file(path).encode("ascii"))
        tree_digest.update(b"\n")
    return f"sha256:{tree_digest.hexdigest()}"


def compute_attempt_evidence_digest(attempt_dir: Path) -> str:
    """Return a deterministic digest for one complete attempt evidence tree."""
    if attempt_dir.is_symlink() or not attempt_dir.is_dir():
        raise ReferenceCorpusError("attempt evidence root must be a real directory")

    files: list[Path] = []
    for path in attempt_dir.rglob("*"):
        if path.is_symlink():
            raise ReferenceCorpusError("attempt evidence tree must not contain symlinks")
        if path.is_file():
            files.append(path)
        elif not path.is_dir():
            raise ReferenceCorpusError(
                "attempt evidence tree contains unsupported filesystem entry"
            )

    tree_digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(attempt_dir).as_posix()):
        relative = path.relative_to(attempt_dir).as_posix()
        tree_digest.update(relative.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(_sha256_file(path).encode("ascii"))
        tree_digest.update(b"\n")
    return f"sha256:{tree_digest.hexdigest()}"


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReferenceCorpusError(f"{label} must be readable valid JSON") from exc
    if not isinstance(payload, dict):
        raise ReferenceCorpusError(f"{label} must contain one JSON object")
    try:
        validate_sanitized_evidence(payload)
    except ValueError as exc:
        raise ReferenceCorpusError(f"{label} contains unsafe evidence") from exc
    return payload


def _require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ReferenceCorpusError(f"{label} must not be a symlink")
    if not path.is_file():
        raise ReferenceCorpusError(f"{label} is required")


def _require_sanitized_text_file(path: Path, label: str) -> None:
    _require_regular_file(path, label)
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReferenceCorpusError(f"{label} must be readable UTF-8 text") from exc
    try:
        validate_sanitized_evidence(content)
    except ValueError as exc:
        raise ReferenceCorpusError(f"{label} contains unsafe evidence") from exc


def _parse_agent_log(path: Path, expected_attempt_id: str) -> tuple[ReferenceAgentLogEvent, ...]:
    _require_regular_file(path, "agent log")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReferenceCorpusError("agent log must be readable") from exc
    if not lines:
        raise ReferenceCorpusError("agent log must contain at least one event")

    events: list[ReferenceAgentLogEvent] = []
    previous_timestamp: datetime | None = None
    for expected_sequence, line in enumerate(lines, start=1):
        if not line.strip():
            raise ReferenceCorpusError("agent log must not contain blank events")
        try:
            payload = json.loads(line)
            event = ReferenceAgentLogEvent.model_validate(payload)
        except ValueError as exc:
            raise ReferenceCorpusError(
                "agent log contains invalid or unsafe event evidence"
            ) from exc
        if event.attempt_id != expected_attempt_id:
            raise ReferenceCorpusError("agent log attempt identity does not match attempt.json")
        if event.sequence != expected_sequence:
            raise ReferenceCorpusError("agent log sequence must be contiguous from 1")
        if previous_timestamp is not None and event.timestamp < previous_timestamp:
            raise ReferenceCorpusError("agent log timestamps must be nondecreasing")
        previous_timestamp = event.timestamp
        events.append(event)
    return tuple(events)


def _required_validation_kinds(
    contract: BenchmarkContract, record: AttemptRecord
) -> tuple[str, ...]:
    task = next((item for item in contract.tasks if item.task_id == record.task_id), None)
    if task is None:
        return ()
    return tuple(kind for kind in ("erc", "drc") if task.stage_requirements[kind] == "required")


def _validate_required_validation_evidence(
    contract: BenchmarkContract, record: AttemptRecord
) -> None:
    if record.classification == "infrastructure_invalid":
        return
    present = {item.kind for item in record.validations}
    for kind in _required_validation_kinds(contract, record):
        if kind not in present:
            raise ReferenceCorpusError(
                f"attempt {record.attempt_id} is missing required {kind} validation evidence"
            )


def _validate_success_artifacts(
    attempt_dir: Path, contract: BenchmarkContract, record: AttemptRecord
) -> None:
    if record.classification != "success":
        return
    if record.manual_repair:
        raise ReferenceCorpusError(
            f"attempt {record.attempt_id} cannot publish success after manual repair"
        )

    required_files = [
        "schematic.kicad_sch",
        "board.kicad_pcb",
        "BOM.csv",
        "manufacturing-report.md",
    ]
    required_files.extend(
        f"{kind.upper()}.txt" for kind in _required_validation_kinds(contract, record)
    )
    for name in required_files:
        _require_sanitized_text_file(attempt_dir / name, name)

    gerbers = attempt_dir / "Gerbers"
    if gerbers.is_symlink():
        raise ReferenceCorpusError("Gerbers must not be a symlink")
    if not gerbers.is_dir():
        raise ReferenceCorpusError("Gerbers directory is required")
    entries = list(gerbers.iterdir())
    if any(entry.is_symlink() for entry in entries):
        raise ReferenceCorpusError("Gerbers must not contain symlinked evidence")
    if not any(entry.is_file() for entry in entries):
        raise ReferenceCorpusError("Gerbers must contain at least one regular file")


def _load_attempt(attempt_dir: Path) -> AttemptRecord:
    attempt_path = attempt_dir / ATTEMPT_RECORD_FILE
    _require_regular_file(attempt_path, ATTEMPT_RECORD_FILE)
    payload = _read_json_object(attempt_path, ATTEMPT_RECORD_FILE)
    try:
        return parse_attempt_record(payload)
    except ValidationError as exc:
        raise ReferenceCorpusError("attempt.json violates pcb-task-outcome.v1") from exc


def _resolve_bundle_root(root: Path) -> Path:
    if root.is_symlink():
        raise ReferenceCorpusError("reference-board bundle root must not be a symlink")
    if not root.is_dir():
        raise ReferenceCorpusError("reference-board bundle root must be a directory")
    return root.resolve()


def _load_reference_contracts(
    root: Path,
) -> tuple[ReferenceBoardManifest, BenchmarkContract, BoardQualityContract]:
    for name in (SPECIFICATION_FILE, ORIGINAL_PROMPT_FILE):
        _require_sanitized_text_file(root / name, name)
    for name in (BENCHMARK_FILE, QUALITY_GATES_FILE, ATTEMPT_MANIFEST_FILE):
        _require_regular_file(root / name, name)

    try:
        manifest = ReferenceBoardManifest.model_validate(
            _read_json_object(root / ATTEMPT_MANIFEST_FILE, ATTEMPT_MANIFEST_FILE)
        )
        contract = parse_benchmark_contract(
            _read_json_object(root / BENCHMARK_FILE, BENCHMARK_FILE)
        )
        quality = parse_quality_contract(
            _read_json_object(root / QUALITY_GATES_FILE, QUALITY_GATES_FILE)
        )
    except ValidationError as exc:
        raise ReferenceCorpusError(
            "reference-board manifest, benchmark, or quality contract is invalid"
        ) from exc

    if (manifest.benchmark_id, manifest.benchmark_version) != (
        contract.benchmark_id,
        contract.benchmark_version,
    ):
        raise ReferenceCorpusError(
            "reference manifest benchmark identity does not match benchmark.json"
        )
    if (quality.board_id, quality.benchmark_version) != (
        manifest.board_id,
        manifest.benchmark_version,
    ):
        raise ReferenceCorpusError("quality gate identity does not match reference manifest")
    if compute_reference_inputs_digest(root) != manifest.reference_inputs_digest:
        raise ReferenceCorpusError(
            "reference input digest does not match specification, prompt, "
            "benchmark, and quality gates"
        )
    return manifest, contract, quality


def _validate_attempt_directory_index(root: Path, manifest: ReferenceBoardManifest) -> None:
    attempts_dir = root / ATTEMPTS_DIRECTORY
    if attempts_dir.is_symlink():
        raise ReferenceCorpusError("attempts directory must not be a symlink")
    if not attempts_dir.is_dir():
        raise ReferenceCorpusError("attempts directory is required")

    actual_dirs: set[str] = set()
    for entry in attempts_dir.iterdir():
        if entry.is_symlink():
            raise ReferenceCorpusError("attempt directories must not be symlinks")
        if entry.is_dir():
            actual_dirs.add(entry.name)
    manifest_dirs = {entry.attempt_id for entry in manifest.attempts}
    if actual_dirs != manifest_dirs:
        raise ReferenceCorpusError("manifest attempt directories do not match filesystem attempts")


def _validate_success_quality_score(
    root: Path,
    attempt_dir: Path,
    quality: BoardQualityContract,
    record: AttemptRecord,
) -> None:
    if record.classification != "success":
        return
    score_path = attempt_dir / QUALITY_SCORE_FILE
    _require_regular_file(score_path, QUALITY_SCORE_FILE)
    try:
        score = parse_quality_score(_read_json_object(score_path, QUALITY_SCORE_FILE))
    except ValidationError as exc:
        raise ReferenceCorpusError("board-quality-score.json is invalid") from exc

    if (score.board_id, score.benchmark_version, score.attempt_id, score.source_revision) != (
        quality.board_id,
        quality.benchmark_version,
        record.attempt_id,
        record.source_revision,
    ):
        raise ReferenceCorpusError("quality score identity does not match attempt evidence")
    expected_rules = [(rule.id, rule.type) for rule in quality.rules]
    actual_rules = [(result.id, result.type) for result in score.results]
    if actual_rules != expected_rules:
        raise ReferenceCorpusError("quality score rule set does not match quality-gates.json")
    if not score.overall_pass:
        raise ReferenceCorpusError("quality score must pass for declared success")
    recomputed = score_reference_board_attempt(root, record.attempt_id)
    if score != recomputed:
        raise ReferenceCorpusError("quality score does not match deterministic scorer output")


def _load_reference_attempt(
    root: Path,
    manifest_entry: ReferenceAttemptEntry,
    contract: BenchmarkContract,
    quality: BoardQualityContract,
) -> AttemptRecord:
    attempt_dir = root / manifest_entry.directory
    if attempt_dir.is_symlink() or not attempt_dir.is_dir():
        raise ReferenceCorpusError(
            f"attempt directory {manifest_entry.directory} must be a real directory"
        )

    record = _load_attempt(attempt_dir)
    if record.attempt_id != manifest_entry.attempt_id:
        raise ReferenceCorpusError("attempt id does not match reference manifest")
    if (record.benchmark_id, record.benchmark_version) != (
        contract.benchmark_id,
        contract.benchmark_version,
    ):
        raise ReferenceCorpusError("attempt benchmark identity does not match benchmark.json")

    _parse_agent_log(attempt_dir / AGENT_LOG_FILE, record.attempt_id)
    _validate_required_validation_evidence(contract, record)
    _validate_success_artifacts(attempt_dir, contract, record)
    _validate_success_quality_score(root, attempt_dir, quality, record)
    if compute_attempt_evidence_digest(attempt_dir) != manifest_entry.evidence_digest:
        raise ReferenceCorpusError(
            f"attempt {manifest_entry.attempt_id} evidence digest does not match filesystem"
        )
    return record


def validate_reference_board_bundle(root: Path) -> ValidatedReferenceBoardBundle:
    """Validate one complete reference-board publication bundle fail closed."""
    root = _resolve_bundle_root(root)
    manifest, contract, quality = _load_reference_contracts(root)
    _validate_attempt_directory_index(root, manifest)
    records = [
        _load_reference_attempt(root, manifest_entry, contract, quality)
        for manifest_entry in manifest.attempts
    ]

    try:
        summary = aggregate_task_outcomes(contract, records)
    except TaskOutcomeScoringError as exc:
        raise ReferenceCorpusError(
            f"reference-board attempts do not match benchmark contract: {exc}"
        ) from exc

    declared_successes = sum(record.classification == "success" for record in records)
    if summary.successful_attempts != declared_successes:
        raise ReferenceCorpusError(
            "declared success attempts must satisfy canonical task-outcome quality gates"
        )
    return ValidatedReferenceBoardBundle(
        root=root,
        manifest=manifest,
        contract=contract,
        attempts=tuple(records),
        summary=summary,
    )
