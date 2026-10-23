"""Deterministic rectangular-board connector-mating reviewer.

No KiCad runtime and no mutations. Passing this bounded check proves only
2-D specified mating-datum alignment, NOT plug volume, 3-D mating, EMC or DFM.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from ..models.intent import ConnectorMatingSpec

_NORMALS: dict[str, tuple[float, float]] = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "top": (0.0, -1.0),
    "bottom": (0.0, 1.0),
}


def _rotated(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """KiCad footprint local-to-board rotation (+degrees counterclockwise)."""
    a = math.radians(angle_deg)
    return x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a)


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _mating_datum_tolerance_problems(
    spec: ConnectorMatingSpec, tag: str, distance: float
) -> list[str]:
    """Conservative 2-D declared tolerance budget, never 3-D approval."""
    problems: list[str] = []
    component_tolerance = spec.datum_component_tolerance_mm
    profile_tolerance = spec.board_edge_tolerance_mm
    if component_tolerance is not None or profile_tolerance is not None:
        if component_tolerance is None or profile_tolerance is None:
            problems.append(
                f"{tag}: incomplete mating tolerance budget; declare both "
                "component and board-edge uncertainties."
            )
        else:
            # Triangle inequality: bounded 2-D datum-to-edge error can grow by
            # at most the sum of the declared scalar position uncertainties.
            # This is intentionally not 3-D connector/enclosure verification.
            worst_case_mm = distance + component_tolerance + profile_tolerance
            if worst_case_mm > spec.max_datum_error_mm + 1e-7:
                problems.append(
                    f"{tag}: worst-case mating datum offset {worst_case_mm:.3f} mm "
                    f"exceeds {spec.max_datum_error_mm:.3f} mm limit "
                    f"(nominal {distance:.3f} + component {component_tolerance:.3f} "
                    f"+ board-edge {profile_tolerance:.3f} mm)."
                )
    return problems


def evaluate_connector_mating(
    spec: ConnectorMatingSpec,
    entry: Mapping[str, object] | None,
    frame: tuple[float, float, float, float],
    *,
    rectangular_outline_verified: bool,
) -> list[str]:
    """Return hard failures; never return an unproven alignment as passing."""
    tag = f"Connector '{spec.ref}'"
    if not rectangular_outline_verified:
        return [f"{tag}: a single rectangular Edge.Cuts outline is required for this v1 2-D check."]
    if entry is None:
        return [f"{tag}: mating-intent footprint is missing from the PCB."]
    if entry.get("name") != spec.footprint_id:
        return [f"{tag}: footprint mismatch: expected {spec.footprint_id!r}."]
    if entry.get("layer_name") != "F.Cu" or entry.get("layer_name_explicit") is not True:
        return [
            f"{tag}: explicit front-copper footprint layer is required; "
            "missing, back-side or mirrored layers are not approved."
        ]
    px = _finite_float(entry.get("x_mm"))
    py = _finite_float(entry.get("y_mm"))
    rotation = _finite_float(entry.get("rotation"))
    if px is None or py is None or rotation is None:
        return [f"{tag}: position or rotation is unavailable/invalid."]
    x_off, y_off = _rotated(spec.datum_x_mm, spec.datum_y_mm, float(rotation))
    x_mm, y_mm = px + x_off, py + y_off
    normal_local = _NORMALS[spec.normal_local]
    nx, ny = _rotated(*normal_local, float(rotation))
    desired_x, desired_y = _NORMALS[spec.edge]
    dot = max(-1.0, min(1.0, nx * desired_x + ny * desired_y))
    angle_error = math.degrees(math.acos(dot))
    x0, y0, x1, y1 = frame
    edge_position = {"left": x0, "right": x1, "top": y0, "bottom": y1}[spec.edge]
    datum_coord = y_mm if spec.edge in {"top", "bottom"} else x_mm
    tangential = x_mm if spec.edge in {"top", "bottom"} else y_mm
    lower, upper = (x0, x1) if spec.edge in {"top", "bottom"} else (y0, y1)
    problems: list[str] = []
    if angle_error > spec.max_direction_error_deg + 1e-7:
        problems.append(
            f"{tag}: mating direction points {angle_error:.1f} degrees away from "
            f"{spec.edge} outward normal (limit {spec.max_direction_error_deg:.1f})."
        )
    # The nearest point belongs to the *finite* side of Edge.Cuts, not
    # the infinite supporting line. At corners both offsets contribute.
    edge_extension_mm = max(lower - tangential, 0.0, tangential - upper)
    distance = math.hypot(datum_coord - edge_position, edge_extension_mm)
    if distance > spec.max_datum_error_mm + 1e-7:
        problems.append(
            f"{tag}: mating datum is {distance:.3f} mm from {spec.edge} Edge.Cuts "
            f"(limit {spec.max_datum_error_mm:.3f} mm)."
        )
    if not lower - spec.max_datum_error_mm <= tangential <= upper + spec.max_datum_error_mm:
        problems.append(f"{tag}: mating datum lies outside the specified edge segment.")
    problems.extend(_mating_datum_tolerance_problems(spec, tag, distance))
    return problems
