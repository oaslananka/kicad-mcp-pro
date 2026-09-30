"""Conservative ProjectDesignIntent -> HardwareIntentContract conversion (#941)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kicad_mcp.ir.engineering_graph import (
    EngineeringGraph,
    GraphEntity,
    GraphEntityKind,
    GraphProvenance,
    GraphProvenanceKind,
    canonical_entity_id,
)
from kicad_mcp.models.intent import InterfaceSpec, PowerRailSpec
from kicad_mcp.project.hardware_intent_adapter import (
    ContractConversionBinding,
    adapt_explicit_design_spec_contracts,
)
from kicad_mcp.project.hardware_intent_contract import HardwareIntentContract
from kicad_mcp.project.hardware_intent_graph import link_hardware_intent_contract
from kicad_mcp.tools.design_intent_state import ProjectDesignIntent, ProjectSpecResolution


def _explicit_spec() -> ProjectDesignIntent:
    # Same typed rail and USB2 fields covered by project_import_design_spec's YAML fixture.
    return ProjectDesignIntent(
        required_sheets=["Power_USB_OR", "MCU_Service"],
        critical_nets=["USB_DP", "USB_DN"],
        power_rails=[PowerRailSpec(name="+3V3", voltage_v=3.3, current_max_a=1.0, source_ref="U3")],
        interfaces=[
            InterfaceSpec(
                kind="usb2",
                refs=["J1", "U1"],
                differential=True,
                impedance_target_ohm=90.0,
                diff_skew_max_ps=80.0,
            )
        ],
    )


def _resolution(**overrides: object) -> ProjectSpecResolution:
    fields: dict[str, object] = {
        "source": "project_spec",
        "explicit": _explicit_spec(),
        "inferred": ProjectDesignIntent(),
        "resolved": _explicit_spec(),
    }
    fields.update(overrides)
    return ProjectSpecResolution.model_validate(fields)


def _binding(**overrides: object) -> ContractConversionBinding:
    fields: dict[str, object] = {
        "source_field": "power_rail_voltage",
        "source_key": "+3V3",
        "contract_id": "INTENT-3V3",
        "contract_version": 1,
        "requirement_id": "REQ-3V3",
        "applicability": {"kind": "rail", "key": "+3V3"},
        "severity": "blocking",
        "release_blocking": True,
        "verification": [{"method_ref": "erc", "evidence_classes": ["erc"]}],
        "relative_pct": "3",
    }
    fields.update(overrides)
    return ContractConversionBinding.model_validate(fields)


def test_explicit_rail_voltage_converts_with_authored_tolerance() -> None:
    result = adapt_explicit_design_spec_contracts(_resolution(), (_binding(),))
    assert not result.unresolved
    assert len(result.contracts) == 1
    contract = result.contracts[0]
    assert contract.contract_id == "INTENT-3V3"
    assert contract.nominal_tolerance is not None
    assert contract.nominal_tolerance.nominal.normalized() == ("V", Decimal("3.3"))
    assert contract.nominal_tolerance.bounds() == (
        "V",
        Decimal("3.201"),
        Decimal("3.399"),
    )
    assert contract.waivers == ()
    assert HardwareIntentContract.model_validate_json(contract.model_dump_json()) == contract


def test_current_limit_and_usb_impedance_convert_from_explicit_fixture() -> None:
    limits = _binding(
        source_field="power_rail_current_max",
        contract_id="INTENT-CURRENT",
        requirement_id="REQ-CURRENT",
        relative_pct=None,
    )
    usb = _binding(
        source_field="interface_impedance",
        source_key="usb2",
        contract_id="INTENT-USB-Z0",
        requirement_id="REQ-USB-Z0",
        applicability={"kind": "interface", "key": "USB"},
        relative_pct="10",
        verification=[{"method_ref": "si_check", "evidence_classes": ["simulation"]}],
    )
    result = adapt_explicit_design_spec_contracts(_resolution(), (limits, usb))
    assert result.unresolved == ()
    assert len(result.contracts) == 2
    current, impedance = result.contracts
    assert current.quantity_range is not None
    assert current.quantity_range.maximum is not None
    assert current.quantity_range.maximum.normalized() == ("A", Decimal("1.0"))
    assert current.nominal_tolerance is None
    assert impedance.nominal_tolerance is not None
    assert impedance.nominal_tolerance.bounds() == ("ohm", Decimal("81.00"), Decimal("99.00"))


def test_missing_author_metadata_never_invents_release_policy_or_evidence() -> None:
    binding = ContractConversionBinding(source_field="power_rail_voltage", source_key="+3V3")
    result = adapt_explicit_design_spec_contracts(_resolution(), (binding,))
    assert result.contracts == ()
    reasons = result.unresolved[0].reasons
    assert "missing reviewer-authored contract_id" in reasons
    assert "missing reviewer-authored requirement_id" in reasons
    assert "missing reviewer-authored applicability" in reasons
    assert "missing reviewer-authored severity" in reasons
    assert "missing reviewer-authored release_blocking" in reasons
    assert "missing reviewer-authored verification/evidence" in reasons
    assert "nominal quantity needs exactly one reviewer-authored tolerance" in reasons


def test_default_legacy_rail_tolerance_is_never_promoted() -> None:
    assert _explicit_spec().power_rails[0].tolerance_pct == 5.0
    result = adapt_explicit_design_spec_contracts(_resolution(), (_binding(relative_pct=None),))
    assert result.contracts == ()
    assert "nominal quantity needs exactly one reviewer-authored tolerance" in (
        result.unresolved[0].reasons
    )


def test_inferred_design_spec_is_not_an_authoritative_contract_source() -> None:
    inferred = _explicit_spec()
    none = adapt_explicit_design_spec_contracts(
        _resolution(
            source="project_spec",
            explicit=ProjectDesignIntent(),
            inferred=inferred,
            resolved=inferred,
        ),
        (_binding(),),
    )
    assert none.contracts == ()
    assert "source rail not found in explicit design intent" in none.unresolved[0].reasons

    no_source = adapt_explicit_design_spec_contracts(_resolution(source="none"), (_binding(),))
    assert no_source.contracts == ()
    assert "no explicit persisted project design-spec source" in no_source.unresolved[0].reasons


def test_missing_or_duplicate_source_and_binding_ids_are_unresolved() -> None:
    missing = _binding(source_key="+5V", applicability={"kind": "rail", "key": "+5V"})
    ambiguous_intent = _explicit_spec().model_copy(
        update={
            "power_rails": [
                _explicit_spec().power_rails[0],
                _explicit_spec().power_rails[0],
            ]
        }
    )
    a = adapt_explicit_design_spec_contracts(_resolution(), (missing,))
    b = adapt_explicit_design_spec_contracts(_resolution(explicit=ambiguous_intent), (_binding(),))
    duplicate_ids = adapt_explicit_design_spec_contracts(
        _resolution(),
        (_binding(), _binding(source_field="power_rail_current_max", relative_pct=None)),
    )
    assert "source rail not found" in a.unresolved[0].reasons[0]
    assert "source rail name is ambiguous" in b.unresolved[0].reasons
    assert duplicate_ids.contracts == ()
    assert len(duplicate_ids.unresolved) == 2
    assert all("duplicate contract ID" in " ".join(x.reasons) for x in duplicate_ids.unresolved)


def test_missing_interface_quantity_and_ambiguous_interface_kind_unresolved() -> None:
    source = _binding(
        source_field="interface_impedance",
        source_key="usb2",
        applicability={"kind": "interface", "key": "USB"},
        relative_pct="5",
    )
    incomplete = _explicit_spec().model_copy(update={"interfaces": [InterfaceSpec(kind="usb2")]})
    result = adapt_explicit_design_spec_contracts(_resolution(explicit=incomplete), (source,))
    assert result.contracts == ()
    assert "selected interface quantity is unspecified" in result.unresolved[0].reasons
    ambiguous = _explicit_spec().model_copy(
        update={
            "interfaces": [
                InterfaceSpec(kind="usb2", impedance_target_ohm=90),
                InterfaceSpec(kind="usb2", impedance_target_ohm=100),
            ]
        }
    )
    result = adapt_explicit_design_spec_contracts(_resolution(explicit=ambiguous), (source,))
    assert "source interface kind is ambiguous" in result.unresolved[0].reasons[0]


def test_binding_scope_and_wrong_tolerances_fail_closed() -> None:
    wrong_scope = _binding(applicability={"kind": "component", "key": "U3"})
    wrong_key = _binding(applicability={"kind": "rail", "key": "+5V"})
    wrong_type = _binding(absolute_tolerance={"value": "1", "unit": "A"}, relative_pct=None)
    wrong_max = _binding(source_field="power_rail_current_max")
    bad_inputs = (wrong_scope, wrong_key, wrong_type, wrong_max)
    results = [adapt_explicit_design_spec_contracts(_resolution(), (item,)) for item in bad_inputs]
    assert all(result.contracts == () for result in results)
    assert "source requires rail applicability" in results[0].unresolved[0].reasons
    assert "rail applicability key must match" in results[1].unresolved[0].reasons[0]
    assert "contract validation failed" in results[2].unresolved[0].reasons[0]
    assert "maximum-only quantity" in results[3].unresolved[0].reasons[0]


def test_incompatible_waiver_contract_version_remains_unresolved() -> None:
    binding = _binding(
        waivers=[
            {
                "waiver_id": "WAIVER-1",
                "contract_id": "INTENT-3V3",
                "contract_version": 2,
                "reason": "Pending lab test",
                "approved_by": "lead",
                "approval_evidence_ref": "artifact-123",
            }
        ]
    )
    result = adapt_explicit_design_spec_contracts(_resolution(), (binding,))
    assert result.contracts == ()
    assert "waiver must bind" in result.unresolved[0].reasons[0]


def test_authorized_conversion_produces_queryable_graph_links() -> None:
    result = adapt_explicit_design_spec_contracts(_resolution(), (_binding(),))
    assert result.unresolved == ()
    graph = EngineeringGraph(project_key="fixture")
    for kind, key in [
        (GraphEntityKind.REQUIREMENT, "REQ-3V3"),
        (GraphEntityKind.POWER_RAIL, "+3V3"),
    ]:
        graph.add_entity(
            GraphEntity(
                entity_id=canonical_entity_id(graph.project_key, kind, key),
                kind=kind,
                stable_key=key,
            )
        )
    contract_id = link_hardware_intent_contract(
        graph,
        result.contracts[0],
        provenance=GraphProvenance(GraphProvenanceKind.USER_APPROVED, source="fixture-review"),
    )
    rail_id = canonical_entity_id(graph.project_key, GraphEntityKind.POWER_RAIL, "+3V3")
    req_id = canonical_entity_id(graph.project_key, GraphEntityKind.REQUIREMENT, "REQ-3V3")
    assert {contract_id, req_id} <= graph.impacted_by({rail_id})
    assert EngineeringGraph.from_document(graph.to_document()).to_document() == graph.to_document()


@pytest.mark.parametrize(
    ("source_field", "unit"),
    [
        ("power_rail_voltage", "V"),
        ("power_rail_current_max", "A"),
        ("interface_impedance", "ohm"),
        ("interface_skew_max", "ps"),
    ],
)
def test_all_supported_sources_are_typed_and_finite(source_field: str, unit: str) -> None:
    if source_field.startswith("interface_"):
        binding = _binding(
            source_field=source_field,
            source_key="usb2",
            contract_id="INTENT-USB-METRIC",
            requirement_id="REQ-USB-METRIC",
            applicability={"kind": "interface", "key": "USB"},
            relative_pct=None if source_field == "interface_skew_max" else "5",
        )
    else:
        binding = _binding(
            source_field=source_field,
            relative_pct=None if source_field == "power_rail_current_max" else "5",
        )
    result = adapt_explicit_design_spec_contracts(_resolution(), (binding,))
    assert not result.unresolved
    constraint = result.contracts[0].quantity_range or result.contracts[0].nominal_tolerance
    assert constraint is not None
    quantity = constraint.maximum if hasattr(constraint, "maximum") else constraint.nominal
    assert quantity is not None
    assert quantity.unit == unit


def test_unknown_source_field_and_missing_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        _binding(source_field="ambient_temperature")
    with pytest.raises(ValidationError):
        _binding(contract_id="???")


def test_absolute_tolerance_is_reviewer_authored() -> None:
    result = adapt_explicit_design_spec_contracts(
        _resolution(),
        (_binding(relative_pct=None, absolute_tolerance={"value": "100", "unit": "mV"}),),
    )
    assert result.unresolved == ()
    assert result.contracts[0].nominal_tolerance is not None
    assert result.contracts[0].nominal_tolerance.bounds() == (
        "V",
        Decimal("3.200"),
        Decimal("3.400"),
    )


def test_invalid_source_quantity_is_rejected_without_contract() -> None:
    rail = _explicit_spec().power_rails[0].model_copy(update={"voltage_v": float("nan")})
    source = _explicit_spec().model_copy(update={"power_rails": [rail]})
    result = adapt_explicit_design_spec_contracts(_resolution(explicit=source), (_binding(),))
    assert result.contracts == ()
    assert "source quantity is not finite" in result.unresolved[0].reasons


def test_informational_contract_and_legacy_explicit_source() -> None:
    result = adapt_explicit_design_spec_contracts(
        _resolution(source="legacy_design_intent"),
        (
            _binding(
                severity="informational",
                release_blocking=False,
                verification=[],
            ),
        ),
    )
    assert not result.unresolved
    assert result.contracts[0].verification == ()
    assert not result.contracts[0].release_blocking


def test_interface_scope_and_invalid_release_policy_return_unresolved() -> None:
    bad_scope = _binding(
        source_field="interface_impedance",
        source_key="usb2",
        applicability={"kind": "rail", "key": "+3V3"},
    )
    bad_policy = _binding(severity="blocking", release_blocking=False)
    scope_result = adapt_explicit_design_spec_contracts(_resolution(), (bad_scope,))
    policy_result = adapt_explicit_design_spec_contracts(_resolution(), (bad_policy,))
    assert scope_result.contracts == ()
    assert "source requires interface applicability" in scope_result.unresolved[0].reasons
    assert policy_result.contracts == ()
    assert "contract validation failed" in policy_result.unresolved[0].reasons[0]


def test_empty_conversion_batch_has_no_side_effects() -> None:
    result = adapt_explicit_design_spec_contracts(_resolution(), ())
    assert result.contracts == ()
    assert result.unresolved == ()
