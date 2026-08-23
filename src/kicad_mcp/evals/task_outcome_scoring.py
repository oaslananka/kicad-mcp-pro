"""Pure scoring for versioned end-to-end PCB task outcome evidence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from math import sqrt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .task_outcomes import (
    AttemptRecord,
    BenchmarkContract,
    TaskContract,
    ValidationEvidence,
    ValidationKind,
)

TASK_OUTCOME_SUMMARY_SCHEMA_VERSION: Literal["pcb-task-outcome-summary.v1"] = (
    "pcb-task-outcome-summary.v1"
)

TargetStatus = Literal["met", "not_met", "insufficient_evidence"]

_WILSON_Z_95 = 1.959963984540054
_TASK_SUCCESS_TARGET = 0.95
_MUTATION_RECOVERY_TARGET = 0.99
_DRC_EXECUTION_TARGET = 1.0
_MANUFACTURING_REPRODUCIBILITY_TARGET = 1.0


class TaskOutcomeScoringError(ValueError):
    """Raised when attempts cannot be scored against the benchmark contract."""


class _SummaryModel(BaseModel):
    """Strict immutable base for deterministic task-outcome summaries."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class WilsonInterval(_SummaryModel):
    """Two-sided 95% Wilson score interval for one rate metric."""

    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)


class RateKpi(_SummaryModel):
    """One rate KPI with explicit denominator, uncertainty, and target state."""

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_interval: WilsonInterval | None = None
    target: float = Field(ge=0.0, le=1.0)
    status: TargetStatus


class TaskOutcomeSummary(_SummaryModel):
    """Deterministic aggregate of complete task-outcome attempt evidence."""

    schema_version: Literal["pcb-task-outcome-summary.v1"] = TASK_OUTCOME_SUMMARY_SCHEMA_VERSION
    benchmark_id: str
    benchmark_version: str
    attempts_total: int = Field(ge=0)
    valid_attempts: int = Field(ge=0)
    infrastructure_invalid_attempts: int = Field(ge=0)
    successful_attempts: int = Field(ge=0)
    failed_attempts: int = Field(ge=0)
    failure_categories: dict[str, int]
    task_success: RateKpi
    mutation_attempts: int = Field(ge=0)
    recovery_required_mutations: int = Field(ge=0)
    successful_recoveries: int = Field(ge=0)
    mutation_recovery: RateKpi
    duplicate_application_incidents: int = Field(ge=0)
    state_divergence_incidents: int = Field(ge=0)
    file_corruption_incidents: int = Field(ge=0)
    file_corruption_status: TargetStatus
    drc_required_tasks: int = Field(ge=0)
    drc_executed_and_consumed_tasks: int = Field(ge=0)
    required_drc_execution: RateKpi
    manufacturing_release_tasks: int = Field(ge=0)
    manufacturing_reproducible_tasks: int = Field(ge=0)
    manufacturing_reproducibility: RateKpi


@dataclass(frozen=True, slots=True)
class _OutcomeCounts:
    successful_attempts: int
    failure_categories: Counter[str]


@dataclass(frozen=True, slots=True)
class _MutationCounts:
    mutation_attempts: int
    recovery_required_mutations: int
    successful_recoveries: int
    duplicate_application_incidents: int
    state_divergence_incidents: int
    file_corruption_incidents: int


@dataclass(frozen=True, slots=True)
class _ReleaseEvidenceCounts:
    drc_required_tasks: int
    drc_executed_and_consumed_tasks: int
    manufacturing_release_tasks: int
    manufacturing_reproducible_tasks: int


def _wilson_interval(numerator: int, denominator: int) -> WilsonInterval | None:
    if denominator == 0:
        return None
    proportion = numerator / denominator
    z_squared = _WILSON_Z_95 * _WILSON_Z_95
    scale = 1.0 + z_squared / denominator
    center = (proportion + z_squared / (2.0 * denominator)) / scale
    half_width = (
        _WILSON_Z_95
        * sqrt((proportion * (1.0 - proportion) + z_squared / (4.0 * denominator)) / denominator)
        / scale
    )
    return WilsonInterval(
        lower=max(0.0, center - half_width),
        upper=min(1.0, center + half_width),
    )


def _rate_kpi(
    *,
    numerator: int,
    denominator: int,
    target: float,
    sufficient: bool,
) -> RateKpi:
    rate = numerator / denominator if denominator else None
    if denominator == 0 or not sufficient:
        status: TargetStatus = "insufficient_evidence"
    elif rate is not None and rate >= target:
        status = "met"
    else:
        status = "not_met"
    return RateKpi(
        numerator=numerator,
        denominator=denominator,
        rate=rate,
        confidence_interval=_wilson_interval(numerator, denominator),
        target=target,
        status=status,
    )


def _task_map(contract: BenchmarkContract) -> dict[str, TaskContract]:
    return {task.task_id: task for task in contract.tasks}


def _validate_attempt_identity(
    contract: BenchmarkContract,
    task: TaskContract | None,
    record: AttemptRecord,
) -> TaskContract:
    if (
        record.benchmark_id != contract.benchmark_id
        or record.benchmark_version != contract.benchmark_version
    ):
        raise TaskOutcomeScoringError(
            f"Attempt {record.attempt_id!r} benchmark identity does not match contract."
        )
    if task is None:
        raise TaskOutcomeScoringError(
            f"Attempt {record.attempt_id!r} references unknown task {record.task_id!r}."
        )
    if record.task_class != task.task_class or record.task_contract_version != task.version:
        raise TaskOutcomeScoringError(
            f"Attempt {record.attempt_id!r} task identity does not match contract."
        )
    return task


def _validation_for(record: AttemptRecord, kind: ValidationKind) -> ValidationEvidence | None:
    return next((validation for validation in record.validations if validation.kind == kind), None)


def _required_validation_passes(
    task: TaskContract,
    record: AttemptRecord,
    kind: ValidationKind,
) -> bool:
    evidence = _validation_for(record, kind)
    if evidence is None or evidence.required is not True:
        return False
    if (
        evidence.execution_attempted
        and evidence.execution_completed
        and evidence.result_consumed
        and evidence.disposition in {"resolved", "accepted"}
    ):
        return True
    allowed_exceptions = task.validation_exception_reason_codes.get(kind, ())
    return (
        evidence.disposition == "exception"
        and evidence.exception_reason_code is not None
        and evidence.exception_reason_code in allowed_exceptions
    )


def _mutation_integrity_passes(record: AttemptRecord) -> bool:
    for mutation in record.mutations:
        if (
            mutation.duplicate_application_detected
            or mutation.state_divergence_detected
            or mutation.corruption_detected
            or not mutation.final_state_verified
        ):
            return False
        if mutation.recovery_required and mutation.recovery_succeeded is not True:
            return False
        if mutation.execution_state != "completed" and not mutation.recovery_required:
            return False
    return True


def _manufacturing_generation_passes(record: AttemptRecord) -> bool:
    evidence = record.manufacturing
    return evidence is not None and evidence.required and evidence.generation_completed


def _manufacturing_reproducible(record: AttemptRecord) -> bool:
    evidence = record.manufacturing
    return (
        evidence is not None
        and evidence.required
        and evidence.generation_completed
        and evidence.regeneration_completed
        and evidence.comparison in {"byte_identical", "normalized_equivalent"}
    )


def _attempt_succeeded(task: TaskContract, record: AttemptRecord) -> bool:
    if record.classification != "success" or record.manual_repair:
        return False

    stages = {evidence.stage: evidence.outcome for evidence in record.stages}
    for stage, requirement in task.stage_requirements.items():
        if requirement == "required" and stages.get(stage) != "passed":
            return False

    if task.stage_requirements["erc"] == "required" and not _required_validation_passes(
        task, record, "erc"
    ):
        return False
    if task.stage_requirements["drc"] == "required" and not _required_validation_passes(
        task, record, "drc"
    ):
        return False
    if not _mutation_integrity_passes(record):
        return False
    if task.stage_requirements[
        "manufacturing_generation"
    ] == "required" and not _manufacturing_generation_passes(record):
        return False
    if task.stage_requirements[
        "manufacturing_reproducibility"
    ] == "required" and not _manufacturing_reproducible(record):
        return False
    return True


def _global_evidence_sufficient(
    contract: BenchmarkContract,
    valid_records: list[AttemptRecord],
) -> bool:
    sufficiency = contract.evidence_sufficiency
    if len(valid_records) < sufficiency.minimum_valid_attempts:
        return False
    class_counts = Counter(record.task_class for record in valid_records)
    return all(
        class_counts[task_class] >= minimum
        for task_class, minimum in sufficiency.minimum_valid_attempts_by_task_class.items()
    )


def _recovery_succeeded(record: AttemptRecord, mutation_index: int) -> bool:
    mutation = record.mutations[mutation_index]
    return (
        mutation.recovery_required
        and mutation.recovery_succeeded is True
        and mutation.final_state_verified
        and not mutation.duplicate_application_detected
        and not mutation.state_divergence_detected
        and not mutation.corruption_detected
    )


def _validated_tasks_for_attempts(
    contract: BenchmarkContract,
    records: list[AttemptRecord],
) -> dict[str, TaskContract]:
    attempt_ids = [record.attempt_id for record in records]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise TaskOutcomeScoringError("Attempt ids must be unique within one aggregate.")

    tasks = _task_map(contract)
    return {
        record.attempt_id: _validate_attempt_identity(
            contract,
            tasks.get(record.task_id),
            record,
        )
        for record in records
    }


def _count_task_outcomes(
    valid_records: list[AttemptRecord],
    task_by_attempt: dict[str, TaskContract],
) -> _OutcomeCounts:
    successful_attempts = 0
    failure_categories: Counter[str] = Counter()
    for record in valid_records:
        if _attempt_succeeded(task_by_attempt[record.attempt_id], record):
            successful_attempts += 1
        else:
            failure_categories[record.failure_category or "unclassified_failure"] += 1
    return _OutcomeCounts(successful_attempts, failure_categories)


def _count_mutation_outcomes(valid_records: list[AttemptRecord]) -> _MutationCounts:
    recovery_required_mutations = 0
    successful_recoveries = 0
    duplicate_application_incidents = 0
    state_divergence_incidents = 0
    file_corruption_incidents = 0
    for record in valid_records:
        for index, mutation in enumerate(record.mutations):
            if mutation.recovery_required:
                recovery_required_mutations += 1
                successful_recoveries += int(_recovery_succeeded(record, index))
            duplicate_application_incidents += int(mutation.duplicate_application_detected)
            state_divergence_incidents += int(mutation.state_divergence_detected)
            file_corruption_incidents += int(mutation.corruption_detected)
    return _MutationCounts(
        mutation_attempts=sum(len(record.mutations) for record in valid_records),
        recovery_required_mutations=recovery_required_mutations,
        successful_recoveries=successful_recoveries,
        duplicate_application_incidents=duplicate_application_incidents,
        state_divergence_incidents=state_divergence_incidents,
        file_corruption_incidents=file_corruption_incidents,
    )


def _count_release_evidence(
    valid_records: list[AttemptRecord],
    task_by_attempt: dict[str, TaskContract],
) -> _ReleaseEvidenceCounts:
    drc_required_tasks = 0
    drc_executed_and_consumed_tasks = 0
    manufacturing_release_tasks = 0
    manufacturing_reproducible_tasks = 0
    for record in valid_records:
        task = task_by_attempt[record.attempt_id]
        if task.stage_requirements["drc"] == "required":
            drc_required_tasks += 1
            drc = _validation_for(record, "drc")
            if (
                drc is not None
                and drc.required
                and drc.execution_attempted
                and drc.execution_completed
                and drc.result_consumed
            ):
                drc_executed_and_consumed_tasks += 1
        if task.stage_requirements["manufacturing_reproducibility"] == "required":
            manufacturing_release_tasks += 1
            manufacturing_reproducible_tasks += int(_manufacturing_reproducible(record))
    return _ReleaseEvidenceCounts(
        drc_required_tasks=drc_required_tasks,
        drc_executed_and_consumed_tasks=drc_executed_and_consumed_tasks,
        manufacturing_release_tasks=manufacturing_release_tasks,
        manufacturing_reproducible_tasks=manufacturing_reproducible_tasks,
    )


def _file_corruption_status(
    *,
    incidents: int,
    globally_sufficient: bool,
    mutation_attempts: int,
) -> TargetStatus:
    if incidents:
        return "not_met"
    if globally_sufficient and mutation_attempts:
        return "met"
    return "insufficient_evidence"


def _partition_attempts(
    records: list[AttemptRecord],
) -> tuple[list[AttemptRecord], list[AttemptRecord]]:
    invalid_records = [
        record for record in records if record.classification == "infrastructure_invalid"
    ]
    valid_records = [
        record for record in records if record.classification != "infrastructure_invalid"
    ]
    return invalid_records, valid_records


def aggregate_task_outcomes(
    contract: BenchmarkContract,
    attempts: Iterable[AttemptRecord],
) -> TaskOutcomeSummary:
    """Aggregate complete attempts without dropping valid failures from denominators."""
    records = list(attempts)
    task_by_attempt = _validated_tasks_for_attempts(contract, records)
    invalid_records, valid_records = _partition_attempts(records)
    globally_sufficient = _global_evidence_sufficient(contract, valid_records)
    outcomes = _count_task_outcomes(valid_records, task_by_attempt)
    mutations = _count_mutation_outcomes(valid_records)
    release_evidence = _count_release_evidence(valid_records, task_by_attempt)

    sufficiency = contract.evidence_sufficiency
    task_success = _rate_kpi(
        numerator=outcomes.successful_attempts,
        denominator=len(valid_records),
        target=_TASK_SUCCESS_TARGET,
        sufficient=globally_sufficient,
    )
    mutation_recovery = _rate_kpi(
        numerator=mutations.successful_recoveries,
        denominator=mutations.recovery_required_mutations,
        target=_MUTATION_RECOVERY_TARGET,
        sufficient=(
            globally_sufficient
            and mutations.recovery_required_mutations
            >= sufficiency.minimum_recovery_required_mutations
        ),
    )
    required_drc_execution = _rate_kpi(
        numerator=release_evidence.drc_executed_and_consumed_tasks,
        denominator=release_evidence.drc_required_tasks,
        target=_DRC_EXECUTION_TARGET,
        sufficient=(
            globally_sufficient
            and release_evidence.drc_required_tasks >= sufficiency.minimum_drc_required_tasks
        ),
    )
    manufacturing_reproducibility = _rate_kpi(
        numerator=release_evidence.manufacturing_reproducible_tasks,
        denominator=release_evidence.manufacturing_release_tasks,
        target=_MANUFACTURING_REPRODUCIBILITY_TARGET,
        sufficient=(
            globally_sufficient
            and release_evidence.manufacturing_release_tasks
            >= sufficiency.minimum_manufacturing_release_tasks
        ),
    )

    return TaskOutcomeSummary(
        benchmark_id=contract.benchmark_id,
        benchmark_version=contract.benchmark_version,
        attempts_total=len(records),
        valid_attempts=len(valid_records),
        infrastructure_invalid_attempts=len(invalid_records),
        successful_attempts=outcomes.successful_attempts,
        failed_attempts=len(valid_records) - outcomes.successful_attempts,
        failure_categories=dict(sorted(outcomes.failure_categories.items())),
        task_success=task_success,
        mutation_attempts=mutations.mutation_attempts,
        recovery_required_mutations=mutations.recovery_required_mutations,
        successful_recoveries=mutations.successful_recoveries,
        mutation_recovery=mutation_recovery,
        duplicate_application_incidents=mutations.duplicate_application_incidents,
        state_divergence_incidents=mutations.state_divergence_incidents,
        file_corruption_incidents=mutations.file_corruption_incidents,
        file_corruption_status=_file_corruption_status(
            incidents=mutations.file_corruption_incidents,
            globally_sufficient=globally_sufficient,
            mutation_attempts=mutations.mutation_attempts,
        ),
        drc_required_tasks=release_evidence.drc_required_tasks,
        drc_executed_and_consumed_tasks=release_evidence.drc_executed_and_consumed_tasks,
        required_drc_execution=required_drc_execution,
        manufacturing_release_tasks=release_evidence.manufacturing_release_tasks,
        manufacturing_reproducible_tasks=release_evidence.manufacturing_reproducible_tasks,
        manufacturing_reproducibility=manufacturing_reproducibility,
    )


__all__ = [
    "TASK_OUTCOME_SUMMARY_SCHEMA_VERSION",
    "RateKpi",
    "TargetStatus",
    "TaskOutcomeScoringError",
    "TaskOutcomeSummary",
    "WilsonInterval",
    "aggregate_task_outcomes",
]
