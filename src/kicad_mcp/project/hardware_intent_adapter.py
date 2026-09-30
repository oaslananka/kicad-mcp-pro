"""Conservative adaptation of existing explicit project design-spec values.

The existing project-spec fields are inputs, not authority to invent contract IDs,
verification, waiver approvals, tolerances or release-blocking semantics.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Literal, cast

from pydantic import Field

from ..tools.design_intent_state import ProjectDesignIntent, ProjectSpecResolution
from .hardware_intent_contract import (
    ContractScope,
    ContractSeverity,
    ContractVerification,
    ContractWaiver,
    HardwareIntentContract,
    HardwareQuantity,
    NominalTolerance,
    QuantityRange,
    StrictContractModel,
    Unit,
)

DesignSpecSourceField = Literal[
    "power_rail_voltage",
    "power_rail_current_max",
    "interface_impedance",
    "interface_skew_max",
]


class ContractConversionBinding(StrictContractModel):
    """Reviewer-authored binding; absence is unresolved, never defaulted."""

    source_field: DesignSpecSourceField
    source_key: str = Field(min_length=1, max_length=120)
    contract_id: str | None = Field(
        default=None, min_length=3, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$"
    )
    contract_version: int | None = Field(default=None, ge=1)
    requirement_id: str | None = Field(
        default=None, min_length=3, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$"
    )
    applicability: ContractScope | None = None
    severity: ContractSeverity | None = None
    release_blocking: bool | None = None
    verification: tuple[ContractVerification, ...] = ()
    relative_pct: Decimal | None = None
    absolute_tolerance: HardwareQuantity | None = None
    waivers: tuple[ContractWaiver, ...] = ()


class ContractConversionUnresolved(StrictContractModel):
    source_field: DesignSpecSourceField
    source_key: str
    contract_id: str | None = None
    reasons: tuple[str, ...] = Field(min_length=1)


class ContractConversionResult(StrictContractModel):
    contracts: tuple[HardwareIntentContract, ...] = ()
    unresolved: tuple[ContractConversionUnresolved, ...] = ()


_SOURCE_UNIT: dict[DesignSpecSourceField, Unit] = {
    "power_rail_voltage": "V",
    "power_rail_current_max": "A",
    "interface_impedance": "ohm",
    "interface_skew_max": "ps",
}


def _rail_source_scalar(
    explicit: ProjectDesignIntent, binding: ContractConversionBinding
) -> tuple[float | None, str | None]:
    matched = [rail for rail in explicit.power_rails if rail.name == binding.source_key]
    if not matched:
        return None, "source rail not found in explicit design intent"
    if len(matched) != 1:
        return None, "source rail name is ambiguous"
    rail = matched[0]
    value = rail.voltage_v if binding.source_field == "power_rail_voltage" else rail.current_max_a
    return value, None


def _interface_source_scalar(
    explicit: ProjectDesignIntent, binding: ContractConversionBinding
) -> tuple[float | None, str | None]:
    matched = [iface for iface in explicit.interfaces if iface.kind == binding.source_key]
    if not matched:
        return None, "source interface not found in explicit design intent"
    if len(matched) != 1:
        return None, "source interface kind is ambiguous; use a unique explicit source"
    iface = matched[0]
    value = (
        iface.impedance_target_ohm
        if binding.source_field == "interface_impedance"
        else iface.diff_skew_max_ps
    )
    if value is None:
        return None, "selected interface quantity is unspecified"
    return value, None


def _explicit_source_value(
    explicit: ProjectDesignIntent, binding: ContractConversionBinding
) -> tuple[Decimal | None, str | None]:
    """Look up an authored source scalar and preserve missing/ambiguous provenance."""
    if binding.source_field.startswith("power_rail_"):
        raw_value, reason = _rail_source_scalar(explicit, binding)
    else:
        raw_value, reason = _interface_source_scalar(explicit, binding)
    if reason is not None:
        return None, reason
    if raw_value is None:
        return None, "selected source quantity is unspecified"
    value = Decimal(str(raw_value))
    if not value.is_finite():
        return None, "source quantity is not finite"
    return value, None


def _binding_metadata_reasons(
    binding: ContractConversionBinding,
    *,
    duplicate_id: bool,
    source: str,
) -> list[str]:
    reasons: list[str] = []
    for field_name in (
        "contract_id",
        "contract_version",
        "requirement_id",
        "applicability",
        "severity",
        "release_blocking",
    ):
        if getattr(binding, field_name) is None:
            reasons.append(f"missing reviewer-authored {field_name}")
    if binding.severity is not ContractSeverity.INFORMATIONAL and not binding.verification:
        reasons.append("missing reviewer-authored verification/evidence")
    if duplicate_id:
        reasons.append("duplicate contract ID in conversion bindings")
    if source not in {"project_spec", "legacy_design_intent"}:
        reasons.append("no explicit persisted project design-spec source")
    return reasons


def _binding_quantity_reasons(binding: ContractConversionBinding) -> list[str]:
    """Fail closed when source and reviewer-approved dimensions do not align."""
    reasons: list[str] = []
    is_rail = binding.source_field.startswith("power_rail_")
    if binding.applicability is not None:
        expected_scope = "rail" if is_rail else "interface"
        if binding.applicability.kind != expected_scope:
            reasons.append(f"source requires {expected_scope} applicability")
        if is_rail and binding.applicability.key != binding.source_key:
            reasons.append("rail applicability key must match explicit rail name")

    is_maximum = binding.source_field in {"power_rail_current_max", "interface_skew_max"}
    has_relative = binding.relative_pct is not None
    has_absolute = binding.absolute_tolerance is not None
    if is_maximum and (has_relative or has_absolute):
        reasons.append("maximum-only quantity does not accept a tolerance")
    if not is_maximum and has_relative == has_absolute:
        reasons.append("nominal quantity needs exactly one reviewer-authored tolerance")
    return reasons


def _contract_from_binding(
    binding: ContractConversionBinding, value: Decimal
) -> HardwareIntentContract:
    """Create a contract only after all mandatory reviewer metadata is validated."""
    quantity = HardwareQuantity(value=value, unit=_SOURCE_UNIT[binding.source_field])
    quantity_range: QuantityRange | None = None
    nominal_tolerance: NominalTolerance | None = None
    if binding.source_field in {"power_rail_current_max", "interface_skew_max"}:
        quantity_range = QuantityRange(maximum=quantity)
    else:
        nominal_tolerance = NominalTolerance(
            nominal=quantity,
            absolute=binding.absolute_tolerance,
            relative_pct=binding.relative_pct,
        )
    return HardwareIntentContract(
        schema_version=1,
        contract_id=cast(str, binding.contract_id),
        contract_version=cast(int, binding.contract_version),
        requirement_id=cast(str, binding.requirement_id),
        applicability=cast(ContractScope, binding.applicability),
        severity=cast(ContractSeverity, binding.severity),
        release_blocking=cast(bool, binding.release_blocking),
        verification=binding.verification,
        waivers=binding.waivers,
        quantity_range=quantity_range,
        nominal_tolerance=nominal_tolerance,
    )


def _unresolved_binding(
    binding: ContractConversionBinding, reasons: list[str]
) -> ContractConversionUnresolved:
    return ContractConversionUnresolved(
        source_field=binding.source_field,
        source_key=binding.source_key,
        contract_id=binding.contract_id,
        reasons=tuple(reasons),
    )


def adapt_explicit_design_spec_contracts(
    resolution: ProjectSpecResolution,
    bindings: tuple[ContractConversionBinding, ...],
) -> ContractConversionResult:
    """Convert reviewer-authored bindings and *explicit* persisted source scalars.

    Never promote inferred ProjectDesignIntent fields or guess missing contracts,
    severity, tolerances, evidence classes, graph IDs or waivers. No project or
    graph is mutated; all unresolved fields retain a source identity and reason.
    """
    contracts: list[HardwareIntentContract] = []
    unresolved: list[ContractConversionUnresolved] = []
    counts = Counter(binding.contract_id for binding in bindings if binding.contract_id is not None)
    for binding in bindings:
        reasons = _binding_metadata_reasons(
            binding,
            duplicate_id=binding.contract_id is not None and counts[binding.contract_id] > 1,
            source=resolution.source,
        )
        reasons.extend(_binding_quantity_reasons(binding))
        value, source_issue = _explicit_source_value(resolution.explicit, binding)
        if source_issue is not None:
            reasons.append(source_issue)
        if reasons:
            unresolved.append(_unresolved_binding(binding, reasons))
            continue
        try:
            contracts.append(_contract_from_binding(binding, cast(Decimal, value)))
        except ValueError as exc:
            unresolved.append(_unresolved_binding(binding, [f"contract validation failed: {exc}"]))
    return ContractConversionResult(contracts=tuple(contracts), unresolved=tuple(unresolved))
