"""HardwareIntentContract v1 deterministic validation and persistence contracts."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from kicad_mcp.project.hardware_intent_contract import (
    HardwareIntentContract,
    HardwareQuantity,
    NominalTolerance,
    QuantityRange,
    hardware_intent_contract_json_schema,
)


def _contract(**overrides: object) -> HardwareIntentContract:
    fields: dict[str, object] = {
        "schema_version": 1,
        "contract_id": "INTENT-USB-001",
        "contract_version": 1,
        "requirement_id": "REQ-USB-001",
        "applicability": {"kind": "net", "key": "USB_DP"},
        "severity": "blocking",
        "release_blocking": True,
        "verification": [{"method_ref": "drc", "evidence_classes": ["drc"]}],
    }
    fields.update(overrides)
    return HardwareIntentContract.model_validate(fields)


def test_json_schema_version_and_roundtrip_are_stable() -> None:
    contract = _contract(
        nominal_tolerance={"nominal": {"value": "3300", "unit": "mV"}, "relative_pct": "5"}
    )
    encoded = json.dumps(contract.model_dump(mode="json"), sort_keys=True)
    restored = HardwareIntentContract.model_validate_json(encoded)
    assert restored == contract
    assert json.dumps(restored.model_dump(mode="json"), sort_keys=True) == encoded
    schema = hardware_intent_contract_json_schema()
    assert schema["$id"].endswith("hardware-intent-contract-v1.schema.json")
    assert schema["properties"]["schema_version"]["const"] == 1
    required = {
        "contract_id",
        "contract_version",
        "requirement_id",
        "applicability",
        "severity",
        "release_blocking",
    }
    assert required <= set(schema["required"])


def test_equivalent_units_normalize_exactly() -> None:
    millivolts = HardwareQuantity(value=Decimal("3300"), unit="mV")
    assert millivolts.normalized() == ("V", Decimal("3.300"))
    assert HardwareQuantity(value=Decimal("3.3"), unit="V").normalized() == ("V", Decimal("3.3"))
    assert HardwareQuantity(value=Decimal("1.5"), unit="ns").normalized() == (
        "ps",
        Decimal("1500.0"),
    )
    assert HardwareQuantity(value=Decimal("90"), unit="ohm").dimension == "resistance"


def test_range_bounds_compare_across_supported_units() -> None:
    valid = QuantityRange(
        minimum={"value": "3250", "unit": "mV"},
        maximum={"value": "3.4", "unit": "V"},
    )
    assert valid.minimum is not None
    assert valid.minimum.normalized()[1] == Decimal("3.250")
    with pytest.raises(ValidationError, match="dimensions differ"):
        QuantityRange(
            minimum={"value": "1", "unit": "V"},
            maximum={"value": "1", "unit": "A"},
        )
    with pytest.raises(ValidationError, match="minimum must precede"):
        QuantityRange(
            minimum={"value": "1", "unit": "V"},
            maximum={"value": "1000", "unit": "mV"},
            minimum_inclusive=False,
        )
    with pytest.raises(ValidationError, match="needs a minimum"):
        QuantityRange()


def test_tolerances_are_explicit_and_dimensionally_valid() -> None:
    tolerance = NominalTolerance(
        nominal={"value": "3.3", "unit": "V"},
        absolute={"value": "100", "unit": "mV"},
    )
    assert tolerance.bounds() == ("V", Decimal("3.200"), Decimal("3.400"))
    relative = NominalTolerance(nominal={"value": "-3.3", "unit": "V"}, relative_pct="10")
    assert relative.bounds() == ("V", Decimal("-3.63"), Decimal("-2.97"))
    with pytest.raises(ValidationError, match="exactly one"):
        NominalTolerance(nominal={"value": "3.3", "unit": "V"})
    with pytest.raises(ValidationError, match="dimensions differ"):
        NominalTolerance(
            nominal={"value": "3.3", "unit": "V"}, absolute={"value": "1", "unit": "A"}
        )
    with pytest.raises(ValidationError, match=r"in \[0, 100\]"):
        NominalTolerance(nominal={"value": "3.3", "unit": "V"}, relative_pct="101")


def test_incomplete_or_ambiguous_claims_fail_closed() -> None:
    with pytest.raises(ValidationError, match="applicability"):
        _contract(applicability=None)
    with pytest.raises(ValidationError, match="verification"):
        _contract(verification=[])
    with pytest.raises(ValidationError, match="Extra inputs"):
        _contract(unverified_value="90 ohm")
    with pytest.raises(ValidationError, match="informational"):
        _contract(severity="informational", release_blocking=True, verification=[])
    informational = _contract(severity="informational", release_blocking=False, verification=[])
    assert informational.verification == ()
    with pytest.raises(ValidationError):
        _contract(
            nominal_tolerance={"nominal": {"value": "3.3", "unit": "V"}, "relative_pct": "nan"}
        )


def test_waivers_are_exactly_bound_to_contract_revision() -> None:
    waiver = {
        "waiver_id": "WAIVER-17",
        "contract_id": "INTENT-USB-001",
        "contract_version": 1,
        "reason": "Lab evidence pending",
        "approved_by": "reviewer",
        "approval_evidence_ref": "approval-17.json",
    }
    valid = _contract(waivers=[waiver])
    assert valid.waivers[0].contract_version == 1
    with pytest.raises(ValidationError, match="exact contract ID and version"):
        _contract(contract_version=2, waivers=[waiver])
    with pytest.raises(ValidationError, match="duplicate waiver ID"):
        _contract(waivers=[waiver, waiver])


def test_persisted_schema_fixture_has_required_v1_shape() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "src/kicad_mcp/project/schemas/hardware-intent-contract-v1.schema.json"
    )
    fixture = json.loads(path.read_text(encoding="utf-8"))
    schema = hardware_intent_contract_json_schema()
    assert fixture["$id"] == schema["$id"]
    assert fixture["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert fixture["properties"]["schema_version"]["const"] == 1
    assert set(fixture["required"]) == set(schema["required"])
    assert set(fixture["$defs"]) == set(schema["$defs"])


def test_unsupported_units_and_duplicate_evidence_fail_closed() -> None:
    with pytest.raises(ValidationError, match="unit"):
        HardwareQuantity.model_validate({"value": "3.3", "unit": "furlong"})
    with pytest.raises(ValidationError, match="duplicate evidence"):
        _contract(verification=[{"method_ref": "drc", "evidence_classes": ["drc", "drc"]}])
    with pytest.raises(ValidationError, match="blocking severity"):
        _contract(release_blocking=False)
    with pytest.raises(ValidationError, match="either a quantity range"):
        _contract(
            quantity_range={"minimum": {"value": "3", "unit": "V"}},
            nominal_tolerance={"nominal": {"value": "3.3", "unit": "V"}, "relative_pct": "5"},
        )
    with pytest.raises(ValidationError, match="at least 1 character"):
        _contract(applicability={"kind": "net", "key": " "})


def test_negative_tolerance_and_open_ended_range_are_deterministic() -> None:
    one_sided = QuantityRange(maximum={"value": "500", "unit": "mV"})
    assert one_sided.minimum is None
    assert one_sided.maximum is not None
    assert one_sided.maximum.normalized() == ("V", Decimal("0.500"))
    with pytest.raises(ValidationError, match="nonnegative"):
        NominalTolerance(
            nominal={"value": "3.3", "unit": "V"},
            absolute={"value": "-10", "unit": "mV"},
        )
    with pytest.raises(ValidationError, match="minimum must precede"):
        QuantityRange(
            minimum={"value": "3.4", "unit": "V"},
            maximum={"value": "3.3", "unit": "V"},
        )
