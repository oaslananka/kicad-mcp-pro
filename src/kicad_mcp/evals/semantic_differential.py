"""Versioned diagnostic evidence for native KiCad semantic differentials."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence_sanitization import validate_sanitized_evidence

DIFFERENTIAL_RESULT_SCHEMA_VERSION: Literal["kicad-semantic-differential-result.v1"] = (
    "kicad-semantic-differential-result.v1"
)
DIFFERENTIAL_REPORT_SCHEMA_VERSION: Literal["kicad-semantic-differential-report.v1"] = (
    "kicad-semantic-differential-report.v1"
)

DifferentialLane = Literal["stable", "preview"]
DifferentialStatus = Literal[
    "match",
    "divergence",
    "unavailable-authority",
    "infrastructure-invalid",
]
SourceSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40,64}$")]
ContentHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class _DifferentialModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DifferentialResult(_DifferentialModel):
    """One normalized comparison between MCP Pro output and native KiCad authority."""

    schema_version: Literal["kicad-semantic-differential-result.v1"] = (
        DIFFERENTIAL_RESULT_SCHEMA_VERSION
    )
    source_sha: SourceSha
    lane: DifferentialLane
    kicad_version: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    fixture_hash: ContentHash
    operation: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    comparison_method: str = Field(min_length=1)
    status: DifferentialStatus
    native_result_hash: ContentHash | None = None
    custom_result_hash: ContentHash | None = None
    native_pass: bool | None = None
    custom_pass: bool | None = None
    false_pass: bool = False
    false_fail: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_semantic_consistency(self) -> Self:
        if self.false_pass and self.false_fail:
            raise ValueError("false_pass and false_fail cannot both be true")

        if self.status in {"match", "divergence"}:
            if self.native_result_hash is None or self.custom_result_hash is None:
                raise ValueError(f"{self.status} requires native and custom result hashes")
            hashes_equal = self.native_result_hash == self.custom_result_hash
            if self.status == "match" and not hashes_equal:
                raise ValueError("match requires equal native/custom result hashes")
            if self.status == "divergence" and hashes_equal:
                raise ValueError("divergence requires different native/custom result hashes")
        elif not self.reason:
            raise ValueError(f"{self.status} requires a reason")

        if self.status == "unavailable-authority" and (
            self.native_result_hash is not None or self.native_pass is not None
        ):
            raise ValueError("unavailable-authority cannot carry native authority evidence")

        expected_false_pass = (
            self.status == "divergence" and self.native_pass is False and self.custom_pass is True
        )
        expected_false_fail = (
            self.status == "divergence" and self.native_pass is True and self.custom_pass is False
        )
        if self.false_pass != expected_false_pass:
            raise ValueError("false_pass must reflect native FAIL versus custom PASS")
        if self.false_fail != expected_false_fail:
            raise ValueError("false_fail must reflect native PASS versus custom FAIL")
        if self.status == "match" and (
            self.native_pass is not None
            and self.custom_pass is not None
            and self.native_pass != self.custom_pass
        ):
            raise ValueError("match cannot carry conflicting native/custom pass outcomes")
        return self


class DifferentialReport(_DifferentialModel):
    """Deterministic per-lane aggregate of differential diagnostic evidence."""

    schema_version: Literal["kicad-semantic-differential-report.v1"] = (
        DIFFERENTIAL_REPORT_SCHEMA_VERSION
    )
    source_sha: SourceSha
    lane: DifferentialLane
    kicad_version: str = Field(min_length=1)
    results_total: int = Field(ge=0)
    match_count: int = Field(ge=0)
    divergence_count: int = Field(ge=0)
    unavailable_authority_count: int = Field(ge=0)
    infrastructure_invalid_count: int = Field(ge=0)
    false_pass_count: int = Field(ge=0)
    false_fail_count: int = Field(ge=0)
    results: tuple[DifferentialResult, ...]

    @model_validator(mode="after")
    def _validate_counts(self) -> Self:
        expected = {
            "match_count": sum(result.status == "match" for result in self.results),
            "divergence_count": sum(result.status == "divergence" for result in self.results),
            "unavailable_authority_count": sum(
                result.status == "unavailable-authority" for result in self.results
            ),
            "infrastructure_invalid_count": sum(
                result.status == "infrastructure-invalid" for result in self.results
            ),
            "false_pass_count": sum(result.false_pass for result in self.results),
            "false_fail_count": sum(result.false_fail for result in self.results),
        }
        if self.results_total != len(self.results):
            raise ValueError("results_total must equal the number of result records")
        for field_name, count in expected.items():
            if getattr(self, field_name) != count:
                raise ValueError(f"{field_name} does not match result records")
        if self.results_total != sum(
            (
                self.match_count,
                self.divergence_count,
                self.unavailable_authority_count,
                self.infrastructure_invalid_count,
            )
        ):
            raise ValueError("status counts must partition all result records")
        return self


def classify_differential_result(
    *,
    source_sha: str,
    lane: DifferentialLane,
    kicad_version: str,
    fixture_id: str,
    fixture_hash: str,
    operation: str,
    authority: str,
    comparison_method: str,
    native_result_hash: str | None,
    custom_result_hash: str | None,
    native_pass: bool | None = None,
    custom_pass: bool | None = None,
    authority_available: bool = True,
    infrastructure_valid: bool = True,
    reason: str | None = None,
) -> DifferentialResult:
    """Classify one differential without manufacturing native equivalence."""
    if not infrastructure_valid:
        status: DifferentialStatus = "infrastructure-invalid"
    elif not authority_available:
        if native_result_hash is not None or native_pass is not None:
            raise ValueError("Unavailable native authority cannot provide native evidence")
        status = "unavailable-authority"
    else:
        if native_result_hash is None or custom_result_hash is None:
            raise ValueError("Native and custom hashes are required when authority is available")
        status = "match" if native_result_hash == custom_result_hash else "divergence"

    false_pass = status == "divergence" and native_pass is False and custom_pass is True
    false_fail = status == "divergence" and native_pass is True and custom_pass is False
    return DifferentialResult(
        source_sha=source_sha,
        lane=lane,
        kicad_version=kicad_version,
        fixture_id=fixture_id,
        fixture_hash=fixture_hash,
        operation=operation,
        authority=authority,
        comparison_method=comparison_method,
        status=status,
        native_result_hash=native_result_hash,
        custom_result_hash=custom_result_hash,
        native_pass=native_pass,
        custom_pass=custom_pass,
        false_pass=false_pass,
        false_fail=false_fail,
        reason=reason,
    )


def aggregate_differential_results(results: Iterable[DifferentialResult]) -> DifferentialReport:
    """Aggregate one exact source/lane/KiCad-version result set."""
    records = tuple(results)
    if not records:
        raise ValueError("At least one differential result is required")
    identity = (records[0].source_sha, records[0].lane, records[0].kicad_version)
    if any((item.source_sha, item.lane, item.kicad_version) != identity for item in records[1:]):
        raise ValueError(
            "Differential results must share the same source SHA, lane, and KiCad version"
        )
    return DifferentialReport(
        source_sha=identity[0],
        lane=identity[1],
        kicad_version=identity[2],
        results_total=len(records),
        match_count=sum(item.status == "match" for item in records),
        divergence_count=sum(item.status == "divergence" for item in records),
        unavailable_authority_count=sum(item.status == "unavailable-authority" for item in records),
        infrastructure_invalid_count=sum(
            item.status == "infrastructure-invalid" for item in records
        ),
        false_pass_count=sum(item.false_pass for item in records),
        false_fail_count=sum(item.false_fail for item in records),
        results=records,
    )


def render_differential_report_json(report: DifferentialReport) -> str:
    """Render deterministic sanitized machine-readable differential evidence."""
    payload = report.model_dump(mode="json", exclude_none=True)
    validate_sanitized_evidence(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


__all__ = [
    "DIFFERENTIAL_REPORT_SCHEMA_VERSION",
    "DIFFERENTIAL_RESULT_SCHEMA_VERSION",
    "DifferentialLane",
    "DifferentialReport",
    "DifferentialResult",
    "DifferentialStatus",
    "aggregate_differential_results",
    "classify_differential_result",
    "render_differential_report_json",
]
