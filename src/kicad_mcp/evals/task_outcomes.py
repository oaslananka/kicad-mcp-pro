"""Versioned evidence contracts for end-to-end PCB task outcomes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence_sanitization import validate_sanitized_evidence

TASK_OUTCOME_SCHEMA_VERSION = "pcb-task-outcome.v1"

AttemptClassification = Literal[
    "success",
    "task_failure",
    "recovery_failure",
    "provider_failure",
    "tool_failure",
    "infrastructure_invalid",
]
FailureCategory = Literal[
    "design",
    "recovery",
    "provider",
    "tool",
    "infrastructure",
    "unclassified_failure",
]
TaskStage = Literal[
    "requirements",
    "schematic",
    "erc",
    "pcb",
    "drc",
    "constraints",
    "manufacturing_generation",
    "manufacturing_reproducibility",
    "parse_reopen",
]
StageRequirement = Literal["required", "not_applicable"]

ALL_TASK_STAGES: tuple[TaskStage, ...] = (
    "requirements",
    "schematic",
    "erc",
    "pcb",
    "drc",
    "constraints",
    "manufacturing_generation",
    "manufacturing_reproducibility",
    "parse_reopen",
)


class _EvidenceModel(BaseModel):
    """Strict immutable base for publishable task-outcome evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceSufficiencyContract(_EvidenceModel):
    """Predeclared evidence minima for a benchmark-suite version."""

    minimum_valid_attempts: int = Field(ge=1)
    minimum_valid_attempts_by_task_class: dict[str, int] = Field(default_factory=dict)
    minimum_recovery_required_mutations: int = Field(ge=0)
    minimum_drc_required_tasks: int = Field(ge=0)
    minimum_manufacturing_release_tasks: int = Field(ge=0)
    confidence_level: float = Field(default=0.95, ge=0.95, le=0.95)
    interval_method: Literal["wilson"] = "wilson"

    @model_validator(mode="after")
    def _validate_class_minima(self) -> EvidenceSufficiencyContract:
        if any(value < 1 for value in self.minimum_valid_attempts_by_task_class.values()):
            raise ValueError("per-task-class evidence minima must be at least 1")
        return self


class TaskContract(_EvidenceModel):
    """Versioned task definition with explicit v1 stage applicability."""

    task_id: str = Field(min_length=1)
    task_class: str = Field(min_length=1)
    version: str = Field(min_length=1)
    stage_requirements: dict[TaskStage, StageRequirement]

    @model_validator(mode="after")
    def _require_all_stage_declarations(self) -> TaskContract:
        if set(self.stage_requirements) != set(ALL_TASK_STAGES):
            raise ValueError("task contract stage requirements must declare every v1 stage")
        return self


class BenchmarkContract(_EvidenceModel):
    """Strict v1 benchmark contract for task-outcome evidence."""

    schema_version: Literal["pcb-task-outcome.v1"] = TASK_OUTCOME_SCHEMA_VERSION
    benchmark_id: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    tasks: tuple[TaskContract, ...]
    evidence_sufficiency: EvidenceSufficiencyContract

    @model_validator(mode="after")
    def _validate_tasks(self) -> BenchmarkContract:
        if not self.tasks:
            raise ValueError("benchmark contract must define at least one task")
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("benchmark contract task ids must be unique")
        return self


class TimingEvidence(_EvidenceModel):
    """Bounded wall-clock evidence for one attempt."""

    started_at: datetime
    ended_at: datetime

    @model_validator(mode="after")
    def _validate_timing(self) -> TimingEvidence:
        if self.started_at.utcoffset() is None or self.ended_at.utcoffset() is None:
            raise ValueError("attempt timestamps must be timezone-aware")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self


class StageEvidence(_EvidenceModel):
    """Outcome for one declared task stage."""

    stage: TaskStage
    outcome: Literal["passed", "failed", "not_applicable"]


class ValidationEvidence(_EvidenceModel):
    """Execution and disposition evidence for ERC or DRC."""

    kind: Literal["erc", "drc"]
    required: bool
    execution_attempted: bool
    execution_completed: bool
    result_consumed: bool
    disposition: Literal["resolved", "accepted", "blocking", "exception", "not_applicable"]
    exception_reason_code: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )

    @model_validator(mode="after")
    def _validate_execution_state(self) -> ValidationEvidence:
        if self.execution_completed and not self.execution_attempted:
            raise ValueError("completed validation requires an attempted execution")
        if self.result_consumed and not self.execution_completed:
            raise ValueError("consumed validation requires a completed execution")
        if self.disposition == "exception" and not self.exception_reason_code:
            raise ValueError("validation exception requires a reason code")
        if self.exception_reason_code is not None and self.disposition != "exception":
            raise ValueError("validation exception reason requires exception disposition")
        return self


class MutationEvidence(_EvidenceModel):
    """Normalized recovery and integrity evidence for one mutation."""

    mutation_id: str = Field(min_length=1, max_length=128)
    recovery_required: bool
    recovery_succeeded: bool | None = None
    duplicate_application_detected: bool = False
    state_divergence_detected: bool = False
    corruption_detected: bool = False
    final_state_verified: bool


class ManufacturingEvidence(_EvidenceModel):
    """Generation and reproducibility evidence for release artifacts."""

    required: bool
    generation_completed: bool
    regeneration_completed: bool
    comparison: Literal["byte_identical", "normalized_equivalent", "divergent", "not_run"]
    artifact_manifest_digest: str | None = Field(default=None, min_length=1, max_length=256)
    normalization_rules_version: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _validate_comparison_state(self) -> ManufacturingEvidence:
        if self.comparison != "not_run" and not (
            self.generation_completed and self.regeneration_completed
        ):
            raise ValueError("manufacturing comparison requires two completed generations")
        if self.comparison == "normalized_equivalent" and not self.normalization_rules_version:
            raise ValueError("normalized comparison requires a normalization rules version")
        return self


class AttemptRecord(_EvidenceModel):
    """Strict sanitized-input shape for one complete benchmark attempt."""

    schema_version: Literal["pcb-task-outcome.v1"] = TASK_OUTCOME_SCHEMA_VERSION
    attempt_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    task_class: str = Field(min_length=1, max_length=128)
    task_contract_version: str = Field(min_length=1, max_length=128)
    benchmark_id: str = Field(min_length=1, max_length=128)
    benchmark_version: str = Field(min_length=1, max_length=128)
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    kicad_version: str = Field(min_length=1, max_length=128)
    toolchain_contract: str = Field(min_length=1, max_length=256)
    agent: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    mcp_profile: str = Field(min_length=1, max_length=128)
    operating_mode: str = Field(min_length=1, max_length=128)
    starting_state_digest: str = Field(min_length=1, max_length=256)
    timing: TimingEvidence
    classification: AttemptClassification
    failure_category: FailureCategory | None = None
    failure_reason_code: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )
    retry_count: int = Field(ge=0)
    start_state: Literal["clean", "recovered"]
    manual_repair: bool
    stages: tuple[StageEvidence, ...]
    validations: tuple[ValidationEvidence, ...] = ()
    mutations: tuple[MutationEvidence, ...] = ()
    manufacturing: ManufacturingEvidence | None = None

    @model_validator(mode="after")
    def _validate_record(self) -> AttemptRecord:
        stage_names = [item.stage for item in self.stages]
        validation_kinds = [item.kind for item in self.validations]
        mutation_ids = [item.mutation_id for item in self.mutations]
        if len(stage_names) != len(set(stage_names)):
            raise ValueError("attempt stages must be unique")
        if len(validation_kinds) != len(set(validation_kinds)):
            raise ValueError("attempt validation kinds must be unique")
        if len(mutation_ids) != len(set(mutation_ids)):
            raise ValueError("attempt mutation ids must be unique")

        allowed_categories: dict[str, set[str]] = {
            "task_failure": {"design", "unclassified_failure"},
            "recovery_failure": {"recovery"},
            "provider_failure": {"provider"},
            "tool_failure": {"tool"},
            "infrastructure_invalid": {"infrastructure"},
        }
        if self.classification == "success":
            if self.failure_category is not None or self.failure_reason_code is not None:
                raise ValueError("success attempt cannot carry failure metadata")
            return self

        if self.failure_category not in allowed_categories[self.classification]:
            raise ValueError(
                f"{self.classification} has incompatible failure category {self.failure_category!r}"
            )
        if self.failure_reason_code is None:
            raise ValueError("failed attempt requires a failure reason code")
        return self


def parse_benchmark_contract(payload: Mapping[str, object]) -> BenchmarkContract:
    """Parse one strict v1 benchmark contract mapping."""
    return BenchmarkContract.model_validate(payload)


def parse_attempt_record(payload: Mapping[str, object]) -> AttemptRecord:
    """Parse one strict v1 attempt evidence mapping."""
    return AttemptRecord.model_validate(payload)


def _render_evidence(value: BaseModel) -> str:
    payload = value.model_dump(mode="json", exclude_none=True)
    validate_sanitized_evidence(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def render_benchmark_contract(contract: BenchmarkContract) -> str:
    """Render one benchmark contract as deterministic sanitized JSON."""
    return _render_evidence(contract)


def render_attempt_record(record: AttemptRecord) -> str:
    """Render one attempt record as deterministic sanitized JSON."""
    return _render_evidence(record)
