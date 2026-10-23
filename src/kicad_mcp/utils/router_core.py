"""Headless Specctra SES -> .kicad_pcb track/via applier (work order P4-T1).

KiCad has no headless ``pcb import specctra`` command, so a routed Specctra session
(``.ses`` produced by FreeRouting) normally has to be applied through the GUI
(``File > Import > Specctra Session``). This module closes that hole: it parses the SES
session and writes the routed segments and vias straight into the ``.kicad_pcb`` using the
round-trip-safe S-expression layer, so a board can be routed end to end without a GUI step.

Coordinate convention: KiCad's Specctra exporter writes DSN/SES coordinates scaled by the
``(resolution ...)`` declaration with the Y axis negated and no offset (Specctra is Y-up,
KiCad is Y-down). This module inverts exactly that transform. It is pure and KiCad-free, so
it is fully unit-testable; the live ``route_apply_ses`` tool feeds it the staged SES.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .sexpr import _extract_block

# Deterministic UUID namespace so a given board+route always yields the same file bytes.
_UUID_NAMESPACE = uuid.UUID("6b6f1f0e-9d2a-5c41-b7e3-2a1f4c8d9e00")
_RESOLUTION_RE = re.compile(r"\(resolution\s+(\w+)\s+([0-9.]+)\)")
# Via padstack names from KiCad's DSN export encode size:drill, e.g. Via[0-1]_600:300_um.
_VIA_PADSTACK_RE = re.compile(r"_(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)_(um|mm|mil)\b")

# Default via geometry (mm) used only when the padstack name does not encode size/drill.
_DEFAULT_VIA_SIZE_MM = 0.6
_DEFAULT_VIA_DRILL_MM = 0.3


@dataclass(frozen=True)
class SesSegment:
    """A single routed track segment in KiCad board millimetres (Y already un-flipped)."""

    net_name: str
    layer: str
    width_mm: float
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass(frozen=True)
class SesVia:
    """A routed via in KiCad board millimetres."""

    net_name: str
    at: tuple[float, float]
    size_mm: float
    drill_mm: float
    layers: tuple[str, str] = ("F.Cu", "B.Cu")


@dataclass
class SesRoute:
    """The routed geometry parsed from a Specctra session."""

    segments: list[SesSegment] = field(default_factory=list)
    vias: list[SesVia] = field(default_factory=list)
    units_per_mm: float = 10000.0

    @property
    def net_names(self) -> set[str]:
        return {s.net_name for s in self.segments} | {v.net_name for v in self.vias}


def _units_per_mm(unit: str, factor: float) -> float:
    """Resolution units per millimetre for a Specctra ``(resolution unit factor)``.

    KiCad's Specctra export writes coordinates in the base ``unit`` itself (verified: with
    ``(resolution um 10)`` a part at 2.5 mm exports as ``2500`` -> micrometres, 1 mm = 1000
    units). The ``factor`` is KiCad's resolution-grid declaration, not a coordinate
    multiplier, so it is not applied to the magnitude. FreeRouting echoes the same
    convention in the .ses it returns.
    """
    _ = factor
    per_unit = {"um": 1000.0, "mm": 1.0, "inch": 1.0 / 25.4, "mil": 1000.0 / 25.4}
    return per_unit.get(unit.lower(), 1000.0)


def _to_mm(value: float, units_per_mm: float, *, flip: bool = False) -> float:
    mm = value / units_per_mm
    return round(-mm if flip else mm, 6)


def _strip_quotes(token: str) -> str:
    return token[1:-1] if len(token) >= 2 and token[0] == '"' and token[-1] == '"' else token


def _parse_via_geometry(padstack: str) -> tuple[float, float]:
    match = _VIA_PADSTACK_RE.search(padstack)
    if match is None:
        return _DEFAULT_VIA_SIZE_MM, _DEFAULT_VIA_DRILL_MM
    size, drill, unit = float(match.group(1)), float(match.group(2)), match.group(3)
    upm = _units_per_mm(unit, 1.0) if unit != "mm" else 1.0
    if unit == "mm":
        return round(size, 6), round(drill, 6)
    return round(size / upm, 6), round(drill / upm, 6)


def parse_ses(text: str) -> SesRoute:
    """Parse a Specctra ``.ses`` session into KiCad-millimetre segments and vias."""
    resolution = _RESOLUTION_RE.search(text)
    units_per_mm = (
        _units_per_mm(resolution.group(1), float(resolution.group(2))) if resolution else 10000.0
    )
    route = SesRoute(units_per_mm=units_per_mm)

    network_start = text.find("(network_out")
    body = text if network_start == -1 else text[network_start:]

    search = 0
    while True:
        net_start = body.find("(net ", search)
        if net_start == -1:
            break
        net_block, consumed = _extract_block(body, net_start)
        search = net_start + max(consumed, 1)
        name_match = re.match(r'\(net\s+("[^"]*"|\S+)', net_block)
        if name_match is None:
            continue
        net_name = _strip_quotes(name_match.group(1))
        _parse_net_wires(net_block, net_name, route)
        _parse_net_vias(net_block, net_name, route)
    return route


def _parse_net_wires(net_block: str, net_name: str, route: SesRoute) -> None:
    for path in re.finditer(r"\(path\s++(\S+)\s++([0-9.]+)\s++([0-9.\s-]+?)\)", net_block):
        layer = _strip_quotes(path.group(1))
        width_mm = round(float(path.group(2)) / route.units_per_mm, 6)
        coords = [float(value) for value in path.group(3).split()]
        points = [
            (
                _to_mm(coords[i], route.units_per_mm),
                _to_mm(coords[i + 1], route.units_per_mm, flip=True),
            )
            for i in range(0, len(coords) - 1, 2)
        ]
        for start, end in zip(points, points[1:], strict=False):
            if start == end:
                continue
            route.segments.append(
                SesSegment(
                    net_name=net_name,
                    layer=layer,
                    width_mm=width_mm,
                    start=start,
                    end=end,
                )
            )


def _parse_net_vias(net_block: str, net_name: str, route: SesRoute) -> None:
    for via in re.finditer(r'\(via\s+("[^"]*"|\S+)\s+(-?[0-9.]+)\s+(-?[0-9.]+)', net_block):
        padstack = _strip_quotes(via.group(1))
        size_mm, drill_mm = _parse_via_geometry(padstack)
        route.vias.append(
            SesVia(
                net_name=net_name,
                at=(
                    _to_mm(float(via.group(2)), route.units_per_mm),
                    _to_mm(float(via.group(3)), route.units_per_mm, flip=True),
                ),
                size_mm=size_mm,
                drill_mm=drill_mm,
            )
        )


def parse_net_numbers(pcb_text: str) -> dict[str, int]:
    """Map net names to their numbers from a ``.kicad_pcb`` ``(net N "name")`` table."""
    numbers: dict[str, int] = {}
    for match in re.finditer(r'\(net\s+(\d+)\s+"([^"]*)"\)', pcb_text):
        numbers[match.group(2)] = int(match.group(1))
    return numbers


def _fmt(value: float) -> str:
    """Format a coordinate the way KiCad does: minimal decimal, no trailing zeros."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _det_uuid(*parts: object) -> str:
    return str(uuid.uuid5(_UUID_NAMESPACE, "|".join(str(part) for part in parts)))


def render_pcb_items(route: SesRoute, net_numbers: dict[str, int], *, indent: str = "\t") -> str:
    """Render the routed segments and vias as deterministic KiCad ``.kicad_pcb`` S-expr."""
    # An SES session is a whole routed result. Silently skipping unknown
    # networks commits a partial board while reporting success to the agent.
    # Reject before rendering *any* track or via, including net-zero/no-net.
    unresolved = sorted(
        name for name in route.net_names if not name or net_numbers.get(name, 0) <= 0
    )
    if unresolved:
        raise ValueError(
            f"SES routing refused: net(s) missing from the PCB net table: "
            f"{', '.join(repr(name) for name in unresolved)}. "
            "No routing was applied."
        )

    lines: list[str] = []
    segments = sorted(
        route.segments,
        key=lambda s: (net_numbers.get(s.net_name, -1), s.layer, s.start, s.end, s.width_mm),
    )
    for seg in segments:
        net = net_numbers[seg.net_name]
        uid = _det_uuid("seg", seg.net_name, seg.layer, seg.start, seg.end, seg.width_mm)
        lines.append(
            f"{indent}(segment (start {_fmt(seg.start[0])} {_fmt(seg.start[1])}) "
            f"(end {_fmt(seg.end[0])} {_fmt(seg.end[1])}) (width {_fmt(seg.width_mm)}) "
            f'(layer "{seg.layer}") (net {net}) (uuid "{uid}"))'
        )
    vias = sorted(
        route.vias,
        key=lambda v: (net_numbers.get(v.net_name, -1), v.at, v.size_mm, v.drill_mm),
    )
    for via in vias:
        net = net_numbers[via.net_name]
        uid = _det_uuid("via", via.net_name, via.at, via.size_mm, via.drill_mm)
        lines.append(
            f"{indent}(via (at {_fmt(via.at[0])} {_fmt(via.at[1])}) (size {_fmt(via.size_mm)}) "
            f'(drill {_fmt(via.drill_mm)}) (layers "{via.layers[0]}" "{via.layers[1]}") '
            f'(net {net}) (uuid "{uid}"))'
        )
    return "\n".join(lines)


def apply_ses_to_pcb(pcb_text: str, ses_text: str) -> tuple[str, SesRoute]:
    """Return ``(updated_pcb_text, route)`` with the SES routing applied.

    Segments and vias are inserted just before the closing paren of the top-level
    ``(kicad_pcb ...)`` block; the rest of the file is left byte-for-byte unchanged
    (round-trip safe). Re-applying the same SES is deterministic and idempotent.
    """
    route = parse_ses(ses_text)
    net_numbers = parse_net_numbers(pcb_text)
    # KiCad 10's current PCB dialect stores (net "NAME") on actual pads and
    # copper items, without the historical (net N "NAME") table. The legacy
    # renderer emits numeric track nets and MUST NOT be used on such a board.
    # A reviewed, KiCad-native and DRC-preflighted writer is required there.
    if route.net_names and not any(number > 0 for number in net_numbers.values()):
        if re.search(r'\(net\s+"(?:\\.|[^"\\])*"\)', pcb_text):
            raise ValueError(
                "SES routing refused: this KiCad PCB uses named-only net encoding "
                '((net "NAME")), which this numeric-net SES writer does not support. '
                "No routing was applied."
            )
    rendered = render_pcb_items(route, net_numbers)
    if not rendered:
        return pcb_text, route

    # Idempotency: drop any segment/via this module applied previously (our deterministic
    # UUIDs) so re-applying the same SES replaces rather than duplicates the routing. Only
    # our own items are touched -- hand-routed tracks have different UUIDs and are kept.
    applied_uuids = set(re.findall(r'\(uuid "([0-9a-f-]+)"\)\)$', rendered, re.MULTILINE))
    kept_lines = [
        line
        for line in pcb_text.splitlines()
        if not (
            ("(segment " in line or "(via " in line) and any(uid in line for uid in applied_uuids)
        )
    ]
    cleaned = "\n".join(kept_lines)

    trailing = ""
    body = cleaned
    while body and body[-1] in "\r\n \t":
        trailing = body[-1] + trailing
        body = body[:-1]
    if not body.endswith(")"):
        raise ValueError("Input does not look like a (kicad_pcb ...) document.")
    updated = f"{body[:-1].rstrip()}\n{rendered}\n)"
    trailing = trailing or ("\n" if pcb_text.endswith("\n") else "")
    return updated + trailing, route
