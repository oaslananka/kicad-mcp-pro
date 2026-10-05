from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.manufacturing.release_evidence")
    assert spec is not None, "Manufacturing release-evidence service must be extracted"
    return importlib.import_module("kicad_mcp.manufacturing.release_evidence")


def _context(tmp_path: Path):  # type: ignore[no-untyped-def]
    module = _module()
    project_dir = tmp_path / "project"
    output_dir = project_dir / "output"
    project_dir.mkdir()
    output_dir.mkdir()
    project_file = project_dir / "demo.kicad_pro"
    pcb_file = project_dir / "demo.kicad_pcb"
    sch_file = project_dir / "demo.kicad_sch"
    for path in (project_file, pcb_file, sch_file):
        path.write_text(path.name, encoding="utf-8")
    for name, content in (
        ("demo-F_Cu.gbr", "gerber"),
        ("demo.drl", "drill"),
        ("demo-bom.csv", "bom"),
        ("demo-pos.csv", "placement"),
    ):
        (output_dir / name).write_text(content, encoding="utf-8")
    return module.ReleaseEvidenceContext(
        output_dir=output_dir,
        project_dir=project_dir,
        project_file=project_file,
        pcb_file=pcb_file,
        sch_file=sch_file,
        kicad_cli=Path("/usr/bin/kicad-cli"),
        kicad_cli_version="10.0.6",
        kicad_mcp_version="3.37.0",
    )


def _gate(payload: dict[str, object], name: str) -> dict[str, object]:
    gates = payload["gates"]
    assert isinstance(gates, list)
    return next(gate for gate in gates if isinstance(gate, dict) and gate.get("gate") == name)


def _successful_service(module: ModuleType):  # type: ignore[no-untyped-def]
    return module.ReleaseEvidenceService(run_cli=_successful_runner)


def _successful_runner(*args: str) -> tuple[int, str, str]:
    output = Path(args[args.index("--output") + 1])
    if args[:2] == ("pcb", "drc"):
        output.write_text(json.dumps({"violations": [], "unconnected_items": []}), encoding="utf-8")
    elif args[:2] == ("sch", "erc"):
        output.write_text(json.dumps({"violations": []}), encoding="utf-8")
    else:  # pragma: no cover - defensive test helper
        raise AssertionError(args)
    return 0, "", ""


def test_release_evidence_service_approves_complete_selv_dry_run(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    service = module.ReleaseEvidenceService(
        run_cli=_successful_runner,
        now_utc=lambda: datetime(2026, 10, 3, tzinfo=UTC),
    )

    first = json.loads(
        service.create_evidence(
            context=context,
            product_domain="selv",
            voltage_v=3.3,
            dry_run=True,
        )
    )
    second = json.loads(
        service.create_evidence(
            context=context,
            product_domain="selv",
            voltage_v=3.3,
            dry_run=True,
        )
    )

    assert first["verdict"] == "release_approved"
    assert first["blocking_reasons"] == []
    assert first["dry_run"] is True
    assert first["evidence_path"] is None
    assert first["content_hash"] == second["content_hash"]
    assert {gate["gate"] for gate in first["gates"]} == {
        "artifact_coverage",
        "drc",
        "erc",
        "hv_safety",
    }


def test_release_evidence_service_blocks_hv_without_dru(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    service = _successful_service(module)

    payload = json.loads(
        service.create_evidence(
            context=context,
            product_domain="hazardous_mains",
            voltage_v=230.0,
            dry_run=True,
        )
    )

    hv_gate = _gate(payload, "hv_safety")
    assert hv_gate["applicable"] is True
    assert hv_gate["passed"] is False
    assert payload["verdict"] == "release_blocked"
    assert any("creepage" in reason.lower() for reason in payload["blocking_reasons"])


def test_release_evidence_service_writes_evidence_and_release_hashes(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    service = _successful_service(module)

    payload = json.loads(service.create_evidence(context=context, dry_run=False))

    evidence_path = Path(payload["evidence_path"])
    assert evidence_path == context.output_dir / "release_evidence.json"
    assert evidence_path.exists()
    persisted = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert persisted["content_hash"] == payload["content_hash"]
    assert persisted["file_count"] == 4
    assert [entry["filename"] for entry in persisted["files"]] == [
        "demo-F_Cu.gbr",
        "demo-bom.csv",
        "demo-pos.csv",
        "demo.drl",
    ]


def test_release_evidence_service_honors_safe_output_path(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    service = _successful_service(module)

    payload = json.loads(
        service.create_evidence(
            context=context,
            output_path="release/evidence",
            dry_run=False,
        )
    )

    expected = context.project_dir / "release" / "evidence" / "release_evidence.json"
    assert Path(payload["evidence_path"]) == expected
    assert expected.exists()
    artifact_gate = _gate(payload, "artifact_coverage")
    assert artifact_gate["passed"] is True
    assert artifact_gate["missing"] == []


def test_release_evidence_service_rejects_output_path_traversal(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    service = _successful_service(module)

    with pytest.raises(ValueError, match="escapes"):
        service.create_evidence(
            context=context,
            output_path="../outside",
            dry_run=True,
        )


def test_generic_csv_does_not_satisfy_bom_or_pick_and_place(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    (context.output_dir / "demo-bom.csv").unlink()
    (context.output_dir / "demo-pos.csv").unlink()
    (context.output_dir / "assembly.csv").write_text("generic\n", encoding="utf-8")
    service = _successful_service(module)

    payload = json.loads(service.create_evidence(context=context, dry_run=True))
    artifact_gate = _gate(payload, "artifact_coverage")

    assert artifact_gate["found"] == ["gerber", "drill"]
    assert artifact_gate["missing"] == ["bom", "pick_and_place"]
    assert artifact_gate["passed"] is False


def test_position_gerber_does_not_satisfy_board_gerber_coverage(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)
    (context.output_dir / "demo-F_Cu.gbr").unlink()
    (context.output_dir / "demo-pos.csv").unlink()
    position_dir = context.output_dir / "pos"
    position_dir.mkdir()
    (position_dir / "board-pos.gbr").write_text("placement\n", encoding="utf-8")
    service = _successful_service(module)

    payload = json.loads(service.create_evidence(context=context, dry_run=True))
    artifact_gate = _gate(payload, "artifact_coverage")

    assert "pick_and_place" in artifact_gate["found"]
    assert "gerber" in artifact_gate["missing"]
    assert artifact_gate["passed"] is False


def test_release_file_hashes_use_relative_paths_for_duplicate_names(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "output"
    first = output / "gerber" / "board.gbr"
    second = output / "archive" / "board.gbr"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")

    records = module.build_release_file_hashes(
        [first, second],
        relative_to=output,
    )

    assert [entry["filename"] for entry in records] == [
        "archive/board.gbr",
        "gerber/board.gbr",
    ]


def test_release_file_hashes_tolerate_disappearing_file(tmp_path: Path) -> None:
    module = _module()
    artifact = tmp_path / "vanished.csv"
    artifact.write_text("temporary\n", encoding="utf-8")
    artifact.unlink()

    records = module.build_release_file_hashes([artifact])

    assert records == [
        {
            "filename": "vanished.csv",
            "sha256": "unavailable",
            "size_bytes": "unavailable",
        }
    ]


def test_artifact_coverage_recognizes_nested_export_layout(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "output"
    gerber = output / "gerber"
    position = output / "pos"
    gerber.mkdir(parents=True)
    position.mkdir()
    (gerber / "demo-F_Cu.gbr").write_text("gerber\n", encoding="utf-8")
    (gerber / "demo.drl").write_text("drill\n", encoding="utf-8")
    (output / "bom.csv").write_text("bom\n", encoding="utf-8")
    (position / "board-pos.csv").write_text("placement\n", encoding="utf-8")

    coverage = module.artifact_coverage(output)

    assert {name: [path.name for path in paths] for name, paths in coverage.items()} == {
        "gerber": ["demo-F_Cu.gbr"],
        "drill": ["demo.drl"],
        "bom": ["bom.csv"],
        "pick_and_place": ["board-pos.csv"],
    }


def test_release_evidence_service_reports_drc_and_erc_cli_failures(tmp_path: Path) -> None:
    module = _module()
    context = _context(tmp_path)

    def failing_runner(*args: str) -> tuple[int, str, str]:
        if args[:2] == ("pcb", "drc"):
            return 2, "", "drc failed"
        if args[:2] == ("sch", "erc"):
            return 3, "erc failed", ""
        raise AssertionError(args)

    service = module.ReleaseEvidenceService(run_cli=failing_runner)
    payload = json.loads(
        service.create_evidence(
            context=context,
            waive_missing_artifacts=True,
            dry_run=True,
        )
    )

    drc = _gate(payload, "drc")
    erc = _gate(payload, "erc")
    assert drc["passed"] is False
    assert drc["error"] == "drc failed"
    assert erc["passed"] is False
    assert erc["error"] == "erc failed"
    assert "DRC could not run: drc failed" in payload["blocking_reasons"]
    assert "ERC could not run: erc failed" in payload["blocking_reasons"]


def test_release_evidence_service_reports_missing_pcb_and_schematic(tmp_path: Path) -> None:
    module = _module()
    context = replace(_context(tmp_path), pcb_file=None, sch_file=None)

    def unexpected_runner(*_args: str) -> tuple[int, str, str]:
        raise AssertionError("CLI must not run without configured source files")

    service = module.ReleaseEvidenceService(run_cli=unexpected_runner)
    payload = json.loads(
        service.create_evidence(
            context=context,
            waive_missing_artifacts=True,
            dry_run=True,
        )
    )

    drc = _gate(payload, "drc")
    erc = _gate(payload, "erc")
    assert drc["error"] == "No PCB file configured."
    assert erc["error"] == "No schematic file configured."
    assert payload["verdict"] == "release_blocked"
