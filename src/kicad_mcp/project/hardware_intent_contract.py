"""HardwareIntentContract v1: typed requirements independent of MCP or KiCad runtime.

This bounded model never supplies verification methods, evidence, target values,
or severity for a caller. An existing design spec must be adapted explicitly, not
silently promoted to a release-blocking, verified contract.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HARDWARE_INTENT_SCHEMA_VERSION = 1
HARDWARE_INTENT_SCHEMA_ID = (
    "https://raw.githubusercontent.com/oaslananka/kicad-mcp-pro/main/"
    "src/kicad_mcp/project/schemas/hardware-intent-contract-v1.schema.json"
)
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$"

# Explicit v1 unit subset. No inferred conversions for unknown units or dimensions.
_UNIT_FACTORS: dict[str, tuple[str, str, Decimal]] = {
    "V": ("voltage", "V", Decimal(1)),
    "mV": ("voltage", "V", Decimal("0.001")),
    "A": ("current", "A", Decimal(1)),
    "mA": ("current", "A", Decimal("0.001")),
    "ohm": ("resistance", "ohm", Decimal(1)),
    "kohm": ("resistance", "ohm", Decimal(1000)),
    "mm": ("length", "mm", Decimal(1)),
    "um": ("length", "mm", Decimal("0.001")),
    "ps": ("time", "ps", Decimal(1)),
    "ns": ("time", "ps", Decimal(1000)),
    "Hz": ("frequency", "Hz", Decimal(1)),
    "kHz": ("frequency", "Hz", Decimal(1000)),
    "MHz": ("frequency", "Hz", Decimal(1000000)),
}
Unit = Literal["V", "mV", "A", "mA", "ohm", "kohm", "mm", "um", "ps", "ns", "Hz", "kHz", "MHz"]
ScopeKind = Literal["project", "component", "net", "interface", "rail", "region", "artifact"]
EvidenceClass = Literal[
    "erc", "drc", "simulation", "measurement", "inspection", "design_review", "manufacturing"
]


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class HardwareQuantity(StrictContractModel):
    """Exact decimal quantity; normalized values are paired with canonical units."""

    value: Decimal
    unit: Unit

    @field_validator("value")
    @classmethod
    def reject_non_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("quantity must be finite")
        return value

    def normalized(self) -> tuple[str, Decimal]:
        """Canonical unit and value, using decimal arithmetic only."""
        _, unit, factor = _UNIT_FACTORS[self.unit]
        return unit, self.value * factor

    @property
    def dimension(self) -> str:
        return _UNIT_FACTORS[self.unit][0]


class QuantityRange(StrictContractModel):
    """Inclusive bounds by default; equality requires inclusive endpoints."""

    minimum: HardwareQuantity | None = None
    maximum: HardwareQuantity | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.minimum is None and self.maximum is None:
            raise ValueError("range needs a minimum or maximum")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum.dimension != self.maximum.dimension:
                raise ValueError("range bound dimensions differ")
            low = self.minimum.normalized()[1]
            high = self.maximum.normalized()[1]
            if low > high or (
                low == high and not (self.minimum_inclusive and self.maximum_inclusive)
            ):
                raise ValueError("range minimum must precede maximum")
        return self


class NominalTolerance(StrictContractModel):
    """Exactly one absolute or percent tolerance about an explicit nominal value."""

    nominal: HardwareQuantity
    absolute: HardwareQuantity | None = None
    relative_pct: Decimal | None = None

    @model_validator(mode="after")
    def validate_tolerance(self) -> Self:
        if (self.absolute is None) == (self.relative_pct is None):
            raise ValueError("supply exactly one absolute or relative_pct tolerance")
        if self.absolute is not None:
            if self.absolute.dimension != self.nominal.dimension:
                raise ValueError("nominal and absolute tolerance dimensions differ")
            if self.absolute.normalized()[1] < 0:
                raise ValueError("absolute tolerance must be nonnegative")
        if self.relative_pct is not None:
            if not self.relative_pct.is_finite() or not 0 <= self.relative_pct <= 100:
                raise ValueError("relative_pct must be finite and in [0, 100]")
        return self

    def bounds(self) -> tuple[str, Decimal, Decimal]:
        unit, nominal = self.nominal.normalized()
        if self.absolute is not None:
            tolerance = self.absolute.normalized()[1]
        else:
            tolerance = abs(nominal) * cast(Decimal, self.relative_pct) / Decimal(100)
        return unit, nominal - tolerance, nominal + tolerance


class ContractScope(StrictContractModel):
    kind: ScopeKind
    key: str = Field(min_length=1, max_length=256)


class ContractVerification(StrictContractModel):
    method_ref: str = Field(min_length=1, max_length=128, pattern=_ID_PATTERN)
    evidence_classes: tuple[EvidenceClass, ...] = Field(min_length=1)

    @field_validator("evidence_classes")
    @classmethod
    def no_duplicate_evidence(
        cls, evidence: tuple[EvidenceClass, ...]
    ) -> tuple[EvidenceClass, ...]:
        if len(set(evidence)) != len(evidence):
            raise ValueError("duplicate evidence class")
        return evidence


class ContractWaiver(StrictContractModel):
    waiver_id: str = Field(min_length=3, max_length=120, pattern=_ID_PATTERN)
    contract_id: str = Field(min_length=3, max_length=120, pattern=_ID_PATTERN)
    contract_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1024)
    approved_by: str = Field(min_length=1, max_length=128)
    approval_evidence_ref: str = Field(min_length=1, max_length=256)


class ContractSeverity(StrEnum):
    INFORMATIONAL = "informational"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


class HardwareIntentContract(StrictContractModel):
    """Versioned authoritative requirement; all engineering claims explicit."""

    schema_version: Literal[1]
    contract_id: str = Field(min_length=3, max_length=120, pattern=_ID_PATTERN)
    contract_version: int = Field(ge=1)
    requirement_id: str = Field(min_length=3, max_length=120, pattern=_ID_PATTERN)
    applicability: ContractScope
    severity: ContractSeverity
    release_blocking: bool
    verification: tuple[ContractVerification, ...] = ()
    quantity_range: QuantityRange | None = None
    nominal_tolerance: NominalTolerance | None = None
    waivers: tuple[ContractWaiver, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.severity is ContractSeverity.INFORMATIONAL and self.release_blocking:
            raise ValueError("informational contract cannot block release")
        if self.severity is ContractSeverity.BLOCKING and not self.release_blocking:
            raise ValueError("blocking severity must block release")
        if self.severity is not ContractSeverity.INFORMATIONAL and not self.verification:
            raise ValueError("non-informational contract requires verification and evidence")
        if self.quantity_range is not None and self.nominal_tolerance is not None:
            raise ValueError("choose either a quantity range or nominal tolerance")
        waiver_ids: set[str] = set()
        for waiver in self.waivers:
            if (waiver.contract_id, waiver.contract_version) != (
                self.contract_id,
                self.contract_version,
            ):
                raise ValueError("waiver must bind the exact contract ID and version")
            if waiver.waiver_id in waiver_ids:
                raise ValueError("duplicate waiver ID")
            waiver_ids.add(waiver.waiver_id)
        return self


def hardware_intent_contract_json_schema() -> dict[str, Any]:
    """Deterministic JSON Schema draft 2020-12 export for v1 validation."""
    schema = HardwareIntentContract.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = HARDWARE_INTENT_SCHEMA_ID
    return schema
