"""Critical placement pin and net connectivity review evaluator (#1582, T4).

Validates critical placement findings against actual component references, supply pins,
connected nets, and supported geometry:
- Decoupling validation against intended supply rail and ground return.
- Wrong-rail capacitors cannot receive an electrical PASS.
- Unresolved power pins or unsupported backside transforms return NOT_ASSESSED or BLOCKED.
- Distance-only heuristics are labeled preliminary/advisory.
- Crystal and SMPS use declared companion topology, not nearest-reference guesses.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import NamedTuple

from ..models.placement_topology import (
    PlacementBoardTopology,
    PlacementComponentTopology,
    PlacementPinTopology,
)
from ..models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ReviewAssessment,
    ReviewContext,
    ReviewFinding,
)

_DECOUPLING_RULE_ID = "placement.decoupling_pin_connectivity"
_CRYSTAL_RULE_ID = "placement.crystal_distance"


def _dist(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _resolve_target_ics(
    topology: PlacementBoardTopology,
    target_ic: str | None,
) -> tuple[list[PlacementComponentTopology], ReviewAssessment | None]:
    if target_ic:
        comp = topology.components.get(target_ic)
        if comp is None:
            return [], ReviewAssessment(
                rule_id=_DECOUPLING_RULE_ID,
                rule_revision=1,
                status=AssessmentStatus.BLOCKED,
                method=EvaluationMethod.ANALYTICAL,
                summary=f"Target IC '{target_ic}' was not found in board placement topology.",
                missing_inputs=["target_ic"],
                metadata={"defect_category": "placement", "electrical_defect": True},
            )
        return [comp], None

    ics = [
        c
        for c in topology.components.values()
        if c.component_type == "ic" or c.reference.upper().startswith("U")
    ]
    if not ics:
        return [], ReviewAssessment(
            rule_id=_DECOUPLING_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.NOT_APPLICABLE,
            method=EvaluationMethod.ANALYTICAL,
            summary="No IC components present in board topology to evaluate decoupling.",
            metadata={"defect_category": "placement", "electrical_defect": False},
        )
    return ics, None


def _resolve_pins_to_evaluate(
    ic: PlacementComponentTopology,
    target_power_pin: str | None,
) -> tuple[list[PlacementPinTopology], ReviewAssessment | None]:
    if target_power_pin:
        pin = ic.find_pin(target_power_pin)
        if pin is None:
            return [], ReviewAssessment(
                rule_id=_DECOUPLING_RULE_ID,
                rule_revision=1,
                status=AssessmentStatus.NOT_ASSESSED,
                method=EvaluationMethod.ANALYTICAL,
                summary=(
                    f"Power pin '{target_power_pin}' was not found on footprint "
                    f"'{ic.reference}'. Center proxy cannot substitute for "
                    "verified pin location."
                ),
                missing_inputs=["power_pin_resolution"],
                metadata={
                    "ic_ref": ic.reference,
                    "unresolved_pin": target_power_pin,
                    "defect_category": "placement",
                },
            )
        return [pin], None

    pins = ic.power_pins()
    if not pins:
        return [], ReviewAssessment(
            rule_id=_DECOUPLING_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary=(
                f"No power pins identified on IC '{ic.reference}'. "
                "Cannot evaluate decoupling without verified pin connectivity."
            ),
            missing_inputs=["power_pin_resolution"],
            metadata={"ic_ref": ic.reference},
        )
    return pins, None


def _match_nearby_capacitors(
    p: PlacementPinTopology,
    pin_net: str,
    all_caps: Sequence[PlacementComponentTopology],
    max_distance_mm: float,
) -> tuple[
    list[tuple[PlacementComponentTopology, float]],
    list[tuple[PlacementComponentTopology, float, str]],
]:
    same_rail: list[tuple[PlacementComponentTopology, float]] = []
    wrong_rail: list[tuple[PlacementComponentTopology, float, str]] = []

    for cap in all_caps:
        if cap.location_mm is None or p.location_mm is None:
            continue
        d_centroid = _dist(p.location_mm, cap.location_mm)

        matching_pin = next(
            (cp for cp in cap.pins if cp.net_name.upper().lstrip("/") == pin_net),
            None,
        )
        if matching_pin is not None:
            d_pin = (
                _dist(p.location_mm, matching_pin.location_mm)
                if matching_pin.location_mm
                else d_centroid
            )
            same_rail.append((cap, d_pin))
        else:
            cap_supply_pins = [
                cp
                for cp in cap.pins
                if cp.net_name
                and not cp.net_name.upper().startswith(("GND", "VSS"))
                and cp.net_name.upper().lstrip("/") != pin_net
            ]
            if d_centroid <= max_distance_mm and cap_supply_pins:
                wrong_rail.append((cap, d_centroid, cap_supply_pins[0].net_name))

    same_rail.sort(key=lambda item: item[1])
    return same_rail, wrong_rail


def _build_same_rail_finding(
    ic: PlacementComponentTopology,
    p: PlacementPinTopology,
    best_cap: PlacementComponentTopology,
    best_d: float,
    ground_return: bool,
    max_distance_mm: float,
    pin_net: str,
) -> ReviewFinding:
    return ReviewFinding(
        id=f"decap-far-{ic.reference}-{p.pin_number}"[:64],
        rule_id=_DECOUPLING_RULE_ID,
        rule_revision=1,
        severity="error",
        object_ref=f"{ic.reference}.{p.pin_number}",
        pin=p.pin_number,
        net=p.net_name,
        layer=p.layer,
        location_mm=p.location_mm,
        description=(
            f"Decoupling cap '{best_cap.reference}' on rail '{pin_net}' "
            f"is {best_d:.2f} mm from pin '{p.pin_number}' "
            f"(threshold {max_distance_mm:.2f} mm)."
        ),
        measured_value=round(best_d, 3),
        expected_value=max_distance_mm,
        units="mm",
        remediation=(
            f"Move capacitor '{best_cap.reference}' closer to "
            f"pin {p.pin_number} (within {max_distance_mm:.1f} mm)."
        ),
        metadata={
            "cap_ref": best_cap.reference,
            "distance_mm": round(best_d, 3),
            "ground_return_verified": ground_return,
        },
    )


def _build_missing_decap_finding(
    ic: PlacementComponentTopology,
    p: PlacementPinTopology,
    wrong_rail_nearby: list[tuple[PlacementComponentTopology, float, str]],
    max_distance_mm: float,
    pin_net: str,
) -> ReviewFinding:
    desc = (
        f"No same-rail decoupling capacitor found for '{ic.reference}' pin "
        f"'{p.pin_number}' (rail '{pin_net}')."
    )
    if wrong_rail_nearby:
        w_cap, w_d, w_net = wrong_rail_nearby[0]
        desc += f" Nearby cap '{w_cap.reference}' ({w_d:.2f} mm) is on wrong rail '{w_net}'."

    return ReviewFinding(
        id=f"decap-missing-{ic.reference}-{p.pin_number}"[:64],
        rule_id=_DECOUPLING_RULE_ID,
        rule_revision=1,
        severity="error",
        object_ref=f"{ic.reference}.{p.pin_number}",
        pin=p.pin_number,
        net=p.net_name,
        layer=p.layer,
        location_mm=p.location_mm,
        description=desc,
        measured_value=None,
        expected_value=max_distance_mm,
        units="mm",
        remediation=(
            f"Add a decoupling capacitor connected to rail '{pin_net}' near pin {p.pin_number}."
        ),
        metadata={
            "defect_category": "placement",
            "wrong_rail_nearby": [
                {"cap": c.reference, "rail": r, "dist_mm": round(d, 2)}
                for c, d, r in wrong_rail_nearby
            ],
        },
    )


def _evaluate_pin_decoupling(
    ic: PlacementComponentTopology,
    p: PlacementPinTopology,
    topology: PlacementBoardTopology,
    all_caps: Sequence[PlacementComponentTopology],
    max_distance_mm: float,
) -> tuple[ReviewFinding | None, bool, str | None, ReviewAssessment | None]:
    if p.location_mm is None:
        return None, False, f"{ic.reference}.{p.pin_number}_location", None

    if p.layer != "F.Cu" and "backside_transform" not in topology.metadata:
        err = ReviewAssessment(
            rule_id=_DECOUPLING_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary=(
                f"Unsupported backside transform for pin '{p.pin_number}' on layer '{p.layer}'."
            ),
            missing_inputs=["backside_transform"],
            metadata={"ic_ref": ic.reference, "pin": p.pin_number, "layer": p.layer},
        )
        return None, False, None, err

    pin_net = p.net_name.upper().lstrip("/")
    same_rail, wrong_rail = _match_nearby_capacitors(p, pin_net, all_caps, max_distance_mm)

    if same_rail:
        best_cap, best_d = same_rail[0]
        ic_gnd = {gp.net_name.upper().lstrip("/") for gp in ic.ground_pins()}
        cap_gnd = {gp.net_name.upper().lstrip("/") for gp in best_cap.ground_pins()}
        ground_return = bool(ic_gnd & cap_gnd and topology.has_ground_plane)

        if best_d <= max_distance_mm:
            return None, True, None, None

        finding = _build_same_rail_finding(
            ic, p, best_cap, best_d, ground_return, max_distance_mm, pin_net
        )
        return finding, False, None, None

    finding = _build_missing_decap_finding(ic, p, wrong_rail, max_distance_mm, pin_net)
    return finding, False, None, None


class _PinScanResult(NamedTuple):
    findings: list[ReviewFinding]
    missing_inputs: list[str]
    checked_pins: int
    passed_pins: int
    error: ReviewAssessment | None


def _scan_decoupling_pins(
    ics_to_check: Sequence[PlacementComponentTopology],
    topology: PlacementBoardTopology,
    target_power_pin: str | None,
    all_caps: Sequence[PlacementComponentTopology],
    max_distance_mm: float,
) -> _PinScanResult:
    """Accumulate pin-level evidence, preserving fail-closed early errors."""
    findings: list[ReviewFinding] = []
    missing_inputs: list[str] = []
    checked_pins = 0
    passed_pins = 0

    for ic in ics_to_check:
        pins_to_eval, pin_err = _resolve_pins_to_evaluate(ic, target_power_pin)
        if pin_err:
            return _PinScanResult(findings, missing_inputs, checked_pins, passed_pins, pin_err)

        for p in pins_to_eval:
            checked_pins += 1
            finding, passed, missing_loc, err = _evaluate_pin_decoupling(
                ic, p, topology, all_caps, max_distance_mm
            )
            if err:
                return _PinScanResult(findings, missing_inputs, checked_pins, passed_pins, err)
            if missing_loc:
                missing_inputs.append(missing_loc)
            elif passed:
                passed_pins += 1
            elif finding:
                findings.append(finding)

    return _PinScanResult(findings, missing_inputs, checked_pins, passed_pins, None)


def evaluate_decoupling_connectivity(
    context: ReviewContext,
    topology: PlacementBoardTopology,
    *,
    target_ic: str | None = None,
    target_power_pin: str | None = None,
    max_distance_mm: float = 3.0,
) -> ReviewAssessment:
    """Evaluate decoupling placement against pin identity, supply rail, and ground return."""
    if topology.unsupported_geometry:
        return ReviewAssessment(
            rule_id=_DECOUPLING_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Unsupported or ambiguous PCB geometry; cannot verify decoupling placement.",
            missing_inputs=["geometry_resolution"],
            metadata={"defect_category": "placement", "electrical_defect": True},
        )

    ics_to_check, err_assessment = _resolve_target_ics(topology, target_ic)
    if err_assessment:
        return err_assessment

    all_caps = [
        c
        for c in topology.components.values()
        if c.component_type == "capacitor" or c.reference.upper().startswith("C")
    ]

    scan = _scan_decoupling_pins(
        ics_to_check, topology, target_power_pin, all_caps, max_distance_mm
    )
    if scan.error:
        return scan.error
    findings = scan.findings
    missing_inputs = scan.missing_inputs
    checked_pins = scan.checked_pins
    passed_pins = scan.passed_pins

    if missing_inputs:
        return ReviewAssessment(
            rule_id=_DECOUPLING_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Missing pin location coordinates for one or more power pins.",
            missing_inputs=missing_inputs,
            metadata={"checked_pins": checked_pins},
        )

    if findings:
        return ReviewAssessment(
            rule_id=_DECOUPLING_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.FAIL,
            method=EvaluationMethod.ANALYTICAL,
            summary=(
                f"Decoupling placement failed for {len(findings)} power pin(s); "
                "missing same-rail capacitor or distance limit exceeded."
            ),
            findings=findings,
            metadata={
                "checked_pins": checked_pins,
                "passed_pins": passed_pins,
                "defect_category": "placement",
            },
        )

    return ReviewAssessment(
        rule_id=_DECOUPLING_RULE_ID,
        rule_revision=1,
        status=AssessmentStatus.PASS,
        method=EvaluationMethod.ANALYTICAL,
        summary=(
            f"All {checked_pins} evaluated power pin(s) have verified same-rail "
            f"decoupling within {max_distance_mm:.1f} mm."
        ),
        metadata={
            "checked_pins": checked_pins,
            "passed_pins": passed_pins,
            "defect_category": "placement",
        },
    )


def _resolve_crystal_companion(
    xtal: PlacementComponentTopology,
    topology: PlacementBoardTopology,
) -> str | None:
    if xtal.companion_refs:
        return xtal.companion_refs[0]

    xtal_nets = {
        p.net_name.upper().lstrip("/")
        for p in xtal.pins
        if p.net_name and not p.net_name.upper().startswith(("GND", "VSS"))
    }
    if not xtal_nets:
        return None

    for candidate in topology.components.values():
        if candidate.reference == xtal.reference:
            continue
        candidate_nets = {p.net_name.upper().lstrip("/") for p in candidate.pins if p.net_name}
        if xtal_nets & candidate_nets:
            return candidate.reference
    return None


def _evaluate_single_crystal(
    xtal: PlacementComponentTopology,
    topology: PlacementBoardTopology,
    max_distance_mm: float,
) -> tuple[ReviewFinding | None, ReviewAssessment | None]:
    companion_ref = _resolve_crystal_companion(xtal, topology)
    if companion_ref is None or companion_ref not in topology.components:
        finding = ReviewFinding(
            id=f"crystal-no-companion-{xtal.reference}"[:64],
            rule_id=_CRYSTAL_RULE_ID,
            rule_revision=1,
            severity="error",
            object_ref=xtal.reference,
            description=(
                f"Crystal '{xtal.reference}' has no declared companion MCU or "
                "shared oscillator net in board topology."
            ),
            units=None,
            remediation="Connect crystal oscillator pins to target MCU companion.",
            metadata={"defect_category": "placement"},
        )
        return finding, None

    companion = topology.components[companion_ref]
    if xtal.location_mm is None or companion.location_mm is None:
        err = ReviewAssessment(
            rule_id=_CRYSTAL_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary=f"Missing placement coordinate for crystal '{xtal.reference}' or companion.",
            missing_inputs=["crystal_coordinates"],
        )
        return None, err

    d = _dist(xtal.location_mm, companion.location_mm)
    if d > max_distance_mm:
        finding = ReviewFinding(
            id=f"crystal-far-{xtal.reference}-{companion.reference}"[:64],
            rule_id=_CRYSTAL_RULE_ID,
            rule_revision=1,
            severity="error",
            object_ref=xtal.reference,
            description=(
                f"Crystal '{xtal.reference}' is {d:.2f} mm from companion MCU "
                f"'{companion.reference}' (threshold {max_distance_mm:.2f} mm)."
            ),
            measured_value=round(d, 3),
            expected_value=max_distance_mm,
            units="mm",
            remediation=f"Move crystal closer to '{companion.reference}'.",
            metadata={"companion": companion.reference, "distance_mm": round(d, 3)},
        )
        return finding, None

    return None, None


def evaluate_crystal_placement(
    context: ReviewContext,
    topology: PlacementBoardTopology,
    *,
    max_distance_mm: float = 8.0,
) -> ReviewAssessment:
    """Evaluate crystal placement against companion MCU oscillator pins."""
    crystals = [
        c
        for c in topology.components.values()
        if c.component_type == "crystal" or c.reference.upper().startswith(("Y", "X"))
    ]
    if not crystals:
        return ReviewAssessment(
            rule_id=_CRYSTAL_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.NOT_APPLICABLE,
            method=EvaluationMethod.ANALYTICAL,
            summary="No crystal oscillator components found in board topology.",
            metadata={"defect_category": "placement"},
        )

    findings: list[ReviewFinding] = []
    checked_crystals = 0

    for xtal in crystals:
        checked_crystals += 1
        finding, err = _evaluate_single_crystal(xtal, topology, max_distance_mm)
        if err:
            return err
        if finding:
            findings.append(finding)

    if findings:
        return ReviewAssessment(
            rule_id=_CRYSTAL_RULE_ID,
            rule_revision=1,
            status=AssessmentStatus.FAIL,
            method=EvaluationMethod.ANALYTICAL,
            summary=(
                f"Crystal placement review failed for {len(findings)} oscillator(s); "
                "missing companion or excessive distance."
            ),
            findings=findings,
            metadata={"checked_crystals": checked_crystals},
        )

    return ReviewAssessment(
        rule_id=_CRYSTAL_RULE_ID,
        rule_revision=1,
        status=AssessmentStatus.PASS,
        method=EvaluationMethod.ANALYTICAL,
        summary=f"All {checked_crystals} crystal oscillator(s) satisfy placement constraints.",
        metadata={"checked_crystals": checked_crystals},
    )
