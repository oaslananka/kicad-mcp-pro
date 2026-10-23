"""Structural symbol/footprint/pin contract verification.

This module provides the *pure* logic behind ``lib_verify_component_contract``
(issue #156): given a symbol definition (pins) and a footprint definition
(pads), it produces structured PASS/WARN/FAIL findings about whether the two
actually agree. Everything here is file-backed and free of network access and
of MCP/KiCad runtime dependencies, so it is cheap to unit-test in isolation.

The MCP tool wrapper in ``tools/library.py`` resolves a reference designator to
its symbol/footprint sources and then delegates the comparison to
``verify_contract``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Severity ordering, worst last, used to roll findings up into one status.
# INFO is purely advisory/evidence and shares PASS's rank so it never elevates
# the overall structural verdict.
_LEVEL_ORDER = {"PASS": 0, "INFO": 0, "WARN": 1, "FAIL": 2}


@dataclass(frozen=True, slots=True)
class Pin:
    """A single symbol pin."""

    number: str
    name: str
    electrical_type: str = ""


@dataclass(frozen=True, slots=True)
class FootprintShape:
    """Structural facts extracted from a ``.kicad_mod`` footprint."""

    connectable_pads: tuple[str, ...] = ()
    mechanical_pad_count: int = 0
    has_courtyard: bool = False
    has_fabrication: bool = False
    has_silkscreen: bool = False
    has_3d_model: bool = False


@dataclass(frozen=True, slots=True)
class Finding:
    """A single structured check result."""

    level: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class ContractReport:
    """Aggregated verification result for one reference designator."""

    reference: str
    lib_id: str
    footprint_id: str
    status: str
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "reference": self.reference,
            "lib_id": self.lib_id,
            "footprint": self.footprint_id,
            "status": self.status,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def _is_unescaped_quote(text: str, index: int, start: int) -> bool:
    """An even number of preceding backslashes makes the quote a delimiter."""
    back = index - 1
    while back >= start and text[back] == "\\":
        back -= 1
    return (index - back - 1) % 2 == 0


def extract_balanced_block(text: str, start: int) -> str:
    """Return the balanced ``(...)`` s-expression beginning at ``start``.

    String literals are respected so that parentheses inside quoted values do
    not unbalance the scan.
    """
    depth = 0
    in_string = False
    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if char == '"':
            if _is_unescaped_quote(text, index, start):
                in_string = not in_string
        elif not in_string:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        index += 1
    return text[start:]


def parse_symbol_pins(symbol_block: str) -> tuple[Pin, ...]:
    """Extract pins from a ``(symbol "Lib:Name" ...)`` definition block.

    Each ``(pin ...)`` sub-expression is isolated as a balanced block and parsed
    on its own, so a pin missing a name or number cannot bleed into the next
    pin's fields (a single non-greedy ``findall`` over the whole block could).
    Duplicate pin numbers (parts drawn as multiple units) are collapsed to the
    first occurrence so the count reflects distinct electrical pins.
    """

    # ``(pin`` + word boundary tolerates any whitespace after the keyword
    # (space/tab/newline) while still excluding ``(pin_numbers``/``(pin_names``.
    pin_start = re.compile(r"\(pin\b")
    seen: set[str] = set()
    pins: list[Pin] = []
    cursor = 0
    while True:
        match = pin_start.search(symbol_block, cursor)
        if match is None:
            break
        index = match.start()
        pin_block = extract_balanced_block(symbol_block, index)
        cursor = index + len(pin_block)
        type_match = re.match(r"\(pin\s+(\w+)", pin_block)
        # Quoted values may contain escaped chars (e.g. ``\"``); consume escape
        # pairs so an escaped quote inside a name does not truncate the match.
        name_match = re.search(r'\(name\s+"([^"\\]*(?:\\.[^"\\]*)*)"', pin_block)
        number_match = re.search(r'\(number\s+"([^"\\]*(?:\\.[^"\\]*)*)"', pin_block)
        if not (type_match and name_match and number_match):
            continue
        number = number_match.group(1)
        if number in seen:
            continue
        seen.add(number)
        pins.append(
            Pin(
                number=number,
                name=name_match.group(1),
                electrical_type=type_match.group(1),
            )
        )
    return tuple(pins)


def parse_footprint(text: str) -> FootprintShape:
    """Extract structural facts from ``.kicad_mod`` footprint text."""

    # Pad numbers may be quoted (``(pad "1" ...)``, modern KiCad) or bare
    # (``(pad 1 ...)``, older/hand-written footprints); accept both.
    pads = re.findall(r'\(pad\s+(?:"([^"]*)"|([^\s()]+))\s+(\w+)', text)
    connectable: list[str] = []
    mechanical = 0
    for quoted, unquoted, _pad_type in pads:
        number = quoted if quoted else unquoted
        if number == "":
            mechanical += 1
        else:
            connectable.append(number)
    return FootprintShape(
        connectable_pads=tuple(dict.fromkeys(connectable)),
        mechanical_pad_count=mechanical,
        has_courtyard=".CrtYd" in text,
        has_fabrication=".Fab" in text,
        has_silkscreen=".SilkS" in text,
        has_3d_model=bool(re.search(r"\(model\b", text)),
    )


def find_symbol_instance(sch_text: str, reference: str) -> tuple[str, str] | None:
    """Return ``(lib_id, footprint)`` for the symbol instance of ``reference``.

    Returns ``None`` if no placed symbol carries that reference designator.
    """

    for match in re.finditer(r"\(symbol\s+\(lib_", sch_text):
        block = extract_balanced_block(sch_text, match.start())
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', block)
        if ref_match is None or ref_match.group(1) != reference:
            continue
        lib_match = re.search(r'\(lib_id\s+"([^"]+)"', block)
        footprint_match = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', block)
        return (
            lib_match.group(1) if lib_match else "",
            footprint_match.group(1) if footprint_match else "",
        )
    return None


def extract_lib_symbol_block(sch_text: str, lib_id: str) -> str | None:
    """Return the ``(lib_symbols ...)`` definition block for ``lib_id``."""

    marker = f'(symbol "{lib_id}"'
    start = sch_text.find(marker)
    if start == -1:
        return None
    return extract_balanced_block(sch_text, start)


def _rollup(findings: list[Finding]) -> str:
    worst = 0
    for finding in findings:
        worst = max(worst, _LEVEL_ORDER.get(finding.level, 0))
    for level, rank in _LEVEL_ORDER.items():
        if rank == worst:
            return level
    return "PASS"


def _verify_pin_pad_alignment(pin_numbers: set[str], pad_numbers: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    if len(pin_numbers) == len(pad_numbers):
        findings.append(
            Finding(
                "PASS",
                "pin_pad_count",
                f"Pin count matches pad count ({len(pin_numbers)}).",
            )
        )
    else:
        findings.append(
            Finding(
                "FAIL",
                "pin_pad_count",
                f"Symbol has {len(pin_numbers)} pins but footprint has "
                f"{len(pad_numbers)} connectable pads.",
            )
        )

    only_pins = sorted(pin_numbers - pad_numbers)
    only_pads = sorted(pad_numbers - pin_numbers)
    if not only_pins and not only_pads:
        findings.append(
            Finding("PASS", "pin_pad_numbers", "Pin numbers match pad numbers exactly.")
        )
    else:
        if only_pins:
            findings.append(
                Finding(
                    "FAIL",
                    "pin_pad_numbers",
                    f"Pins with no matching pad: {', '.join(only_pins)}.",
                )
            )
        if only_pads:
            findings.append(
                Finding(
                    "WARN",
                    "pin_pad_numbers",
                    f"Pads with no matching pin: {', '.join(only_pads)}.",
                )
            )
    return findings


def _verify_metadata_and_model(
    footprint: FootprintShape,
    known_contract_category: str,
    datasheet: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if footprint.has_3d_model:
        findings.append(Finding("PASS", "model_3d", "Footprint references a 3D model."))
    else:
        findings.append(
            Finding("WARN", "model_3d", "Footprint does not reference a 3D model (advisory).")
        )

    if known_contract_category:
        findings.append(
            Finding(
                "PASS",
                "known_contract",
                f"Recognized as a '{known_contract_category}' component with a known "
                "connectivity contract.",
            )
        )

    if datasheet:
        findings.append(Finding("INFO", "datasheet", f"Datasheet evidence available: {datasheet}"))
    else:
        findings.append(
            Finding(
                "INFO",
                "datasheet",
                "No datasheet property on the symbol (advisory; not auto-filled).",
            )
        )
    return findings


def verify_contract(
    *,
    reference: str,
    lib_id: str,
    footprint_id: str,
    pins: tuple[Pin, ...],
    footprint: FootprintShape,
    datasheet: str = "",
    known_contract_category: str = "",
) -> ContractReport:
    """Compare symbol pins against footprint pads and emit structured findings.

    All checks are evidence-based: footprint completeness and the 3D-model
    presence are reported as WARN (advisory) rather than FAIL because a missing
    courtyard or model is a quality smell, not a guaranteed defect, whereas a
    pin/pad count or numbering mismatch is a hard contract violation (FAIL).
    """

    findings: list[Finding] = []

    pin_numbers = {pin.number for pin in pins if pin.number}
    pad_numbers = set(footprint.connectable_pads)

    if not pins:
        findings.append(
            Finding("WARN", "symbol_pins_unknown", "No pins could be read from the symbol.")
        )
    if not footprint.connectable_pads:
        findings.append(
            Finding("WARN", "footprint_pads_unknown", "No connectable pads found in the footprint.")
        )

    if pin_numbers and pad_numbers:
        findings.extend(_verify_pin_pad_alignment(pin_numbers, pad_numbers))

    findings.extend(
        [
            _completeness_finding("courtyard", footprint.has_courtyard),
            _completeness_finding("fabrication", footprint.has_fabrication),
            _completeness_finding("silkscreen", footprint.has_silkscreen),
        ]
    )
    findings.extend(_verify_metadata_and_model(footprint, known_contract_category, datasheet))

    return ContractReport(
        reference=reference,
        lib_id=lib_id,
        footprint_id=footprint_id,
        status=_rollup(findings),
        findings=tuple(findings),
    )


def _completeness_finding(layer: str, present: bool) -> Finding:
    if present:
        return Finding("PASS", f"footprint_{layer}", f"Footprint has {layer} geometry.")
    return Finding(
        "WARN",
        f"footprint_{layer}",
        f"Footprint is missing {layer} geometry (advisory).",
    )
