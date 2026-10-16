"""IPC-7351B footprint validation (work order P4-T3).

Checks an existing two-terminal chip footprint's land geometry against the
IPC-7351B nominal computed by :func:`footprint_gen.chip_pad_geometry` — the same
math the generator uses, so a footprint is validated against exactly what we would
have produced. Gross deviation fails (a hard gate), minor deviation warns.

Scope is honest: this validates chip passives (0201–2512) against the IPC-7351B
*standard* nominal. It is not a datasheet-specific land-pattern check (that needs
the part's recommended pattern) and does not yet cover SOIC/QFP/QFN/BGA.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .footprint_gen import DensityLevel, chip_pad_geometry
from .sexpr import _extract_block

FootprintVerdict = Literal["PASS", "WARN", "FAIL"]

# A pad whose width/height/pitch is off by more than this many mm is a hard fail;
# between the tolerance and this it is a warning.
_DEFAULT_TOL_MM = 0.12
_FAIL_MULTIPLIER = 2.0

_PAD_RE = re.compile(
    r"\(pad\s+\"?(?P<num>[^\s\"]+)\"?\s+smd\s+\w+\s+"
    r"\(at\s+(?P<x>-?\d+(?:\.\d+)?)\s+(?P<y>-?\d+(?:\.\d+)?)(?:\s+-?\d+(?:\.\d+)?)?\s*\)\s+"
    r"\(size\s+(?P<w>\d+(?:\.\d+)?)\s+(?P<h>\d+(?:\.\d+)?)\s*\)",
)


@dataclass(frozen=True)
class ParsedPad:
    num: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class FootprintCheck:
    verdict: FootprintVerdict
    summary: str
    findings: list[str] = field(default_factory=list)


def parse_smd_pads(footprint_text: str) -> list[ParsedPad]:
    """Extract SMD rectangular/roundrect/oval pads from .kicad_mod text."""
    pads: list[ParsedPad] = []
    for match in _PAD_RE.finditer(footprint_text):
        pads.append(
            ParsedPad(
                num=match.group("num"),
                x=float(match.group("x")),
                y=float(match.group("y")),
                w=float(match.group("w")),
                h=float(match.group("h")),
            )
        )
    return pads


def validate_chip_footprint(
    size_code: str,
    pads: list[ParsedPad],
    *,
    density: DensityLevel = "B",
    tol_mm: float = _DEFAULT_TOL_MM,
) -> FootprintCheck:
    """Validate a two-terminal chip footprint against its IPC-7351B nominal."""
    nominal = chip_pad_geometry(size_code, density)
    findings: list[str] = []
    fail_tol = tol_mm * _FAIL_MULTIPLIER
    worst: float = 0.0

    if len(pads) != 2:
        return FootprintCheck(
            verdict="FAIL",
            summary=(
                f"Expected 2 SMD pads for chip {size_code}, found {len(pads)}. "
                "Not a recognizable two-terminal chip land pattern."
            ),
            findings=[f"pad count {len(pads)} != 2"],
        )

    def _check(label: str, actual: float, nominal_value: float) -> None:
        nonlocal worst
        deviation = abs(actual - nominal_value)
        worst = max(worst, deviation)
        if deviation > tol_mm:
            findings.append(
                f"{label}: {actual:.3f} mm vs IPC nominal {nominal_value:.3f} mm "
                f"(Δ {deviation:.3f} mm)"
            )

    for pad in pads:
        _check(f"pad {pad.num} width", pad.w, nominal.pad_w)
        _check(f"pad {pad.num} height", pad.h, nominal.pad_h)
    measured_pitch = abs(pads[0].x - pads[1].x)
    _check("pad pitch", measured_pitch, nominal.pitch)

    if worst > fail_tol:
        verdict: FootprintVerdict = "FAIL"
        summary = (
            f"Chip {size_code} footprint deviates from IPC-7351B density {density} by "
            f"up to {worst:.3f} mm (> {fail_tol:.3f} mm) — blocking."
        )
    elif findings:
        verdict = "WARN"
        summary = (
            f"Chip {size_code} footprint is within {fail_tol:.3f} mm of IPC-7351B but "
            f"deviates beyond {tol_mm:.3f} mm on some dimensions."
        )
    else:
        verdict = "PASS"
        summary = (
            f"Chip {size_code} footprint matches IPC-7351B density {density} within "
            f"{tol_mm:.3f} mm."
        )
    return FootprintCheck(verdict=verdict, summary=summary, findings=findings)


# ---------------------------------------------------------------------------
# Pad-count vs package cross-check (issue #201)
# ---------------------------------------------------------------------------
# A package name encodes its pin count; the footprint must actually carry that
# many numbered pads. A footprint with fewer pads than its package promises is a
# hard error (silent fab-killer). This is package-agnostic and complements the
# chip-geometry check above.

# Families where the integer right after the family token IS the pin/lead count
# (e.g. SOIC-8, LQFP-48, QFN-32, TSSOP-20, PDIP-16). Longest names must be tried
# first so "TSSOP" wins over "SOP"/"SO" and "SDIP" wins over "DIP".
_PIN_COUNT_FAMILIES = (
    "HTSSOP",
    "TSSOP",
    "VSSOP",
    "SSOP",
    "QSOP",
    "MSOP",
    "SOIC",
    "SOP",
    "SO",
    "HVQFN",
    "WQFN",
    "UQFN",
    "VQFN",
    "TQFN",
    "QFN",
    "UDFN",
    "WDFN",
    "DFN",
    "LQFP",
    "TQFP",
    "MQFP",
    "HQFP",
    "QFP",
    "PLCC",
    "PDIP",
    "CDIP",
    "SDIP",
    "DIP",
)
# Families where the FIRST number is a JEDEC package code, not the pin count —
# the lead count (if present) follows a second dash: SOT-23-5, SOT-23-3,
# TO-252-3. Bare "SOT-23"/"SOT-223" carry no explicit lead count, so we skip
# them rather than guess (no false positives).
_CODE_FIRST_FAMILIES = ("SOT", "SOD", "SC", "TO")

_PIN_COUNT_RE = re.compile(
    r"(?<![A-Z])(?:" + "|".join(_PIN_COUNT_FAMILIES) + r")-(\d+)(?![0-9])",
    re.IGNORECASE,
)
_CODE_FIRST_RE = re.compile(
    r"(?<![A-Z])(?:" + "|".join(_CODE_FIRST_FAMILIES) + r")-\d+-(\d+)(?![0-9])",
    re.IGNORECASE,
)
_PAD_NUM_RE = re.compile(
    r'\(pad\s+"?(?P<num>[^"\s)]+)"?\s+(?:smd|thru_hole|connect)\b',
    re.IGNORECASE,
)
_THRU_HOLE_PAD_RE = re.compile(
    r'\(pad\s+"?[^"\s)]+"?\s+(?:np_thru_hole|thru_hole)\b',
    re.IGNORECASE,
)


def expected_pin_count_from_package(footprint_name: str) -> int | None:
    """Return the pin count a footprint's package name implies, or ``None``.

    Strips any ``Library:`` prefix. Returns ``None`` for packages whose name does
    not unambiguously encode a pin count (bare ``SOT-23``, grid-array BGA/LGA,
    plain chip codes), so the cross-check stays silent unless it is confident.
    """
    base = footprint_name.split(":")[-1]
    code_first = _CODE_FIRST_RE.search(base)
    if code_first is not None:
        return int(code_first.group(1))
    pin_count = _PIN_COUNT_RE.search(base)
    if pin_count is not None:
        return int(pin_count.group(1))
    return None


def count_thru_hole_pads(footprint_text: str) -> int:
    """Count through-hole pads, which :func:`parse_smd_pads` cannot see.

    ``parse_smd_pads`` matches ``smd`` pads only, so a through-hole footprint
    parses as zero pads. Callers use this to tell "no pads at all" apart from
    "pads outside this validator's scope" and report the difference honestly.
    """
    return len(_THRU_HOLE_PAD_RE.findall(footprint_text))


def count_numbered_pads(footprint_text: str) -> int:
    """Count distinct positive-integer pad numbers (signal pins) in .kicad_mod text.

    Mechanical/unnumbered pads (``np_thru_hole``, pads numbered ``""`` or ``0``)
    and grid-reference pads (``A1``) are not counted as signal pins.
    """
    numbers: set[int] = set()
    for match in _PAD_NUM_RE.finditer(footprint_text):
        token = match.group("num")
        if token.isdigit() and int(token) > 0:
            numbers.add(int(token))
    return len(numbers)


def check_footprint_pad_count(
    footprint_name: str,
    footprint_text: str,
    *,
    exposed_pad_tolerance: int = 2,
) -> FootprintCheck | None:
    """Cross-check a footprint's numbered-pad count against its package name.

    Returns ``None`` when the package name carries no certifiable pin count.
    Fewer pads than the package implies is a blocking ``FAIL``; a small surplus
    (within ``exposed_pad_tolerance``) is treated as an exposed/thermal pad and
    ``PASS``es with a note; a larger surplus ``WARN``s.
    """
    expected = expected_pin_count_from_package(footprint_name)
    if expected is None:
        return None
    actual = count_numbered_pads(footprint_text)
    package = footprint_name.split(":")[-1]

    if actual == expected:
        return FootprintCheck(
            verdict="PASS",
            summary=(
                f"Footprint '{package}' has {actual} numbered pads, "
                f"matching its {expected}-pin package."
            ),
        )
    if actual < expected:
        return FootprintCheck(
            verdict="FAIL",
            summary=(
                f"Footprint '{package}' has {actual} numbered pads but its package name implies "
                f"{expected} pins — pins are missing, which will not match the part."
            ),
            findings=[f"pad count {actual} < expected {expected}"],
        )
    if actual <= expected + exposed_pad_tolerance:
        extra = actual - expected
        return FootprintCheck(
            verdict="PASS",
            summary=(
                f"Footprint '{package}' has {actual} numbered pads for a {expected}-pin package; "
                f"the {extra} extra is likely an exposed/thermal pad."
            ),
        )
    return FootprintCheck(
        verdict="WARN",
        summary=(
            f"Footprint '{package}' has {actual} numbered pads but its package name implies "
            f"{expected} pins — more pads than expected."
        ),
        findings=[f"pad count {actual} > expected {expected} + {exposed_pad_tolerance}"],
    )


# ---------------------------------------------------------------------------
# Documentation-layer completeness (issue #201)
# ---------------------------------------------------------------------------
# A complete footprint carries a courtyard (placement/DRC clearance), a
# fabrication outline (assembly drawing), and a silkscreen outline (board
# legend). A missing courtyard is a hard gate because KiCad relies on it for
# component-to-component clearance; missing fab/silk degrade documentation.

_IPC_DENSITY_RE = re.compile(r"IPC[- ]?7351[ _]density[ _]?([ABC])|IPC7351_([ABC])", re.IGNORECASE)


def parse_ipc_density(footprint_text: str) -> str | None:
    """Return the IPC-7351 density level (``A``/``B``/``C``) a footprint records, or ``None``.

    Generated footprints embed the density they were built with in their descr/tags
    (see ``footprint_gen.ipc_density_tag``); this recovers it for certification.
    """
    match = _IPC_DENSITY_RE.search(footprint_text)
    if match is None:
        return None
    return (match.group(1) or match.group(2)).upper()


_FOOTPRINT_GEOMETRY_TOKENS = frozenset(
    {"fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_curve"}
)
_SEXPR_TOKEN_RE = re.compile(r"\(\s*([a-z_][a-z0-9_]*)\b", re.IGNORECASE)
_DOCUMENTATION_LAYER_RE = re.compile(
    r'\(layer\s+"?(?P<layer>[FB]\.(?:CrtYd|Fab|SilkS))"?\s*\)', re.IGNORECASE
)


def _match_geometry_layer(footprint_text: str, index: int) -> tuple[str | None, int]:
    token_match = _SEXPR_TOKEN_RE.match(footprint_text, index)
    if token_match and token_match.group(1).lower() in _FOOTPRINT_GEOMETRY_TOKENS:
        block, length = _extract_block(footprint_text, index)
        if block and length:
            layer_match = _DOCUMENTATION_LAYER_RE.search(block)
            layer = layer_match.group("layer").lower() if layer_match else None
            return layer, length
    return None, 1


def _footprint_geometry_layers(footprint_text: str) -> set[str]:
    """Return documentation layers used by actual footprint geometry elements."""
    layers: set[str] = set()
    index = 0
    in_string = False
    escaped = False
    while index < len(footprint_text):
        char = footprint_text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char == "(":
            layer, length = _match_geometry_layer(footprint_text, index)
            if layer:
                layers.add(layer)
            index += length
            continue
        index += 1
    return layers


def check_footprint_documentation_layers(footprint_text: str) -> FootprintCheck:
    """Verify a footprint has courtyard, fabrication, and silkscreen graphics.

    No courtyard is a blocking ``FAIL`` (KiCad uses it for placement clearance);
    a missing fab or silkscreen outline ``WARN``s. All three present ``PASS``es.
    """
    geometry_layers = _footprint_geometry_layers(footprint_text)
    has_courtyard = bool({"f.crtyd", "b.crtyd"} & geometry_layers)
    has_fab = bool({"f.fab", "b.fab"} & geometry_layers)
    has_silk = bool({"f.silks", "b.silks"} & geometry_layers)

    findings: list[str] = []
    if not has_fab:
        findings.append("no fabrication-layer (F.Fab/B.Fab) outline")
    if not has_silk:
        findings.append("no silkscreen-layer (F.SilkS/B.SilkS) outline")

    if not has_courtyard:
        return FootprintCheck(
            verdict="FAIL",
            summary=(
                "Footprint has no courtyard (F.CrtYd/B.CrtYd) — KiCad needs it for "
                "component-to-component placement clearance; blocking."
            ),
            findings=["no courtyard-layer (F.CrtYd/B.CrtYd) graphics", *findings],
        )
    if findings:
        return FootprintCheck(
            verdict="WARN",
            summary="Footprint has a courtyard but is missing documentation graphics.",
            findings=findings,
        )
    return FootprintCheck(
        verdict="PASS",
        summary="Footprint has courtyard, fabrication, and silkscreen graphics.",
    )
