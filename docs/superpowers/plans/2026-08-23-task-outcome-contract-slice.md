# Task Outcome Contract Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first independently testable #729 delivery slice: a strict, versioned, sanitized, deterministic task-outcome evidence contract that later scoring and real-board benchmark layers can consume.

**Architecture:** Keep task-outcome evidence separate from the existing live-model and golden-corpus result models. Reuse the repository's existing Pydantic v2 dependency for immutable/extra-forbidden evidence models, extract the existing sensitive-evidence validator into a shared eval utility without breaking its current public import path, and expose deterministic JSON rendering without adding a new filesystem write sink. Scoring, KPI aggregation, report rendering, corpus adapters, and #728/#730 physical evidence integration remain later slices.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, Ruff, Mypy, existing `kicad_mcp.evals` package.

**Spec:** `docs/superpowers/specs/2026-08-21-task-outcome-kpi-design.md`

## Global Constraints

- Schema identifier for this slice is exactly `pcb-task-outcome.v1`.
- No public MCP tool, REST/GraphQL, CLI, database, config/env, or event contract changes.
- No new dependency; use the already-declared Pydantic v2 dependency and standard library only.
- Task-outcome models remain FastMCP-independent and do not import server/tool modules.
- Unknown schema versions and unknown fields fail closed; evidence models use `ConfigDict(frozen=True, extra="forbid")`.
- `provider_failure` remains a real valid attempt classification; only `infrastructure_invalid` is structurally distinguishable for later denominator exclusion.
- Evidence carries stable identifiers/digests and bounded structured facts, never prompts, credentials, raw provider payloads, unrelated board content, or absolute private paths.
- Existing `kicad_mcp.evals.live_runner.EvidenceSanitizationError` and `validate_sanitized_evidence` imports remain backward-compatible after sanitizer extraction.
- Serialization is deterministic: JSON mode, `exclude_none=True`, `sort_keys=True`, UTF-8-safe output, two-space indentation, one trailing newline.
- This slice does not calculate KPI rates, Wilson intervals, `met/not_met/insufficient_evidence`, or publish headline claims; those belong to the scoring slice.

---

### Task 1: Extract the shared evidence sanitization boundary

**Files:**
- Create: `src/kicad_mcp/evals/evidence_sanitization.py`
- Modify: `src/kicad_mcp/evals/live_runner.py`
- Test: `tests/unit/test_live_model_eval_runner.py`

**Interfaces:**
- Consumes: the current sensitive-key/value/path policy embedded in `live_runner.py`.
- Produces: `EvidenceSanitizationError` and `validate_sanitized_evidence(value: object) -> None` from `kicad_mcp.evals.evidence_sanitization` while preserving the same names from `kicad_mcp.evals.live_runner`.

- [ ] **Step 1: Write the failing shared-module regression test**

Add a test that fails before the shared module exists without breaking test collection:

```python
def test_evidence_sanitizer_has_shared_eval_module() -> None:
    import importlib.util

    assert importlib.util.find_spec("kicad_mcp.evals.evidence_sanitization") is not None
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
uv run --all-extras pytest tests/unit/test_live_model_eval_runner.py::test_evidence_sanitizer_has_shared_eval_module -q
```

Expected: FAIL because `find_spec(...)` returns `None`.

- [ ] **Step 3: Move the existing sanitizer implementation without changing behavior**

Create `evidence_sanitization.py` with the existing exception, allow/deny constants, regexes, and recursive validator. In `live_runner.py`, replace the local definitions with imports:

```python
from .evidence_sanitization import EvidenceSanitizationError, validate_sanitized_evidence
```

Do not change the validator's forbidden key set, sensitive-value regex, private-path regex, recursion semantics, error text, or the existing `write_evidence()` call sequence.

- [ ] **Step 4: Verify GREEN and backward compatibility**

Run:

```bash
uv run --all-extras pytest \
  tests/unit/test_live_model_eval_runner.py::test_evidence_sanitizer_has_shared_eval_module \
  tests/unit/test_live_model_eval_runner.py::test_evidence_validator_rejects_sensitive_shapes \
  tests/unit/test_live_model_eval_runner.py::test_evidence_validator_rejects_embedded_private_paths \
  tests/unit/test_live_model_eval_runner.py::test_evidence_is_sanitized_and_byte_reproducible -q
```

Expected: all selected tests PASS.

- [ ] **Step 5: Commit the sanitizer extraction**

```bash
git add src/kicad_mcp/evals/evidence_sanitization.py src/kicad_mcp/evals/live_runner.py tests/unit/test_live_model_eval_runner.py
git commit -m "refactor(eval): share evidence sanitization"
```

---

### Task 2: Define strict v1 benchmark and attempt evidence models

**Files:**
- Create: `src/kicad_mcp/evals/task_outcomes.py`
- Create: `tests/unit/test_task_outcomes.py`
- Modify: `src/kicad_mcp/evals/__init__.py`

**Interfaces:**
- Consumes: shared `validate_sanitized_evidence`; existing Pydantic v2 dependency.
- Produces:
  - `TASK_OUTCOME_SCHEMA_VERSION`
  - `ALL_TASK_STAGES`
  - `AttemptClassification`
  - `FailureCategory`
  - `EvidenceSufficiencyContract`
  - `TaskContract`
  - `BenchmarkContract`
  - `TimingEvidence`
  - `StageEvidence`
  - `ValidationEvidence`
  - `MutationEvidence`
  - `ManufacturingEvidence`
  - `InfrastructureInvalidEvidence`
  - `AttemptRecord`

- [ ] **Step 1: Write RED tests for package-level contract availability**

Start `tests/unit/test_task_outcomes.py` with:

```python
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

import kicad_mcp.evals as evals


def valid_stage_requirements() -> dict[str, str]:
    requirements = {stage: "not_applicable" for stage in evals.ALL_TASK_STAGES}
    for stage in ("requirements", "pcb", "drc", "parse_reopen"):
        requirements[stage] = "required"
    return requirements


def valid_benchmark_payload() -> dict[str, Any]:
    return {
        "schema_version": "pcb-task-outcome.v1",
        "benchmark_id": "pcb-reference-suite",
        "benchmark_version": "v1",
        "tasks": [
            {
                "task_id": "route-usb-board",
                "task_class": "pcb-edit",
                "version": "v1",
                "stage_requirements": valid_stage_requirements(),
            }
        ],
        "evidence_sufficiency": {
            "minimum_valid_attempts": 20,
            "minimum_valid_attempts_by_task_class": {"pcb-edit": 10},
            "minimum_recovery_required_mutations": 10,
            "minimum_drc_required_tasks": 10,
            "minimum_manufacturing_release_tasks": 0,
            "confidence_level": 0.95,
            "interval_method": "wilson",
        },
    }


def valid_attempt_payload(classification: str = "success") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "pcb-task-outcome.v1",
        "attempt_id": "attempt-001",
        "task_id": "route-usb-board",
        "task_class": "pcb-edit",
        "task_contract_version": "v1",
        "benchmark_id": "pcb-reference-suite",
        "benchmark_version": "v1",
        "source_revision": "a" * 40,
        "kicad_version": "10.0.5",
        "toolchain_contract": "toolchain-v1",
        "agent": "fixture-agent",
        "model": "fixture-model",
        "provider": "fixture-provider",
        "mcp_profile": "default",
        "operating_mode": "write",
        "starting_state_digest": "sha256:" + "b" * 64,
        "timing": {
            "started_at": "2026-08-23T01:00:00+03:00",
            "ended_at": "2026-08-23T01:01:00+03:00",
        },
        "classification": classification,
        "retry_count": 0,
        "start_state": "clean",
        "manual_repair": False,
        "stages": [
            {"stage": "requirements", "outcome": "passed"},
            {"stage": "pcb", "outcome": "passed"},
            {"stage": "drc", "outcome": "passed"},
            {"stage": "parse_reopen", "outcome": "passed"},
        ],
        "validations": [
            {
                "kind": "drc",
                "required": True,
                "execution_attempted": True,
                "execution_completed": True,
                "result_consumed": True,
                "disposition": "resolved",
            }
        ],
        "mutations": [],
    }
    failure_categories = {
        "task_failure": "design",
        "recovery_failure": "recovery",
        "provider_failure": "provider",
        "tool_failure": "tool",
        "infrastructure_invalid": "infrastructure",
    }
    if classification != "success":
        payload["failure_category"] = failure_categories[classification]
        payload["failure_reason_code"] = "fixture_failure"
    return payload


def test_eval_package_exposes_task_outcome_v1_contract() -> None:
    assert evals.TASK_OUTCOME_SCHEMA_VERSION == "pcb-task-outcome.v1"
    assert evals.AttemptRecord is not None
    assert evals.BenchmarkContract is not None
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run --all-extras pytest tests/unit/test_task_outcomes.py::test_eval_package_exposes_task_outcome_v1_contract -q
```

Expected: FAIL because the new exports do not exist.

- [ ] **Step 3: Add the strict common model boundary and stable literals**

In `task_outcomes.py`, define the shared immutable model config and stable type contracts:

```python
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
ValidationKind = Literal["erc", "drc"]
StableReasonCode = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
ArtifactDigest = Annotated[str, Field(min_length=1, max_length=256)]
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
    model_config = ConfigDict(frozen=True, extra="forbid")
```

Import `Annotated` alongside `Literal` from `typing`. Use bounded string fields (`min_length=1`) for IDs/versions, `Field(ge=0)` for counters, and the existing source-revision convention of a lowercase 40-character Git SHA.

- [ ] **Step 4: Write RED tests for the benchmark contract**

Add tests proving:

```python
def test_benchmark_contract_requires_explicit_stage_requirement_for_every_stage() -> None:
    payload = valid_benchmark_payload()
    payload["tasks"][0]["stage_requirements"].pop("drc")

    with pytest.raises(ValidationError, match="stage requirements"):
        evals.BenchmarkContract.model_validate(payload)


def test_benchmark_contract_rejects_unknown_schema_version() -> None:
    payload = valid_benchmark_payload()
    payload["schema_version"] = "pcb-task-outcome.v2"

    with pytest.raises(ValidationError):
        evals.BenchmarkContract.model_validate(payload)


def test_benchmark_contract_rejects_unknown_fields() -> None:
    payload = valid_benchmark_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        evals.BenchmarkContract.model_validate(payload)
```

- [ ] **Step 5: Implement benchmark and sufficiency models minimally**

Implement:

```python
class EvidenceSufficiencyContract(_EvidenceModel):
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
    task_id: str = Field(min_length=1)
    task_class: str = Field(min_length=1)
    version: str = Field(min_length=1)
    stage_requirements: dict[TaskStage, StageRequirement]
    validation_exception_reason_codes: dict[ValidationKind, tuple[StableReasonCode, ...]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def _require_all_stage_declarations(self) -> TaskContract:
        if set(self.stage_requirements) != set(ALL_TASK_STAGES):
            raise ValueError("task contract stage requirements must declare every v1 stage")
        for kind, reason_codes in self.validation_exception_reason_codes.items():
            if self.stage_requirements[kind] != "required":
                raise ValueError(
                    f"{kind} validation exceptions require the validation stage to be required"
                )
            if len(reason_codes) != len(set(reason_codes)):
                raise ValueError(f"{kind} validation exception reason codes must be unique")
        return self


class BenchmarkContract(_EvidenceModel):
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
```

Do not add KPI scoring or target-status logic yet.

- [ ] **Step 6: Verify benchmark-model GREEN**

Run:

```bash
uv run --all-extras pytest tests/unit/test_task_outcomes.py -q
```

At this checkpoint, the package-export test and benchmark-contract tests must PASS; attempt-record tests added below may still be absent.

- [ ] **Step 7: Write RED tests for attempt identity and classification invariants**

Add tests covering a complete valid record plus these fail-closed cases:

```python
def test_attempt_record_rejects_extra_fields() -> None:
    payload = valid_attempt_payload()
    payload["raw_response"] = "must never be accepted"
    with pytest.raises(ValidationError):
        evals.AttemptRecord.model_validate(payload)


def test_success_attempt_rejects_failure_metadata() -> None:
    payload = valid_attempt_payload()
    payload["failure_category"] = "provider"
    payload["failure_reason_code"] = "rate_limited"
    with pytest.raises(ValidationError, match="success"):
        evals.AttemptRecord.model_validate(payload)


def test_provider_failure_requires_provider_category() -> None:
    payload = valid_attempt_payload(classification="provider_failure")
    payload["failure_category"] = "tool"
    with pytest.raises(ValidationError, match="provider"):
        evals.AttemptRecord.model_validate(payload)


def test_timing_rejects_naive_or_reverse_timestamps() -> None:
    payload = valid_attempt_payload()
    payload["timing"] = {
        "started_at": "2026-08-23T01:00:00+03:00",
        "ended_at": "2026-08-23T00:59:00+03:00",
    }
    with pytest.raises(ValidationError, match="ended_at"):
        evals.AttemptRecord.model_validate(payload)


def test_validation_evidence_rejects_consumed_without_completion() -> None:
    payload = valid_attempt_payload()
    payload["validations"][0]["execution_completed"] = False
    with pytest.raises(ValidationError, match="consumed validation"):
        evals.AttemptRecord.model_validate(payload)


def test_attempt_rejects_duplicate_stage_evidence() -> None:
    payload = valid_attempt_payload()
    payload["stages"].append({"stage": "drc", "outcome": "failed"})
    with pytest.raises(ValidationError, match="stages must be unique"):
        evals.AttemptRecord.model_validate(payload)
```

- [ ] **Step 8: Implement the bounded attempt evidence models**

Implement the following shapes without free-form metadata dictionaries:

```python
class TimingEvidence(_EvidenceModel):
    started_at: datetime
    ended_at: datetime


class StageEvidence(_EvidenceModel):
    stage: TaskStage
    outcome: Literal["passed", "failed", "not_applicable"]


class ValidationEvidence(_EvidenceModel):
    kind: ValidationKind
    required: bool
    execution_attempted: bool
    execution_completed: bool
    result_consumed: bool
    disposition: Literal["resolved", "accepted", "blocking", "exception", "not_applicable"]
    exception_reason_code: StableReasonCode | None = None


class MutationEvidence(_EvidenceModel):
    mutation_id: str = Field(min_length=1)
    attempted: Literal[True] = True
    execution_state: Literal["completed", "interrupted", "failed"]
    recovery_required: bool
    recovery_succeeded: bool | None = None
    duplicate_application_detected: bool = False
    state_divergence_detected: bool = False
    corruption_detected: bool = False
    final_state_verified: bool


class ManufacturingEvidence(_EvidenceModel):
    required: bool
    generation_completed: bool
    regeneration_completed: bool
    comparison: Literal["byte_identical", "normalized_equivalent", "divergent", "not_run"]
    artifact_manifest_digests: tuple[ArtifactDigest, ArtifactDigest] | None = None
    normalization_rules_version: str | None = None


class InfrastructureInvalidEvidence(_EvidenceModel):
    reason_code: StableReasonCode
    reviewed: Literal[True]
    task_execution_started: Literal[False]
```

`AttemptRecord` must include the spec's pinned identity/accounting fields:

```python
class AttemptRecord(_EvidenceModel):
    schema_version: Literal["pcb-task-outcome.v1"] = TASK_OUTCOME_SCHEMA_VERSION
    attempt_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_class: str = Field(min_length=1)
    task_contract_version: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    kicad_version: str = Field(min_length=1)
    toolchain_contract: str = Field(min_length=1)
    agent: str | None = None
    model: str | None = None
    provider: str | None = None
    mcp_profile: str = Field(min_length=1)
    operating_mode: str = Field(min_length=1)
    starting_state_digest: str = Field(min_length=1)
    timing: TimingEvidence
    classification: AttemptClassification
    failure_category: FailureCategory | None = None
    failure_reason_code: StableReasonCode | None = None
    retry_count: int = Field(ge=0)
    start_state: Literal["clean", "reviewed_recovered"]
    manual_repair: bool
    stages: tuple[StageEvidence, ...]
    validations: tuple[ValidationEvidence, ...] = ()
    mutations: tuple[MutationEvidence, ...] = ()
    manufacturing: ManufacturingEvidence | None = None
    infrastructure_evidence: InfrastructureInvalidEvidence | None = None
```

Use these explicit structural validators; do not convert invalid records into a different classification:

```python
class TimingEvidence(_EvidenceModel):
    started_at: datetime
    ended_at: datetime

    @model_validator(mode="after")
    def _validate_timing(self) -> TimingEvidence:
        if self.started_at.utcoffset() is None or self.ended_at.utcoffset() is None:
            raise ValueError("attempt timestamps must be timezone-aware")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self


# Add this method inside ValidationEvidence.
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


# Add this method inside MutationEvidence.
@model_validator(mode="after")
def _validate_recovery_state(self) -> MutationEvidence:
    if not self.recovery_required and self.recovery_succeeded is not None:
        raise ValueError("recovery result requires a recovery-required mutation")
    return self


# Add this method inside ManufacturingEvidence.
@model_validator(mode="after")
def _validate_comparison_state(self) -> ManufacturingEvidence:
    if self.comparison != "not_run" and not (
        self.generation_completed and self.regeneration_completed
    ):
        raise ValueError("manufacturing comparison requires two completed generations")
    if self.comparison != "not_run" and self.artifact_manifest_digests is None:
        raise ValueError("manufacturing comparison requires both artifact-set manifest digests")
    if self.comparison == "not_run" and self.artifact_manifest_digests is not None:
        raise ValueError("artifact-set manifest digests require a manufacturing comparison")
    if self.comparison == "normalized_equivalent" and not self.normalization_rules_version:
        raise ValueError("normalized comparison requires a normalization rules version")
    return self


# Add this method inside AttemptRecord.
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

    if self.classification == "infrastructure_invalid":
        if self.infrastructure_evidence is None:
            raise ValueError("infrastructure-invalid evidence must be reviewed and pre-task")
        if self.failure_reason_code != self.infrastructure_evidence.reason_code:
            raise ValueError(
                "infrastructure-invalid evidence reason must match failure reason code"
            )
    elif self.infrastructure_evidence is not None:
        raise ValueError(
            "infrastructure-invalid evidence is only valid for infrastructure_invalid attempts"
        )

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
            f"{self.classification} has incompatible failure category "
            f"{self.failure_category!r}"
        )
    if self.failure_reason_code is None:
        raise ValueError("failed attempt requires a failure reason code")
    return self
```

Keep `failure_reason_code` bounded to stable identifier syntax (letters/digits plus `._:-`), not free-form provider text. Insert each validator into the corresponding model defined in the preceding step; do not duplicate model classes.

Reviewer hardening before publication must also preserve the approved design's accounting semantics:

- validation exception reason codes are predeclared by the task contract and only for required ERC/DRC stages;
- every mutation record explicitly states that the mutation was attempted plus `completed` / `interrupted` / `failed` execution state;
- `recovery_succeeded` is absent unless the mutation contributes to the recovery-required denominator;
- recovered starts use the explicit `reviewed_recovered` value rather than an ambiguous `recovered` label;
- `infrastructure_invalid` requires reviewed evidence proving task execution did not start and its stable reason must match the top-level failure reason;
- a manufacturing comparison carries both independently generated artifact-set manifest digests.

- [ ] **Step 9: Verify all model tests GREEN**

Run:

```bash
uv run --all-extras pytest tests/unit/test_task_outcomes.py -q
```

Expected: all task-outcome model tests PASS.

- [ ] **Step 10: Commit the v1 models**

```bash
git add src/kicad_mcp/evals/task_outcomes.py src/kicad_mcp/evals/__init__.py tests/unit/test_task_outcomes.py
git commit -m "feat(eval): add task outcome evidence contract"
```

---

### Task 3: Add deterministic sanitized parsing and rendering

**Files:**
- Modify: `src/kicad_mcp/evals/task_outcomes.py`
- Modify: `src/kicad_mcp/evals/__init__.py`
- Modify: `tests/unit/test_task_outcomes.py`

**Interfaces:**
- Consumes: `BenchmarkContract`, `AttemptRecord`, shared `validate_sanitized_evidence`.
- Produces:
  - `parse_benchmark_contract(payload: Mapping[str, object]) -> BenchmarkContract`
  - `parse_attempt_record(payload: Mapping[str, object]) -> AttemptRecord`
  - `render_benchmark_contract(contract: BenchmarkContract) -> str`
  - `render_attempt_record(record: AttemptRecord) -> str`

- [ ] **Step 1: Write RED parser tests**

```python
def test_parse_attempt_record_accepts_complete_v1_mapping() -> None:
    record = evals.parse_attempt_record(valid_attempt_payload())
    assert record.schema_version == "pcb-task-outcome.v1"
    assert record.classification == "success"


def test_parse_benchmark_contract_rejects_v2_mapping() -> None:
    payload = valid_benchmark_payload()
    payload["schema_version"] = "pcb-task-outcome.v2"
    with pytest.raises(ValidationError):
        evals.parse_benchmark_contract(payload)
```

- [ ] **Step 2: Verify parser RED**

Run:

```bash
uv run --all-extras pytest \
  tests/unit/test_task_outcomes.py::test_parse_attempt_record_accepts_complete_v1_mapping \
  tests/unit/test_task_outcomes.py::test_parse_benchmark_contract_rejects_v2_mapping -q
```

Expected: FAIL because parse functions are missing.

- [ ] **Step 3: Implement thin Pydantic parser functions**

```python
def parse_benchmark_contract(payload: Mapping[str, object]) -> BenchmarkContract:
    return BenchmarkContract.model_validate(payload)


def parse_attempt_record(payload: Mapping[str, object]) -> AttemptRecord:
    return AttemptRecord.model_validate(payload)
```

Do not catch and weaken `ValidationError`; callers need the original field-level failure evidence.

- [ ] **Step 4: Write RED deterministic/sanitization tests**

```python
def test_attempt_render_is_byte_reproducible() -> None:
    record = evals.parse_attempt_record(valid_attempt_payload())
    first_render = evals.render_attempt_record(record).encode()
    second_render = evals.render_attempt_record(record).encode()

    assert first_render == second_render


def test_attempt_render_ends_with_one_newline_and_sorted_keys() -> None:
    rendered = evals.render_attempt_record(evals.parse_attempt_record(valid_attempt_payload()))
    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")
    assert rendered.index('"agent"') < rendered.index('"attempt_id"')


def test_attempt_render_rejects_private_path_values() -> None:
    payload = valid_attempt_payload()
    payload["agent"] = "/home/private/agent-config"
    record = evals.parse_attempt_record(payload)
    with pytest.raises(evals.EvidenceSanitizationError):
        evals.render_attempt_record(record)
```

- [ ] **Step 5: Verify renderer RED**

Run:

```bash
uv run --all-extras pytest tests/unit/test_task_outcomes.py -q
```

Expected: the new renderer tests FAIL because render functions are missing.

- [ ] **Step 6: Implement one private deterministic renderer and two typed wrappers**

```python
def _render_evidence(value: BaseModel) -> str:
    payload = value.model_dump(mode="json", exclude_none=True)
    validate_sanitized_evidence(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def render_benchmark_contract(contract: BenchmarkContract) -> str:
    return _render_evidence(contract)


def render_attempt_record(record: AttemptRecord) -> str:
    return _render_evidence(record)
```

Do not add a file writer in this slice; that would introduce a new path-write boundary without a current requirement.

- [ ] **Step 7: Verify GREEN and shared-sanitizer regression**

Run:

```bash
uv run --all-extras pytest tests/unit/test_task_outcomes.py tests/unit/test_live_model_eval_runner.py -q
```

Expected: both the new contract suite and existing live-model runner suite PASS.

- [ ] **Step 8: Commit parsing/rendering**

```bash
git add src/kicad_mcp/evals/task_outcomes.py src/kicad_mcp/evals/__init__.py tests/unit/test_task_outcomes.py
git commit -m "feat(eval): render sanitized task outcome evidence"
```

---

### Task 4: Verify the contract slice as a production-quality PR

**Files:**
- Review only: all files changed by Tasks 1-3 plus this implementation plan.
- Modify only if a verification failure demonstrates a real issue in the slice.

**Interfaces:**
- Consumes: all contract-slice code/tests.
- Produces: verified branch ready for PR review; no claim about #729 headline KPI completion.

- [ ] **Step 1: Run focused contract and regression tests**

```bash
uv run --all-extras pytest \
  tests/unit/test_task_outcomes.py \
  tests/unit/test_live_model_eval_runner.py \
  tests/unit/test_corpus_eval.py -q
```

Expected: PASS with zero failures.

- [ ] **Step 2: Run changed-surface format/lint/type checks**

```bash
uv run --all-extras ruff format --check \
  src/kicad_mcp/evals/evidence_sanitization.py \
  src/kicad_mcp/evals/live_runner.py \
  src/kicad_mcp/evals/task_outcomes.py \
  src/kicad_mcp/evals/__init__.py \
  tests/unit/test_live_model_eval_runner.py \
  tests/unit/test_task_outcomes.py
uv run --all-extras ruff check \
  src/kicad_mcp/evals/evidence_sanitization.py \
  src/kicad_mcp/evals/live_runner.py \
  src/kicad_mcp/evals/task_outcomes.py \
  src/kicad_mcp/evals/__init__.py \
  tests/unit/test_live_model_eval_runner.py \
  tests/unit/test_task_outcomes.py
uv run --all-extras python -m mypy src/kicad_mcp/
```

Expected: PASS; Mypy reports zero issues.

- [ ] **Step 3: Run repository contract/security/package gates used by this project**

Run the existing repository scripts rather than inventing new gates:

```bash
uv run --all-extras python scripts/check_release_preflight.py
corepack pnpm run check:meta
corepack pnpm run check:security
corepack pnpm run check:build
```

- [ ] **Step 4: Run full Python verification**

```bash
uv run --all-extras python scripts/run_pytest.py full
```

Expected: runner reports success and repository coverage remains at or above its configured threshold.

- [ ] **Step 5: Review the final diff like a reviewer**

```bash
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
git diff origin/main...HEAD -- \
  src/kicad_mcp/evals/evidence_sanitization.py \
  src/kicad_mcp/evals/live_runner.py \
  src/kicad_mcp/evals/task_outcomes.py \
  src/kicad_mcp/evals/__init__.py \
  tests/unit/test_live_model_eval_runner.py \
  tests/unit/test_task_outcomes.py \
  docs/superpowers/plans/2026-08-23-task-outcome-contract-slice.md
```

Confirm: no debug code, no commented-out implementation, no generated/build artifacts, no secret material, no dependency change, no public MCP contract change, no unrelated formatting/refactor.

- [ ] **Step 6: Publish as a focused #729 contract-slice PR**

PR body must state explicitly that it implements only the versioned contract foundation. It must not claim the #729 KPI targets are met. Required remote gates include Required PR Gate, platform lanes, CodeQL, Semgrep, dependency/security checks, Sonar, and Codecov where applicable.

- [ ] **Step 7: Post-merge verification**

After merge, verify exact-main CI/security/Sonar on the merge SHA. Only then update #729 with the contract-slice evidence and proceed to a separate scoring-slice plan/PR.
