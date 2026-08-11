"""FastMCP-independent placed-component contract verification orchestration."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models import contract_verifier as cv
from ..models.component_contracts import find_component_contract


def _resolve_symbol(
    schematic_files: list[Path], reference: str
) -> tuple[tuple[str, str], str | None] | None:
    for sch_file in schematic_files:
        try:
            sch_text = sch_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = cv.find_symbol_instance(sch_text, reference)
        if found is not None:
            return found, cv.extract_lib_symbol_block(sch_text, found[0])
    return None


def _datasheet_from_symbol(symbol_block: str | None) -> str:
    if symbol_block is None:
        return ""
    match = re.search(r'\(property\s+"Datasheet"\s+"([^"]*)"', symbol_block)
    if match is None or match.group(1) in ("", "~"):
        return ""
    return match.group(1)


def _footprint_evidence(
    footprint_file: Callable[[str, str], Path], footprint_id: str
) -> tuple[cv.FootprintShape, bool]:
    if not footprint_id or ":" not in footprint_id:
        return cv.FootprintShape(), False
    fp_library, fp_name = footprint_id.split(":", 1)
    try:
        fp_path = footprint_file(fp_library, fp_name)
    except (OSError, ValueError):
        return cv.FootprintShape(), False
    if not fp_path.exists():
        return cv.FootprintShape(), False
    return (
        cv.parse_footprint(fp_path.read_text(encoding="utf-8", errors="ignore")),
        True,
    )


def _footprint_note(footprint_id: str, footprint_read: bool) -> str | None:
    if footprint_id and not footprint_read:
        return "Footprint file could not be located; pad-level checks were skipped."
    if not footprint_id:
        return "No footprint is assigned to this reference; pad checks were skipped."
    return None


@dataclass(frozen=True)
class LibraryComponentContractService:
    """Resolve local project evidence and delegate structural verification."""

    project_schematic_files: Callable[[], list[Path]]
    footprint_file: Callable[[str, str], Path]

    def verify(self, reference: str) -> str:
        reference = reference.strip()
        if not reference:
            return json.dumps({"error": "reference must not be empty."})

        resolved_symbol = _resolve_symbol(self.project_schematic_files(), reference)
        if resolved_symbol is None:
            return json.dumps(
                {"error": f"No placed symbol with reference '{reference}' was found."}
            )

        (lib_id, footprint_id), symbol_block = resolved_symbol
        pins = cv.parse_symbol_pins(symbol_block) if symbol_block else ()
        footprint_shape, footprint_read = _footprint_evidence(self.footprint_file, footprint_id)
        contract = find_component_contract(lib_id=lib_id, footprint=footprint_id)
        report = cv.verify_contract(
            reference=reference,
            lib_id=lib_id,
            footprint_id=footprint_id,
            pins=pins,
            footprint=footprint_shape,
            datasheet=_datasheet_from_symbol(symbol_block),
            known_contract_category=contract.category if contract else "",
        )
        result = report.as_dict()
        note = _footprint_note(footprint_id, footprint_read)
        if note is not None:
            result["notes"] = [note]
        return json.dumps(result, indent=2)
