from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.manufacturing.release_evidence")
    assert spec is not None, "Manufacturing release-evidence service module must be extracted"
    return importlib.import_module("kicad_mcp.manufacturing.release_evidence")


def _context(tmp_path: Path):  # type: ignore[no-untyped-def]
    module = _module()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    project = tmp_path / "demo.kicad_pro"
    pcb = tmp_path / "demo.kicad_pcb"
    sch = tmp_path / "demo.kicad_sch"
    project.write_text("project", encoding="utf-8")
    pcb.write_text("pcb", encoding="utf-8")
    sch.write_text("sch", encoding="utf-8")
    return module.ReleaseEvidenceContext(
        output_dir=output_dir,
        project_dir=tmp_path,
        project_file=project,
        pcb_file=pcb,
        sch_file=sch,
        kicad_cli=Path("kicad-cli"),
        kicad_cli_version="10.0.1",
        kicad_mcp_version="3.37.0",
    )


def test_release_evidence_dry_run_preserves_gate_shape_and_stable_hash(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    for name, content in [
        ("demo-F_Cu.gbr", "gerber"),
        ("demo.drl", "drill"),
        ("bom.csv", "bom"),
        ("positions.csv", "cpl"),
    ]:
        (context.output_dir / name).write_text(content, encoding="utf-8")

    service = module.ManufacturingReleaseEvidenceService(
        run_drc=lambda _pcb: module.DrcGateResult(passed=True, violations=0, unconnected_items=0),
        run_erc=lambda _sch: module.ErcGateResult(passed=True, violations=0),
        now=lambda: datetime(2026, 10, 3, 0, 0, tzinfo=UTC),
    )

    first = json.loads(service.create(context, dry_run=True, product_domain="selv", voltage_v=3.3))
    second = json.loads(service.create(context, dry_run=True, product_domain="selv", voltage_v=3.3))

    assert first["verdict"] == "release_approved"
    assert first["dry_run"] is True
    assert first["evidence_path"] is None
    assert first["content_hash"] == second["content_hash"]
    assert {gate["gate"] for gate in first["gates"]} == {
        "artifact_coverage",
        "drc",
        "erc",
        "hv_safety",
    }
    assert first["provenance"]["kicad_cli_version"] == "10.0.1"
    assert first["file_count"] == 4


def test_release_evidence_hv_and_missing_artifacts_block_without_waiver(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    service = module.ManufacturingReleaseEvidenceService(
        run_drc=lambda _pcb: module.DrcGateResult(passed=True, violations=0, unconnected_items=0),
        run_erc=lambda _sch: module.ErcGateResult(passed=True, violations=0),
    )

    payload = json.loads(
        service.create(
            context,
            dry_run=True,
            product_domain="hazardous_mains",
            voltage_v=230.0,
        )
    )

    assert payload["verdict"] == "release_blocked"
    assert any("Missing required artifacts" in reason for reason in payload["blocking_reasons"])
    hv_gate = next(gate for gate in payload["gates"] if gate["gate"] == "hv_safety")
    assert hv_gate["applicable"] is True
    assert hv_gate["passed"] is False
    assert "creepage" in hv_gate["detail"].lower()


def test_release_evidence_writes_expected_file_and_preserves_gate_errors(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    service = module.ManufacturingReleaseEvidenceService(
        run_drc=lambda _pcb: module.DrcGateResult(
            passed=False,
            violations=-1,
            unconnected_items=-1,
            error="No PCB file configured.",
        ),
        run_erc=lambda _sch: module.ErcGateResult(
            passed=False,
            violations=-1,
            error="No schematic file configured.",
        ),
    )

    payload = json.loads(service.create(context, waive_missing_artifacts=True, dry_run=False))

    assert payload["verdict"] == "release_blocked"
    assert "DRC could not run: No PCB file configured." in payload["blocking_reasons"]
    assert "ERC could not run: No schematic file configured." in payload["blocking_reasons"]
    evidence_path = Path(payload["evidence_path"])
    assert evidence_path == context.output_dir / "release_evidence.json"
    assert evidence_path.is_file()
