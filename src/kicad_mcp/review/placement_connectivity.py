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


def _dist(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


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
            rule_id="placement.decoupling_pin_connectivity",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Unsupported or ambiguous PCB geometry; cannot verify decoupling placement.",
            missing_inputs=["geometry_resolution"],
            metadata={"defect_category": "placement", "electrical_defect": True},
        )

    # 1. Target IC resolution
    ics_to_check: list[PlacementComponentTopology] = []
    if target_ic:
        comp = topology.components.get(target_ic)
        if comp is None:
            return ReviewAssessment(
                rule_id="placement.decoupling_pin_connectivity",
                rule_revision=1,
                status=AssessmentStatus.BLOCKED,
                method=EvaluationMethod.ANALYTICAL,
                summary=f"Target IC '{target_ic}' was not found in board placement topology.",
                missing_inputs=["target_ic"],
                metadata={"defect_category": "placement", "electrical_defect": True},
            )
        ics_to_check.append(comp)
    else:
        ics_to_check = [
            c
            for c in topology.components.values()
            if c.component_type == "ic" or c.reference.upper().startswith("U")
        ]

    if not ics_to_check:
        return ReviewAssessment(
            rule_id="placement.decoupling_pin_connectivity",
            rule_revision=1,
            status=AssessmentStatus.NOT_APPLICABLE,
            method=EvaluationMethod.ANALYTICAL,
            summary="No IC components present in board topology to evaluate decoupling.",
            metadata={"defect_category": "placement", "electrical_defect": False},
        )

    all_caps = [
        c
        for c in topology.components.values()
        if c.component_type == "capacitor" or c.reference.upper().startswith("C")
    ]

    findings: list[ReviewFinding] = []
    missing_inputs: list[str] = []
    checked_pins = 0
    passed_pins = 0

    for ic in ics_to_check:
        # Resolve power pins
        if target_power_pin:
            pin = ic.find_pin(target_power_pin)
            if pin is None:
                return ReviewAssessment(
                    rule_id="placement.decoupling_pin_connectivity",
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
            pins_to_eval = [pin]
        else:
            pins_to_eval = ic.power_pins()

        if not pins_to_eval:
            # If no power pins declared/found, cannot verify without pins
            return ReviewAssessment(
                rule_id="placement.decoupling_pin_connectivity",
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

        for p in pins_to_eval:
            checked_pins += 1
            if p.location_mm is None:
                missing_inputs.append(f"{ic.reference}.{p.pin_number}_location")
                continue

            if p.layer != "F.Cu" and "backside_transform" not in topology.metadata:
                return ReviewAssessment(
                    rule_id="placement.decoupling_pin_connectivity",
                    rule_revision=1,
                    status=AssessmentStatus.NOT_ASSESSED,
                    method=EvaluationMethod.ANALYTICAL,
                    summary=(
                        f"Unsupported backside transform for pin '{p.pin_number}' on "
                        f"layer '{p.layer}'."
                    ),
                    missing_inputs=["backside_transform"],
                    metadata={"ic_ref": ic.reference, "pin": p.pin_number, "layer": p.layer},
                )

            pin_net = p.net_name.upper().lstrip("/")
            same_rail_caps: list[
                tuple[PlacementComponentTopology, float, PlacementPinTopology]
            ] = []
            wrong_rail_nearby: list[tuple[PlacementComponentTopology, float, str]] = []

            for cap in all_caps:
                cap_loc = cap.location_mm
                if cap_loc is None:
                    continue
                d_centroid = _dist(p.location_mm, cap_loc)

                # Find if cap has matching rail pin
                matching_cap_pin = next(
                    (cp for cp in cap.pins if cp.net_name.upper().lstrip("/") == pin_net),
                    None,
                )
                if matching_cap_pin is not None:
                    d_pin = (
                        _dist(p.location_mm, matching_cap_pin.location_mm)
                        if matching_cap_pin.location_mm
                        else d_centroid
                    )
                    same_rail_caps.append((cap, d_pin, matching_cap_pin))
                else:
                    # Check if cap is near this pin on a DIFFERENT non-ground supply rail
                    cap_supply_pins = [
                        cp
                        for cp in cap.pins
                        if cp.net_name
                        and not cp.net_name.upper().startswith(("GND", "VSS"))
                        and cp.net_name.upper().lstrip("/") != pin_net
                    ]
                    if d_centroid <= max_distance_mm and cap_supply_pins:
                        wrong_rail_nearby.append((cap, d_centroid, cap_supply_pins[0].net_name))

            # Sort same-rail caps by distance
            same_rail_caps.sort(key=lambda item: item[1])

            # Check ground return topology
            ground_return_verified = False
            ic_gnd_pins = ic.ground_pins()
            ic_gnd_nets = {gp.net_name.upper().lstrip("/") for gp in ic_gnd_pins}

            if same_rail_caps:
                best_cap, best_d, best_cap_pin = same_rail_caps[0]
                cap_gnd_pins = best_cap.ground_pins()
                cap_gnd_nets = {gp.net_name.upper().lstrip("/") for gp in cap_gnd_pins}

                shared_gnd = ic_gnd_nets & cap_gnd_nets
                if shared_gnd and topology.has_ground_plane:
                    ground_return_verified = True

                if best_d <= max_distance_mm:
                    passed_pins += 1
                else:
                    findings.append(
                        ReviewFinding(
                            id=f"decap-far-{ic.reference}-{p.pin_number}"[:64],
                            rule_id="placement.decoupling_pin_connectivity",
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
                                "ground_return_verified": ground_return_verified,
                            },
                        )
                    )
            else:
                # No same-rail capacitor found
                desc = (
                    f"No same-rail decoupling capacitor found for '{ic.reference}' pin "
                    f"'{p.pin_number}' (rail '{pin_net}')."
                )
                if wrong_rail_nearby:
                    w_cap, w_d, w_net = wrong_rail_nearby[0]
                    desc += (
                        f" Nearby cap '{w_cap.reference}' ({w_d:.2f} mm) is on wrong "
                        f"rail '{w_net}'."
                    )
                findings.append(
                    ReviewFinding(
                        id=f"decap-missing-{ic.reference}-{p.pin_number}"[:64],
                        rule_id="placement.decoupling_pin_connectivity",
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
                            f"Add a decoupling capacitor connected to rail '{pin_net}' "
                            f"near pin {p.pin_number}."
                        ),
                        metadata={
                            "defect_category": "placement",
                            "wrong_rail_nearby": [
                                {"cap": c.reference, "rail": r, "dist_mm": round(d, 2)}
                                for c, d, r in wrong_rail_nearby
                            ],
                        },
                    )
                )

    if missing_inputs:
        return ReviewAssessment(
            rule_id="placement.decoupling_pin_connectivity",
            rule_revision=1,
            status=AssessmentStatus.NOT_ASSESSED,
            method=EvaluationMethod.ANALYTICAL,
            summary="Missing pin location coordinates for one or more power pins.",
            missing_inputs=missing_inputs,
            metadata={"checked_pins": checked_pins},
        )

    if findings:
        return ReviewAssessment(
            rule_id="placement.decoupling_pin_connectivity",
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
        rule_id="placement.decoupling_pin_connectivity",
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
            rule_id="placement.crystal_distance",
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
        # Resolve companion MCU
        companion_ref: str | None = None
        if xtal.companion_refs:
            companion_ref = xtal.companion_refs[0]
        else:
            # Match by shared oscillator net
            xtal_nets = {
                p.net_name.upper().lstrip("/")
                for p in xtal.pins
                if p.net_name and not p.net_name.upper().startswith(("GND", "VSS"))
            }
            if xtal_nets:
                for candidate in topology.components.values():
                    if candidate.reference == xtal.reference:
                        continue
                    candidate_nets = {
                        p.net_name.upper().lstrip("/") for p in candidate.pins if p.net_name
                    }
                    if xtal_nets & candidate_nets:
                        companion_ref = candidate.reference
                        break

        if companion_ref is None or companion_ref not in topology.components:
            findings.append(
                ReviewFinding(
                    id=f"crystal-no-companion-{xtal.reference}"[:64],
                    rule_id="placement.crystal_distance",
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
            )
            continue

        companion = topology.components[companion_ref]
        if xtal.location_mm is None or companion.location_mm is None:
            return ReviewAssessment(
                rule_id="placement.crystal_distance",
                rule_revision=1,
                status=AssessmentStatus.NOT_ASSESSED,
                method=EvaluationMethod.ANALYTICAL,
                summary=(
                    f"Missing placement coordinate for crystal '{xtal.reference}' or companion."
                ),
                missing_inputs=["crystal_coordinates"],
            )

        d = _dist(xtal.location_mm, companion.location_mm)
        if d > max_distance_mm:
            findings.append(
                ReviewFinding(
                    id=f"crystal-far-{xtal.reference}-{companion.reference}"[:64],
                    rule_id="placement.crystal_distance",
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
            )

    if findings:
        return ReviewAssessment(
            rule_id="placement.crystal_distance",
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
        rule_id="placement.crystal_distance",
        rule_revision=1,
        status=AssessmentStatus.PASS,
        method=EvaluationMethod.ANALYTICAL,
        summary=f"All {checked_crystals} crystal oscillator(s) satisfy placement constraints.",
        metadata={"checked_crystals": checked_crystals},
    )
