"""FastMCP-independent placed-component contract verification orchestration."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models import contract_verifier as cv
from ..models.component_contracts import find_component_contract


@dataclass(frozen=True)
class LibraryComponentContractService:
    """Resolve local project evidence and delegate structural verification."""

    project_schematic_files: Callable[[], list[Path]]
    footprint_file: Callable[[str, str], Path]

    def verify(self, reference: str) -> str:
        reference = reference.strip()
        if not reference:
            return json.dumps({"error": "reference must not be empty."})

        resolved: tuple[str, str] | None = None
        symbol_block: str | None = None
        for sch_file in self.project_schematic_files():
            try:
                sch_text = sch_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found = cv.find_symbol_instance(sch_text, reference)
            if found is not None:
                resolved = found
                symbol_block = cv.extract_lib_symbol_block(sch_text, found[0])
                break

        if resolved is None:
            return json.dumps(
                {"error": f"No placed symbol with reference '{reference}' was found."}
            )

        lib_id, footprint_id = resolved
        pins = cv.parse_symbol_pins(symbol_block) if symbol_block else ()
        datasheet = ""
        if symbol_block:
            ds_match = re.search(r'\(property\s+"Datasheet"\s+"([^"]*)"', symbol_block)
            if ds_match and ds_match.group(1) not in ("", "~"):
                datasheet = ds_match.group(1)

        footprint_shape = cv.FootprintShape()
        footprint_read = False
        if footprint_id and ":" in footprint_id:
            fp_library, fp_name = footprint_id.split(":", 1)
            try:
                fp_path = self.footprint_file(fp_library, fp_name)
            except (OSError, ValueError):
                fp_path = None
            if fp_path is not None and fp_path.exists():
                footprint_shape = cv.parse_footprint(
                    fp_path.read_text(encoding="utf-8", errors="ignore")
                )
                footprint_read = True

        contract = find_component_contract(lib_id=lib_id, footprint=footprint_id)
        report = cv.verify_contract(
            reference=reference,
            lib_id=lib_id,
            footprint_id=footprint_id,
            pins=pins,
            footprint=footprint_shape,
            datasheet=datasheet,
            known_contract_category=contract.category if contract else "",
        )
        result = report.as_dict()
        notes: list[str] = []
        if footprint_id and not footprint_read:
            notes.append("Footprint file could not be located; pad-level checks were skipped.")
        elif not footprint_id:
            notes.append("No footprint is assigned to this reference; pad checks were skipped.")
        if notes:
            result["notes"] = notes
        return json.dumps(result, indent=2)
