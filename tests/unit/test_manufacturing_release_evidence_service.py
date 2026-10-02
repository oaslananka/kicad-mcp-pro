from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.manufacturing.release_evidence")
    assert spec is not None, "Manufacturing release-evidence service must be extracted"
    return importlib.import_module("kicad_mcp.manufacturing.release_evidence")


def _context(module: ModuleType, root: Path):
    output_dir = root / "output"
    output_dir.mkdir()
    project = root / "demo.kicad_pro"
    pcb = root / "demo.kicad_pcb"
    sch = root / "demo.kicad_sch"
    for path in (project, pcb, sch):
        path.write_text(path.name, encoding="utf-8")
    return module.ReleaseEvidenceContext(
        output_dir=output_dir,
        project_dir=root,
        project_file=project,
        pcb_file=pcb,
        sch_file=sch,
        kicad_cli=Path("kicad-cli"),
    )


def _passing_cli(*args: str) -> tuple[int, str, str]:
    output_index = args.index("--output") + 1
    report_path = Path(args[output_index])
    if args[:2] == ("pcb", "drc"):
        report = {"violations": [], "unconnected_items": []}
    else:
        report = {"violations": []}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return 0, "", ""


def test_dry_run_preserves_gate_shape_and_content_hash(tmp_path: Path) -> None:
    module = _module()
    ctx = _context(module, tmp_path)
    (ctx.output_dir / "demo-F_Cu.gbr").write_text("gbr", encoding="utf-8")
    (ctx.output_dir / "demo.drl").write_text("drl", encoding="utf-8")
    (ctx.output_dir / "bom.csv").write_text("bom", encoding="utf-8")
    service = module.ManufacturingReleaseEvidenceService(
        get_context=lambda: ctx,
        run_cli=_passing_cli,
        get_cli_capabilities=lambda _cli: SimpleNamespace(version="10.0.1"),
        package_version="3.37.0",
        now=lambda: datetime(2026, 10, 3, tzinfo=UTC),
    )

    payload = json.loads(service.create(product_domain="selv", voltage_v=3.3, dry_run=True))

    assert payload["verdict"] == "release_approved"
    assert payload["dry_run"] is True
    assert payload["evidence_path"] is None
    assert {gate["gate"] for gate in payload["gates"]} == {
        "artifact_coverage",
        "drc",
        "erc",
        "hv_safety",
    }
    assert payload["provenance"]["kicad_mcp_version"] == "3.37.0"
    assert payload["provenance"]["kicad_cli_version"] == "10.0.1"
    assert payload["content_hash"]


def test_hv_gate_blocks_without_creepage_rules(tmp_path: Path) -> None:
    module = _module()
    ctx = _context(module, tmp_path)
    service = module.ManufacturingReleaseEvidenceService(
        get_context=lambda: ctx,
        run_cli=_passing_cli,
        get_cli_capabilities=lambda _cli: SimpleNamespace(version="10.0.1"),
        package_version="3.37.0",
    )

    payload = json.loads(
        service.create(product_domain="hazardous_mains", voltage_v=230.0, dry_run=True)
    )

    hv = next(g for g in payload["gates"] if g["gate"] == "hv_safety")
    assert hv["applicable"] is True
    assert hv["passed"] is False
    assert payload["verdict"] == "release_blocked"
    assert any("kicad_dru" in reason for reason in payload["blocking_reasons"])


def test_non_dry_run_writes_release_evidence_json(tmp_path: Path) -> None:
    module = _module()
    ctx = _context(module, tmp_path)
    service = module.ManufacturingReleaseEvidenceService(
        get_context=lambda: ctx,
        run_cli=_passing_cli,
        get_cli_capabilities=lambda _cli: SimpleNamespace(version="10.0.1"),
        package_version="3.37.0",
    )

    payload = json.loads(service.create(waive_missing_artifacts=True, dry_run=False))

    evidence_path = Path(payload["evidence_path"])
    assert evidence_path == ctx.output_dir / "release_evidence.json"
    assert evidence_path.exists()
    on_disk = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert on_disk["content_hash"] == payload["content_hash"]
