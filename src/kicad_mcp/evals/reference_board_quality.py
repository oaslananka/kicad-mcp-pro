from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..ir.circuit_ir import IRCircuit
from ..ir.from_kicad import parse_schematic
from ..tools.dfm import _outline_bounds_mm
from ..tools.pcb import _parse_board_footprint_blocks
from .evidence_sanitization import validate_sanitized_evidence
from .task_outcomes import AttemptRecord, parse_attempt_record, parse_benchmark_contract

QUALITY_SCHEMA_VERSION: Literal["pcb-reference-board-quality.v1"] = "pcb-reference-board-quality.v1"
QUALITY_SCORE_SCHEMA_VERSION: Literal["pcb-reference-board-quality-score.v1"] = (
    "pcb-reference-board-quality-score.v1"
)
RuleType = Literal[
    "schematic_component",
    "schematic_net",
    "pcb_footprint",
    "pcb_net",
    "board_outline",
    "attempt_validation",
    "artifact",
]
RuleStatus = Literal["pass", "fail"]

QualityReasonCode = Literal[
    "matched",
    "component_missing",
    "identity_mismatch",
    "net_missing",
    "net_membership_mismatch",
    "footprint_missing",
    "outline_missing",
    "outline_bounds_mismatch",
    "validation_missing",
    "validation_failed",
    "artifact_missing",
    "artifact_empty",
    "evidence_missing",
    "evidence_identity_mismatch",
]


class _QualityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _QualityRuleBase(_QualityModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    required: Literal[True] = True


class SchematicComponentRule(_QualityRuleBase):
    type: Literal["schematic_component"]
    reference: str = Field(min_length=1, max_length=64)
    allowed_lib_ids: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    allowed_footprints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _require_identity_constraint(self) -> SchematicComponentRule:
        if not (self.allowed_lib_ids or self.allowed_values or self.allowed_footprints):
            raise ValueError("schematic_component requires an identity constraint")
        return self


class SchematicNetRule(_QualityRuleBase):
    type: Literal["schematic_net"]
    net_name: str = Field(min_length=1, max_length=128)
    required_references: tuple[str, ...] = ()


class PcbFootprintRule(_QualityRuleBase):
    type: Literal["pcb_footprint"]
    reference: str = Field(min_length=1, max_length=64)
    allowed_footprints: tuple[str, ...] = Field(min_length=1)


class PcbNetRule(_QualityRuleBase):
    type: Literal["pcb_net"]
    net_name: str = Field(min_length=1, max_length=128)
    required_references: tuple[str, ...] = ()


class BoardOutlineRule(_QualityRuleBase):
    type: Literal["board_outline"]
    min_width_mm: float | None = Field(default=None, gt=0)
    max_width_mm: float | None = Field(default=None, gt=0)
    min_height_mm: float | None = Field(default=None, gt=0)
    max_height_mm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_bounds(self) -> BoardOutlineRule:
        if (
            self.min_width_mm is not None
            and self.max_width_mm is not None
            and self.min_width_mm > self.max_width_mm
        ):
            raise ValueError("outline width bounds are inverted")
        if (
            self.min_height_mm is not None
            and self.max_height_mm is not None
            and self.min_height_mm > self.max_height_mm
        ):
            raise ValueError("outline height bounds are inverted")
        return self


class AttemptValidationRule(_QualityRuleBase):
    type: Literal["attempt_validation"]
    validation_kind: Literal["erc", "drc"]


class ArtifactRule(_QualityRuleBase):
    type: Literal["artifact"]
    path: str = Field(min_length=1, max_length=256)
    kind: Literal["file", "directory"]

    @model_validator(mode="after")
    def _require_relative_path(self) -> ArtifactRule:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or self.path.startswith(("/", "\\")):
            raise ValueError("artifact path must be canonical and relative")
        return self


RuleModel = (
    SchematicComponentRule
    | SchematicNetRule
    | PcbFootprintRule
    | PcbNetRule
    | BoardOutlineRule
    | AttemptValidationRule
    | ArtifactRule
)
QualityRule = Annotated[RuleModel, Field(discriminator="type")]


class BoardQualityContract(_QualityModel):
    schema_version: Literal["pcb-reference-board-quality.v1"] = QUALITY_SCHEMA_VERSION
    board_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    benchmark_version: str = Field(min_length=1, max_length=128)
    rules: tuple[QualityRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_unique_rule_ids(self) -> BoardQualityContract:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("quality rule ids must be unique")
        return self


class QualityRuleResult(_QualityModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    type: RuleType
    status: RuleStatus
    reason_code: QualityReasonCode


class BoardQualityScore(_QualityModel):
    schema_version: Literal["pcb-reference-board-quality-score.v1"] = QUALITY_SCORE_SCHEMA_VERSION
    board_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    benchmark_version: str = Field(min_length=1, max_length=128)
    attempt_id: str = Field(min_length=1, max_length=128)
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    required_rule_count: int = Field(ge=1)
    passed_required_rule_count: int = Field(ge=0)
    quality_score_percent: float = Field(ge=0.0, le=100.0)
    overall_pass: bool
    results: tuple[QualityRuleResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_counts(self) -> BoardQualityScore:
        if self.passed_required_rule_count > self.required_rule_count:
            raise ValueError("passed required rule count exceeds total")
        if len(self.results) != self.required_rule_count:
            raise ValueError("quality result count must match required rule count")
        passed = sum(item.status == "pass" for item in self.results)
        if passed != self.passed_required_rule_count:
            raise ValueError("quality pass count does not match rule results")
        expected = round((passed / self.required_rule_count) * 100.0, 2)
        if self.quality_score_percent != expected:
            raise ValueError("quality score percent does not match rule results")
        if self.overall_pass != (passed == self.required_rule_count):
            raise ValueError("overall pass must require every rule to pass")
        return self


def parse_quality_contract(payload: Mapping[str, object]) -> BoardQualityContract:
    return BoardQualityContract.model_validate(payload)


def parse_quality_score(payload: Mapping[str, object]) -> BoardQualityScore:
    return BoardQualityScore.model_validate(payload)


def render_quality_score(score: BoardQualityScore) -> str:
    payload = score.model_dump(mode="json")
    validate_sanitized_evidence(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


SchematicRule = SchematicComponentRule | SchematicNetRule
PcbRule = PcbFootprintRule | PcbNetRule | BoardOutlineRule


def _rule_result(
    rule: RuleModel, status: RuleStatus, reason_code: QualityReasonCode
) -> QualityRuleResult:
    return QualityRuleResult(id=rule.id, type=rule.type, status=status, reason_code=reason_code)


def evaluate_schematic_rule(rule: SchematicRule, circuit: IRCircuit) -> QualityRuleResult:
    if isinstance(rule, SchematicComponentRule):
        component = circuit.components.get(rule.reference)
        if component is None:
            return _rule_result(rule, "fail", "component_missing")
        matches = (
            (not rule.allowed_lib_ids or component.lib_id in rule.allowed_lib_ids)
            and (not rule.allowed_values or component.value in rule.allowed_values)
            and (not rule.allowed_footprints or component.footprint in rule.allowed_footprints)
        )
        return (
            _rule_result(rule, "pass", "matched")
            if matches
            else _rule_result(rule, "fail", "identity_mismatch")
        )

    net = circuit.nets.get(rule.net_name)
    if net is None:
        return _rule_result(rule, "fail", "net_missing")
    connected_references = {reference for reference, _pin in net.connections}
    if not set(rule.required_references).issubset(connected_references):
        return _rule_result(rule, "fail", "net_membership_mismatch")
    return _rule_result(rule, "pass", "matched")


def evaluate_pcb_rule(rule: PcbRule, board_text: str) -> QualityRuleResult:
    if isinstance(rule, BoardOutlineRule):
        bounds = _outline_bounds_mm(board_text)
        if bounds is None:
            return _rule_result(rule, "fail", "outline_missing")
        min_x, min_y, max_x, max_y = bounds
        width = max_x - min_x
        height = max_y - min_y
        in_bounds = (
            (rule.min_width_mm is None or width >= rule.min_width_mm)
            and (rule.max_width_mm is None or width <= rule.max_width_mm)
            and (rule.min_height_mm is None or height >= rule.min_height_mm)
            and (rule.max_height_mm is None or height <= rule.max_height_mm)
        )
        return (
            _rule_result(rule, "pass", "matched")
            if in_bounds
            else _rule_result(rule, "fail", "outline_bounds_mismatch")
        )

    footprints = _parse_board_footprint_blocks(board_text)
    if isinstance(rule, PcbFootprintRule):
        footprint = footprints.get(rule.reference)
        if footprint is None:
            return _rule_result(rule, "fail", "footprint_missing")
        if footprint["name"] not in rule.allowed_footprints:
            return _rule_result(rule, "fail", "identity_mismatch")
        return _rule_result(rule, "pass", "matched")

    references_on_net = {
        reference
        for reference, footprint in footprints.items()
        if rule.net_name in footprint["net_names"]
    }
    if not references_on_net:
        return _rule_result(rule, "fail", "net_missing")
    if not set(rule.required_references).issubset(references_on_net):
        return _rule_result(rule, "fail", "net_membership_mismatch")
    return _rule_result(rule, "pass", "matched")


def evaluate_attempt_rule(rule: AttemptValidationRule, attempt: AttemptRecord) -> QualityRuleResult:
    validation = next(
        (item for item in attempt.validations if item.kind == rule.validation_kind),
        None,
    )
    if validation is None:
        return _rule_result(rule, "fail", "validation_missing")
    passed = (
        validation.required
        and validation.execution_completed
        and validation.result_consumed
        and validation.disposition in {"resolved", "accepted"}
    )
    return (
        _rule_result(rule, "pass", "matched")
        if passed
        else _rule_result(rule, "fail", "validation_failed")
    )


def evaluate_artifact_rule(rule: ArtifactRule, attempt_root: Path) -> QualityRuleResult:
    root = attempt_root.resolve()
    relative = Path(*PurePosixPath(rule.path).parts)
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return _rule_result(rule, "fail", "artifact_missing")
    if candidate.is_symlink():
        return _rule_result(rule, "fail", "artifact_missing")
    if rule.kind == "file":
        if not resolved.is_file():
            return _rule_result(rule, "fail", "artifact_missing")
        if resolved.stat().st_size == 0:
            return _rule_result(rule, "fail", "artifact_empty")
    elif not resolved.is_dir():
        return _rule_result(rule, "fail", "artifact_missing")
    elif next(resolved.iterdir(), None) is None:
        return _rule_result(rule, "fail", "artifact_empty")
    return _rule_result(rule, "pass", "matched")


def _load_json_mapping(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("quality evidence file must contain one JSON object")
    validate_sanitized_evidence(payload)
    return payload


def _failed_result(rule: RuleModel, reason: QualityReasonCode) -> QualityRuleResult:
    return _rule_result(rule, "fail", reason)


def _build_quality_score(
    contract: BoardQualityContract,
    attempt: AttemptRecord,
    results: list[QualityRuleResult],
) -> BoardQualityScore:
    passed = sum(result.status == "pass" for result in results)
    total = len(results)
    return BoardQualityScore(
        board_id=contract.board_id,
        benchmark_version=contract.benchmark_version,
        attempt_id=attempt.attempt_id,
        source_revision=attempt.source_revision,
        required_rule_count=total,
        passed_required_rule_count=passed,
        quality_score_percent=round((passed / total) * 100.0, 2),
        overall_pass=passed == total,
        results=tuple(results),
    )


def score_reference_board_attempt(bundle_root: Path, attempt_id: str) -> BoardQualityScore:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", attempt_id) is None:
        raise ValueError("attempt id must be canonical")
    root = bundle_root.resolve(strict=True)
    attempt_dir = root / "attempts" / attempt_id
    attempt = parse_attempt_record(_load_json_mapping(attempt_dir / "attempt.json"))
    benchmark = parse_benchmark_contract(_load_json_mapping(root / "benchmark.json"))
    quality = parse_quality_contract(_load_json_mapping(root / "quality-gates.json"))

    identity_matches = (
        attempt.attempt_id == attempt_id
        and quality.board_id == root.parent.name
        and quality.benchmark_version == root.name
        and attempt.benchmark_id == benchmark.benchmark_id
        and attempt.benchmark_version == benchmark.benchmark_version
        and quality.benchmark_version == benchmark.benchmark_version
    )
    if not identity_matches:
        return _build_quality_score(
            quality,
            attempt,
            [_failed_result(rule, "evidence_identity_mismatch") for rule in quality.rules],
        )

    schematic_path = attempt_dir / "schematic.kicad_sch"
    board_path = attempt_dir / "board.kicad_pcb"
    needs_schematic = any(
        isinstance(rule, (SchematicComponentRule, SchematicNetRule)) for rule in quality.rules
    )
    needs_board = any(
        isinstance(rule, (PcbFootprintRule, PcbNetRule, BoardOutlineRule)) for rule in quality.rules
    )

    circuit: IRCircuit | None = None
    if needs_schematic and schematic_path.is_file() and not schematic_path.is_symlink():
        try:
            circuit = parse_schematic(schematic_path, load_pin_metadata=False)
        except (OSError, RuntimeError, ValueError):
            circuit = None

    board_text: str | None = None
    if needs_board and board_path.is_file() and not board_path.is_symlink():
        try:
            board_text = board_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            board_text = None

    results: list[QualityRuleResult] = []
    for rule in quality.rules:
        if isinstance(rule, (SchematicComponentRule, SchematicNetRule)):
            result = (
                _failed_result(rule, "evidence_missing")
                if circuit is None
                else evaluate_schematic_rule(rule, circuit)
            )
        elif isinstance(rule, (PcbFootprintRule, PcbNetRule, BoardOutlineRule)):
            result = (
                _failed_result(rule, "evidence_missing")
                if board_text is None
                else evaluate_pcb_rule(rule, board_text)
            )
        elif isinstance(rule, AttemptValidationRule):
            result = evaluate_attempt_rule(rule, attempt)
        else:
            result = evaluate_artifact_rule(rule, attempt_dir)
        results.append(result)
    return _build_quality_score(quality, attempt, results)
