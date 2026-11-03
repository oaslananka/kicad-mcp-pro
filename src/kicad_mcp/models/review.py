"""Typed domain models for engineering review and honest assessment outcomes (#1579).

In accordance with milestone M18 principles:
- Rules, findings, assessments, and coverage are pure domain records.
- Missing information, incomplete coverage, or unassessed conditions must never
  synthesize a PASS.
- Readability/cosmetics and routing styles remain distinct from electrical defects.
- Units must never be coerced across incompatible physical dimensions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Explicit physical dimensions for review units to prevent cross-dimension coercion.
SUPPORTED_REVIEW_UNITS: dict[str, str] = {
    "mm": "length",
    "um": "length",
    "mil": "length",
    "in": "length",
    "V": "voltage",
    "mV": "voltage",
    "kV": "voltage",
    "A": "current",
    "mA": "current",
    "uA": "current",
    "ohm": "resistance",
    "mohm": "resistance",
    "kohm": "resistance",
    "Mohm": "resistance",
    "deg": "angle",
    "rad": "angle",
    "ps": "time",
    "ns": "time",
    "s": "time",
    "Hz": "frequency",
    "kHz": "frequency",
    "MHz": "frequency",
    "GHz": "frequency",
    "W": "power",
    "mW": "power",
    "C": "temperature",
    "pct": "ratio",
    "count": "dimensionless",
}


def validate_unit_compatibility(unit_a: str | None, unit_b: str | None) -> None:
    """Ensure two unit strings share physical dimension; raises ValueError if incompatible."""
    if unit_a is None or unit_b is None:
        return
    dim_a = SUPPORTED_REVIEW_UNITS.get(unit_a)
    dim_b = SUPPORTED_REVIEW_UNITS.get(unit_b)
    if dim_a is None:
        raise ValueError(f"Unrecognized unit: '{unit_a}'.")
    if dim_b is None:
        raise ValueError(f"Unrecognized unit: '{unit_b}'.")
    if dim_a != dim_b:
        raise ValueError(
            f"Cannot coerce or compare incompatible physical dimensions: "
            f"'{unit_a}' ({dim_a}) vs '{unit_b}' ({dim_b})."
        )


class ReviewDomain(StrEnum):
    """Engineering review domains."""

    SCHEMATIC = "schematic"
    PCB = "pcb"
    ROUTING = "routing"
    PLACEMENT = "placement"
    SIGNAL_INTEGRITY = "signal_integrity"
    POWER_INTEGRITY = "power_integrity"
    THERMAL = "thermal"
    EMC = "emc"
    SAFETY = "safety"
    DFM = "dfm"
    ASSEMBLY = "assembly"
    BOM = "bom"
    MECHANICAL = "mechanical"


class RuleApplicability(StrEnum):
    """Applicability status of an engineering rule under a specific ReviewContext."""

    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNDETERMINED = "UNDETERMINED"


class AssessmentStatus(StrEnum):
    """Honest evaluation status for an engineering check.

    Missing inputs or unavailable execution must yield NOT_ASSESSED or BLOCKED,
    never PASS.
    """

    PASS = "PASS"  # nosec B105  # noqa: S105
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_ASSESSED = "NOT_ASSESSED"
    BLOCKED = "BLOCKED"


class EvaluationMethod(StrEnum):
    """Method used to execute or verify an engineering check."""

    NATIVE = "native"
    ANALYTICAL = "analytical"
    HEURISTIC = "heuristic"
    HUMAN_REVIEW = "human_review"
    PHYSICAL_MEASUREMENT = "physical_measurement"


class ReviewRule(BaseModel):
    """Versioned specification of an engineering review rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9][a-z0-9_.:/-]*$")
    revision: int = Field(ge=1)
    domain: ReviewDomain
    title: str = Field(min_length=3, max_length=200)
    source_doc: str = Field(min_length=1, max_length=200)
    source_revision: str = Field(min_length=1, max_length=100)
    required_inputs: list[str] = Field(default_factory=list)
    units: str | None = None
    method: EvaluationMethod
    severity: Literal["error", "warning", "info"] = "error"
    rationale: str = ""
    remediation: str = ""
    validator_version: str = "1.0.0"
    is_mandatory: bool = True

    @field_validator("units")
    @classmethod
    def validate_known_unit(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_REVIEW_UNITS:
            raise ValueError(f"Rule unit '{value}' is not in SUPPORTED_REVIEW_UNITS.")
        return value


class ReviewContext(BaseModel):
    """Project requirements and execution environment for rule applicability."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    project_name: str = ""
    maturity: Literal["concept", "development", "prototype", "production"] = "development"
    technical_domains: list[str] = Field(default_factory=list)
    operating_voltage_v: float | None = None
    operating_current_a: float | None = None
    is_hv: bool = False
    declared_routing_style: str | None = None
    selected_mfg_profile: str | None = None
    selected_assembly_profile: str | None = None
    has_kicad_cli: bool = False
    has_3d_models: bool = False
    explicit_requirements: dict[str, Any] = Field(default_factory=dict)
    inferred_values: dict[str, Any] = Field(default_factory=dict)

    def is_inferred(self, field_name: str) -> bool:
        """Return True if the specified parameter was inferred rather than declared explicitly."""
        return field_name in self.inferred_values


class ResolvedReviewRule(BaseModel):
    """Outcome of resolving rule applicability against a ReviewContext."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: ReviewRule
    status: RuleApplicability
    rationale: str
    missing_inputs: list[str] = Field(default_factory=list)
    applied_threshold: float | str | None = None
    threshold_unit: str | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> ResolvedReviewRule:
        if (
            self.status == RuleApplicability.UNDETERMINED
            and not self.missing_inputs
            and not self.rationale
        ):
            raise ValueError("UNDETERMINED rule must specify missing_inputs or rationale.")
        if self.threshold_unit is not None and self.rule.units is not None:
            validate_unit_compatibility(self.rule.units, self.threshold_unit)
        return self


class ReviewFinding(BaseModel):
    """A single semantic finding discovered during review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    rule_id: str
    rule_revision: int = 1
    severity: Literal["error", "warning", "info"] = "error"
    object_ref: str = ""
    pin: str | None = None
    net: str | None = None
    layer: str | None = None
    location_mm: tuple[float, float] | None = None
    description: str
    measured_value: float | str | None = None
    expected_value: float | str | None = None
    units: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    remediation: str = ""

    @model_validator(mode="after")
    def check_unit_consistency(self) -> ReviewFinding:
        if self.units is not None and self.units not in SUPPORTED_REVIEW_UNITS:
            raise ValueError(f"Finding unit '{self.units}' is not in SUPPORTED_REVIEW_UNITS.")
        return self


class ReviewAssessment(BaseModel):
    """Honest evaluation result for one rule on the active design."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    rule_revision: int = 1
    status: AssessmentStatus
    method: EvaluationMethod
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_honest_status(self) -> ReviewAssessment:
        if self.status == AssessmentStatus.PASS and self.findings:
            raise ValueError("Assessment cannot have status PASS when findings are present.")
        if self.status == AssessmentStatus.BLOCKED and not self.missing_inputs and not self.summary:
            raise ValueError("BLOCKED assessment must specify summary or missing_inputs.")
        return self


class ReviewCoverage(BaseModel):
    """Aggregate metrics of rule evaluation across the project."""

    model_config = ConfigDict(extra="forbid")

    total_rules: int = 0
    applicable_count: int = 0
    not_applicable_count: int = 0
    undetermined_count: int = 0
    passed_count: int = 0
    warned_count: int = 0
    failed_count: int = 0
    not_assessed_count: int = 0
    blocked_count: int = 0
    required_unassessed: list[str] = Field(default_factory=list)
    justified_exclusions: dict[str, str] = Field(default_factory=dict)


class ReviewSnapshot(BaseModel):
    """Complete, immutable snapshot of engineering review results at a single revision."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    project_key: str
    project_source_sha256: str
    rule_catalog_revision: str
    context: ReviewContext
    resolved_rules: list[ResolvedReviewRule] = Field(default_factory=list)
    assessments: list[ReviewAssessment] = Field(default_factory=list)
    coverage: ReviewCoverage = Field(default_factory=ReviewCoverage)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
