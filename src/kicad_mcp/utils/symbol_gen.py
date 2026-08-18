"""KiCad symbol generator from a pin-table specification.

Produces KiCad-format ``.kicad_sym`` library S-expressions for arbitrary ICs
and connectors from a structured pin list.  Each pin specifies its number,
name, electrical type, and preferred placement side (left / right / top / bottom).

Pin electrical types (KiCad identifiers):
    input, output, bidirectional, tri_state, passive, free, unspecified,
    power_in, power_out, open_emitter, open_collector, no_connect
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ..file_formats import GENERATED_SEXPR_DIALECT_VERSION
from .sexpr import _sexpr_string

PinType = Literal[
    "input",
    "output",
    "bidirectional",
    "tri_state",
    "passive",
    "free",
    "unspecified",
    "power_in",
    "power_out",
    "open_emitter",
    "open_collector",
    "no_connect",
]

PinSide = Literal["left", "right", "top", "bottom"]

# KiCad pin direction for each placement side
_SIDE_DIR: dict[PinSide, str] = {
    "left": "right",  # pin extends left → arrow points right into body
    "right": "left",  # pin extends right → arrow points left into body
    "top": "down",
    "bottom": "up",
}

# Grid spacing for symbol pins (50 mil = 1.27 mm in KiCad 6+ units)
_PIN_PITCH = 2.54  # mm (100 mil)
_PIN_LENGTH = 2.54  # mm (100 mil)
_BOX_PAD = 2.54  # mm margin inside body rectangle


@dataclass
class PinSpec:
    """Specification for a single IC pin."""

    number: str | int
    name: str
    pin_type: PinType = "bidirectional"
    side: PinSide = "left"
    unit: int = 1  # for multi-unit symbols


def _escape(s: str) -> str:
    return _sexpr_string(s)


def _pin_sexpr(
    pin: PinSpec,
    x: float,
    y: float,
    direction: str,
    length: float = _PIN_LENGTH,
) -> str:
    """Emit one (pin …) S-expression."""
    return (
        f"\t\t\t(pin {pin.pin_type} line"
        f" (at {x:.4f} {y:.4f} {_dir_to_angle(direction)})"
        f" (length {length:.4f})"
        f" (name {_escape(pin.name)} (effects (font (size 1.27 1.27))))"
        f" (number {_escape(str(pin.number))} (effects (font (size 1.27 1.27)))))"
    )


def _dir_to_angle(direction: str) -> int:
    return {"right": 0, "left": 180, "up": 90, "down": 270}[direction]


def _layout_pins(
    pins: list[PinSpec],
) -> dict[PinSide, list[PinSpec]]:
    """Group and sort pins by side."""
    groups: dict[PinSide, list[PinSpec]] = {"left": [], "right": [], "top": [], "bottom": []}
    for pin in pins:
        groups[pin.side].append(pin)
    return groups


def _side_geometry(
    groups: dict[PinSide, list[PinSpec]],
) -> tuple[float, float]:
    """Calculate body width and height to fit all pins."""
    left_h = max(len(groups["left"]) - 1, 0) * _PIN_PITCH + _BOX_PAD * 2
    right_h = max(len(groups["right"]) - 1, 0) * _PIN_PITCH + _BOX_PAD * 2
    top_w = max(len(groups["top"]) - 1, 0) * _PIN_PITCH + _BOX_PAD * 2
    bot_w = max(len(groups["bottom"]) - 1, 0) * _PIN_PITCH + _BOX_PAD * 2
    body_h = max(left_h, right_h, 2 * _PIN_PITCH)
    body_w = max(top_w, bot_w, 4 * _PIN_PITCH)
    # Round up to nearest grid
    body_h = math.ceil(body_h / _PIN_PITCH) * _PIN_PITCH
    body_w = math.ceil(body_w / _PIN_PITCH) * _PIN_PITCH
    return body_w, body_h


def generate_symbol(
    name: str,
    pins: list[PinSpec],
    reference_prefix: str = "U",
    description: str = "",
    datasheet: str = "",
    footprint_hint: str = "",
    unit_count: int = 1,
) -> str:
    """Generate a KiCad ``.kicad_sym`` library S-expression.

    Args:
        name: Symbol name (used as both library entry name and value).
        pins: List of :class:`PinSpec` objects defining each pin.
        reference_prefix: Reference designator prefix (``"U"``, ``"J"``, etc.).
        description: Symbol description text.
        datasheet: Datasheet URL or path.
        footprint_hint: Default footprint string (e.g. ``"Package_SO:SOIC-8"``)
        unit_count: Number of sub-units. Pins with ``unit > 1`` are placed in
            subsequent units; pins with ``unit <= 0`` appear in all units.

    Returns:
        Complete ``.kicad_sym`` S-expression as a string.
    """
    # Group pins per unit
    units: dict[int, list[PinSpec]] = {}
    for pin in pins:
        u = pin.unit if pin.unit >= 1 else 1
        units.setdefault(u, []).append(pin)

    if not units:
        units[1] = []

    lines: list[str] = [
        "(kicad_symbol_lib",
        f"\t(version {GENERATED_SEXPR_DIALECT_VERSION})",
        '\t(generator "kicad-mcp-symbol-gen")',
        f"\t(symbol {_escape(name)}",
        "\t\t(pin_names (offset 1.016))",
        "\t\t(exclude_from_sim no)",
        "\t\t(in_bom yes)",
        "\t\t(on_board yes)",
        # Properties
        f'\t\t(property "Reference" {_escape(reference_prefix)}',
        "\t\t\t(at 0 0 0)",
        "\t\t\t(effects (font (size 1.27 1.27)))",
        "\t\t)",
        f'\t\t(property "Value" {_escape(name)}',
        "\t\t\t(at 0 -2.54 0)",
        "\t\t\t(effects (font (size 1.27 1.27)))",
        "\t\t)",
        f'\t\t(property "Footprint" {_escape(footprint_hint)}',
        "\t\t\t(at 0 -5.08 0)",
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))",
        "\t\t)",
        f'\t\t(property "Datasheet" {_escape(datasheet)}',
        "\t\t\t(at 0 -7.62 0)",
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))",
        "\t\t)",
        f'\t\t(property "Description" {_escape(description)}',
        "\t\t\t(at 0 -10.16 0)",
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))",
        "\t\t)",
    ]

    for unit_idx in sorted(units):
        unit_pins = units[unit_idx]
        groups = _layout_pins(unit_pins)
        body_w, body_h = _side_geometry(groups)
        half_w = body_w / 2
        half_h = body_h / 2
        # Emit unit graphics (body rectangle + pin-1 dot + pins)
        lines.append(f"\t\t(symbol {_escape(name + f'_{unit_idx}_1')}")
        lines.append(
            f"\t\t\t(rectangle (start {-half_w:.4f} {half_h:.4f}) (end {half_w:.4f} {-half_h:.4f})"
            f" (stroke (width 0)(type default)) (fill (type background)))"
        )

        # Left side pins — descend from top
        for idx, pin in enumerate(groups["left"]):
            y = half_h - _BOX_PAD - idx * _PIN_PITCH
            x = -half_w - _PIN_LENGTH
            lines.append(_pin_sexpr(pin, x, y, _SIDE_DIR["left"]))

        # Right side pins — descend from top
        for idx, pin in enumerate(groups["right"]):
            y = half_h - _BOX_PAD - idx * _PIN_PITCH
            x = half_w + _PIN_LENGTH
            lines.append(_pin_sexpr(pin, x, y, _SIDE_DIR["right"]))

        # Top side pins — left to right
        for idx, pin in enumerate(groups["top"]):
            x = -((len(groups["top"]) - 1) * _PIN_PITCH / 2) + idx * _PIN_PITCH
            y = half_h + _PIN_LENGTH
            lines.append(_pin_sexpr(pin, x, y, _SIDE_DIR["top"]))

        # Bottom side pins — left to right
        for idx, pin in enumerate(groups["bottom"]):
            x = -((len(groups["bottom"]) - 1) * _PIN_PITCH / 2) + idx * _PIN_PITCH
            y = -half_h - _PIN_LENGTH
            lines.append(_pin_sexpr(pin, x, y, _SIDE_DIR["bottom"]))

        lines.append("\t\t)")

    lines.append("\t)")  # close symbol
    lines.append(")")  # close kicad_symbol_lib
    return "\n".join(lines)
