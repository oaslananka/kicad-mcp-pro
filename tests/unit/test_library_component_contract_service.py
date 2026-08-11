from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.library.component_contract")
    assert spec is not None, "Library component-contract service must be extracted"
    return importlib.import_module("kicad_mcp.library.component_contract")


SCHEMATIC = """(kicad_sch
  (lib_symbols
    (symbol "Device:R"
      (property "Datasheet" "https://example.test/r")
      (pin passive line (name "A") (number "1"))
      (pin passive line (name "B") (number "2"))))
  (symbol (lib_id "Device:R")
    (property "Reference" "R1")
    (property "Footprint" "Resistor_SMD:R_0603")))"""

NO_FOOTPRINT_SCHEMATIC = """(kicad_sch
  (lib_symbols
    (symbol "Device:R"
      (pin passive line (name "A") (number "1"))))
  (symbol (lib_id "Device:R")
    (property "Reference" "R2")))"""

FOOTPRINT = """(footprint "R_0603"
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at 2 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask"))
  (fp_rect (start 0 0) (end 1 1) (stroke (width 0.1) (type default)) (fill none) (layer "F.CrtYd"))
  (fp_rect (start 0 0) (end 1 1) (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))
  (fp_line (start 0 0) (end 1 0) (stroke (width 0.1) (type default)) (layer "F.SilkS"))
  (model "R.step"))"""


def test_verify_rejects_blank_and_unknown_reference(tmp_path: Path) -> None:
    module = _module()
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text(SCHEMATIC, encoding="utf-8")
    service = module.LibraryComponentContractService(
        project_schematic_files=lambda: [sch],
        footprint_file=lambda _library, _footprint: tmp_path / "missing.kicad_mod",
    )

    assert service.verify("   ") == json.dumps({"error": "reference must not be empty."})
    assert service.verify("R404") == json.dumps(
        {"error": "No placed symbol with reference 'R404' was found."}
    )


def test_verify_skips_unreadable_schematic_and_preserves_pass_report(tmp_path: Path) -> None:
    module = _module()
    missing = tmp_path / "unreadable.kicad_sch"
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text(SCHEMATIC, encoding="utf-8")
    fp = tmp_path / "R_0603.kicad_mod"
    fp.write_text(FOOTPRINT, encoding="utf-8")
    service = module.LibraryComponentContractService(
        project_schematic_files=lambda: [missing, sch],
        footprint_file=lambda _library, _footprint: fp,
    )

    report = json.loads(service.verify(" R1 "))

    assert report["reference"] == "R1"
    assert report["lib_id"] == "Device:R"
    assert report["footprint"] == "Resistor_SMD:R_0603"
    assert report["status"] == "PASS"
    assert "notes" not in report


def test_verify_preserves_missing_footprint_notes_and_resolver_errors(tmp_path: Path) -> None:
    module = _module()
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text(SCHEMATIC, encoding="utf-8")
    no_fp = tmp_path / "no-fp.kicad_sch"
    no_fp.write_text(NO_FOOTPRINT_SCHEMATIC, encoding="utf-8")

    def fail_resolver(_library: str, _footprint: str) -> Path:
        raise ValueError("not resolvable")

    missing_service = module.LibraryComponentContractService(
        project_schematic_files=lambda: [sch], footprint_file=fail_resolver
    )
    missing = json.loads(missing_service.verify("R1"))
    assert missing["notes"] == [
        "Footprint file could not be located; pad-level checks were skipped."
    ]

    no_fp_service = module.LibraryComponentContractService(
        project_schematic_files=lambda: [no_fp], footprint_file=fail_resolver
    )
    no_footprint = json.loads(no_fp_service.verify("R2"))
    assert no_footprint["notes"] == [
        "No footprint is assigned to this reference; pad checks were skipped."
    ]
