"""Conservative adaptation of existing explicit project design-spec values.

The existing project-spec fields are inputs, not authority to invent contract IDs,
verification, waiver approvals, tolerances or release-blocking semantics.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Literal

from pydantic import Field, ValidationError

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


_SOURCE_UNIT: dict[DesignSpecSourceField, str] = {
    "power_rail_voltage": "V",
    "power_rail_current_max": "A",
    "interface_impedance": "ohm",
    "interface_skew_max": "ps",
}


def _explicit_source_value(
    explicit: ProjectDesignIntent, binding: ContractConversionBinding
) -> tuple[Decimal | None, str | None]:
    """Resolve a named source or report missing/ambiguous provenance."""
    if binding.source_field.startswith("power_rail_"):
        matched = [rail for rail in explicit.power_rails if rail.name == binding.source_key]
        if not matched:
            return None, "source rail not found in explicit design intent"
        if len(matched) != 1:
            return None, "source rail name is ambiguous"
        rail = matched[0]
        scalar = (
            rail.voltage_v
            if binding.source_field == "power_rail_voltage"
            else rail.current_max_a
        )
    else:
        matched = [iface for iface in explicit.interfaces if iface.kind == binding.source_key]
        if not matched:
            return None, "source interface not found in explicit design intent"
        if len(matched) != 1:
            return None, "source interface kind is ambiguous; use a unique explicit source"
        iface = matched[0]
        scalar = (
            iface.impedance_target_ohm
            if binding.source_field == "interface_impedance"
            else iface.diff_skew_max_ps
        )
        if scalar is None:
            return None, "selected interface quantity is unspecified"
    value = Decimal(str(scalar))
    if not value.is_finite():
        return None, "source quantity is not finite"
    return value, None


def adapt_explicit_design_spec_contracts(
    resolution: ProjectSpecResolution,
    bindings: tuple[ContractConversionBinding, ...],
) -> ContractConversionResult:
    """Convert approved binding metadata + explicit spec scalars without guessing.

    Import/source provenance is mandatory. Only resolution.explicit is used:
    resolution.resolved can contain inferred PCB heuristics, so reading it as
    an authored requirement would silently promote guesses to release gates.

    No files or graphs are mutated. An incomplete conversion returns an
    explicit unresolved record with the original binding identity.
    """
    contracts: list[HardwareIntentContract] = []
    unresolved: list[ContractConversionUnresolved] = []
    counts = Counter(
        binding.contract_id
        for binding in bindings
        if binding.contract_id is not None
    )
    for binding in bindings:
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
        if counts[binding.contract_id] > 1:
            reasons.append("duplicate contract ID in conversion bindings")
        if resolution.source not in {"project_spec", "legacy_design_intent"}:
            reasons.append("no explicit persisted project design-spec source")

        rail_source = binding.source_field.startswith("power_rail_")
        if binding.applicability is not None:
            expected_scope = "rail" if rail_source else "interface"
            if binding.applicability.kind != expected_scope:
                reasons.append(f"source requires {expected_scope} applicability")
            if rail_source and binding.applicability.key != binding.source_key:
                reasons.append("rail applicability key must match explicit rail name")

        maximum_source = binding.source_field in {
            "power_rail_current_max",
            "interface_skew_max",
        }
        if maximum_source and (
            binding.relative_pct is not None or binding.absolute_tolerance is not None
        ):
            reasons.append("maximum-only quantity does not accept a tolerance")
        if not maximum_source and (
            (binding.relative_pct is None) == (binding.absolute_tolerance is None)
        ):
            reasons.append("nominal quantity needs exactly one reviewer-authored tolerance")

        value, missing_source = _explicit_source_value(resolution.explicit, binding)
        if missing_source is not None:
            reasons.append(missing_source)

        if reasons:
            unresolved.append(
                ContractConversionUnresolved(
                    source_field=binding.source_field,
                    source_key=binding.source_key,
                    contract_id=binding.contract_id,
                    reasons=tuple(reasons),
                )
            )
            continue

        if value is None or binding.applicability is None:
            raise RuntimeError("unresolved source value was not rejected")
        if binding.contract_id is None or binding.requirement_id is None:
            raise RuntimeError("unresolved contract identity was not rejected")
        if binding.contract_version is None or binding.severity is None:
            raise RuntimeError("unresolved version or severity was not rejected")
        if binding.release_blocking is None:
            raise RuntimeError("unresolved release policy was not rejected")

        quantity = HardwareQuantity(value=value, unit=_SOURCE_UNIT[binding.source_field])
        try:
            constraint: dict[str, object]
            if maximum_source:
                constraint = {"quantity_range": QuantityRange(maximum=quantity)}
            else:
                constraint = {
                    "nominal_tolerance": NominalTolerance(
                        nominal=quantity,
                        absolute=binding.absolute_tolerance,
                        relative_pct=binding.relative_pct,
                    )
                }
            contract = HardwareIntentContract(
                schema_version=1,
                contract_id=binding.contract_id,
                contract_version=binding.contract_version,
                requirement_id=binding.requirement_id,
                applicability=binding.applicability,
                severity=binding.severity,
                release_blocking=binding.release_blocking,
                verification=binding.verification,
                waivers=binding.waivers,
                **constraint,
            )
        except (ValidationError, ValueError) as exc:
            unresolved.append(
                ContractConversionUnresolved(
                    source_field=binding.source_field,
                    source_key=binding.source_key,
                    contract_id=binding.contract_id,
                    reasons=(f"contract validation failed: {exc}",),
                )
            )
            continue
        contracts.append(contract)

    return ContractConversionResult(
        contracts=tuple(contracts),
        unresolved=tuple(unresolved),
    )
