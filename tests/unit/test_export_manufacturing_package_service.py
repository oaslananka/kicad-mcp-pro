from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

import pytest


def _service_module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.export.manufacturing_package")
    assert spec is not None, "Manufacturing package service module must be extracted"
    return importlib.import_module("kicad_mcp.export.manufacturing_package")


@dataclass
class FakeOutcome:
    name: str
    status: str
    summary: str
    details: list[str]


class ManufacturingPackageService(Protocol):
    async def export(self, **kwargs: object) -> str: ...


def _approval_payload() -> dict[str, str]:
    return {
        "approved_by": "Test Reviewer",
        "approved_at_utc": "2026-08-11T00:00:00Z",
        "approval_scope": "manufacturing release",
    }


def _service(tmp_path: Path):  # type: ignore[no-untyped-def]
    module = _service_module()
    calls: dict[str, list[Any]] = {
        "resolve": [],
        "gerber": [],
        "drill": [],
        "bom": [],
        "pick": [],
        "ipc": [],
        "odb": [],
    }
    output_root = tmp_path / "output"

    def resolve_project_path(path_text: str) -> Path:
        calls["resolve"].append(path_text)
        if path_text == "unsafe.json":
            raise ValueError("unsafe evidence")
        return tmp_path / path_text

    def ensure_output_dir() -> Path:
        output_root.mkdir(parents=True, exist_ok=True)
        return output_root

    def write_export(label: str, variant_name: str | None) -> str:
        calls[label].append(variant_name)
        path = output_root / f"{label}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{label}:{variant_name}\n", encoding="utf-8")
        return f"{label} exported"

    service = module.ExportManufacturingPackageService(
        resolve_project_path=resolve_project_path,
        ensure_output_dir=ensure_output_dir,
        export_gerber=lambda variant_name: write_export("gerber", variant_name),
        export_drill=lambda variant_name: write_export("drill", variant_name),
        export_bom=lambda variant_name: write_export("bom", variant_name),
        export_pick_and_place=lambda variant_name: write_export("pick", variant_name),
        export_ipc2581=lambda variant_name: write_export("ipc", variant_name),
        export_odb=lambda variant_name: write_export("odb", variant_name),
    )
    return service, calls, output_root


async def _run_export(
    service: ManufacturingPackageService,
    *,
    variant: str = "",
    approval_evidence_path: str = "",
    outcomes: list[FakeOutcome] | None = None,
    ipc_result: str | None = None,
    odb_result: str | None = None,
):
    progress: list[tuple[int, int, str]] = []
    rendered: list[tuple[list[FakeOutcome], str]] = []
    outcomes = outcomes if outcomes is not None else []

    def evaluate_project_gate() -> list[FakeOutcome]:
        return outcomes

    def render_gate_report(values: list[Any], summary: str) -> str:
        rendered.append((values, summary))
        return f"gate::{summary}"

    async def report_progress(current: int, total: int, message: str) -> None:
        progress.append((current, total, message))

    if ipc_result is not None:
        object.__setattr__(service, "export_ipc2581", lambda _variant: ipc_result)
    if odb_result is not None:
        object.__setattr__(service, "export_odb", lambda _variant: odb_result)

    result = await service.export(
        variant=variant,
        approval_evidence_path=approval_evidence_path,
        evaluate_project_gate=evaluate_project_gate,
        render_gate_report=render_gate_report,
        report_progress=report_progress,
    )
    return result, progress, rendered


@pytest.mark.anyio
async def test_package_hard_blocks_failed_gate_before_evidence_or_exports(tmp_path: Path) -> None:
    service, calls, _output_root = _service(tmp_path)
    failed = [FakeOutcome("Schematic", "FAIL", "bad", ["ERC violations: 2"])]

    result, progress, rendered = await _run_export(service, outcomes=failed)

    summary = (
        "- Manufacturing package export is hard-blocked until the full project quality gate passes."
    )
    assert result == f"gate::{summary}"
    assert progress == [(5, 100, "Running full project quality gate...")]
    assert rendered == [(failed, summary)]
    assert calls["resolve"] == []
    assert all(not calls[name] for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"))


@pytest.mark.anyio
async def test_package_requires_and_validates_approval_evidence_after_gate_pass(
    tmp_path: Path,
) -> None:
    service, calls, _output_root = _service(tmp_path)

    missing, _progress, _rendered = await _run_export(service)
    assert missing == (
        "Manufacturing package export is hard-blocked until "
        "approval_evidence_path is supplied.\n"
        "- Run project_signoff_report() before final release export.\n"
        "- Store reviewer approval in a project-local JSON evidence file."
    )

    unsafe, _progress, _rendered = await _run_export(
        service,
        approval_evidence_path="unsafe.json",
    )
    assert "Manufacturing evidence path is invalid: unsafe evidence" in unsafe

    incomplete_path = tmp_path / ".kicad-mcp" / "manufacturing_approval.json"
    incomplete_path.parent.mkdir(parents=True)
    incomplete_path.write_text(json.dumps({"approved_by": "Reviewer"}), encoding="utf-8")
    incomplete, _progress, _rendered = await _run_export(
        service,
        approval_evidence_path=".kicad-mcp/manufacturing_approval.json",
    )
    assert "Manufacturing evidence is missing: approved_at_utc, approval_scope" in incomplete
    assert all(not calls[name] for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"))


@pytest.mark.anyio
async def test_package_preserves_explicit_variant_progress_report_and_artifacts(
    tmp_path: Path,
) -> None:
    service, calls, output_root = _service(tmp_path)
    evidence_path = tmp_path / ".kicad-mcp" / "manufacturing_approval.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(json.dumps(_approval_payload()), encoding="utf-8")

    result, progress, rendered = await _run_export(
        service,
        variant=" lite ",
        approval_evidence_path=".kicad-mcp/manufacturing_approval.json",
    )

    assert rendered == []
    assert progress == [
        (5, 100, "Running full project quality gate..."),
        (25, 100, "Exporting Gerbers..."),
        (45, 100, "Exporting drill files..."),
        (65, 100, "Exporting BOM..."),
        (85, 100, "Exporting pick-and-place data..."),
        (100, 100, "Manufacturing package complete."),
    ]
    for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"):
        assert calls[name] == ["lite"]
    assert "gerber exported" in result
    assert "drill exported" in result
    assert "bom exported" in result
    assert "pick exported" in result
    assert "ipc exported" in result
    assert "odb exported" in result
    assert "Manufacturing release evidence:" in result

    report_path = output_root / "manufacturing_release_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "manufacturing_release.v1"
    assert report["variant"] == "lite"
    assert report["approval_evidence_path"] == str(evidence_path)
    assert report["approval_evidence"]["approved_by"] == "Test Reviewer"
    assert report["quality_gate"] == []
    assert report["export_results"] == [
        "gerber exported",
        "drill exported",
        "bom exported",
        "pick exported",
        "ipc exported",
        "odb exported",
    ]
    assert report["artifacts"]
    assert all(
        {"path", "relative_path", "size_bytes", "sha256"} <= set(item)
        for item in report["artifacts"]
    )


@pytest.mark.anyio
async def test_package_omits_unsupported_optional_manufacturing_formats(tmp_path: Path) -> None:
    service, _calls, _output_root = _service(tmp_path)
    evidence_path = tmp_path / "approval.json"
    evidence_path.write_text(json.dumps(_approval_payload()), encoding="utf-8")

    result, _progress, _rendered = await _run_export(
        service,
        approval_evidence_path="approval.json",
        ipc_result="IPC-2581 export is not supported by the detected KiCad CLI.",
        odb_result="ODB++ export is not supported by the detected KiCad CLI.",
    )

    assert "IPC-2581 export is not supported" not in result
    assert "ODB++ export is not supported" not in result
    report = json.loads(
        (tmp_path / "output" / "manufacturing_release_report.json").read_text(encoding="utf-8")
    )
    assert all("not supported" not in item for item in report["export_results"])


@pytest.mark.anyio
async def test_package_revalidates_approved_project_file_digests_at_export_boundary(
    tmp_path: Path,
) -> None:
    import hashlib

    service, calls, _output_root = _service(tmp_path)
    board = tmp_path / "board.kicad_pcb"
    board.write_text("approved-state\n", encoding="utf-8")
    approval = _approval_payload() | {
        "approved_project_files": [
            {
                "path": "board.kicad_pcb",
                "sha256": hashlib.sha256(board.read_bytes()).hexdigest(),
            }
        ]
    }
    evidence_path = tmp_path / "approval.json"
    evidence_path.write_text(json.dumps(approval), encoding="utf-8")
    board.write_text("changed-after-approval\n", encoding="utf-8")

    result, _progress, _rendered = await _run_export(
        service, approval_evidence_path="approval.json"
    )

    assert "approved project file digest mismatch" in result
    assert all(not calls[name] for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"))


@pytest.mark.anyio
async def test_package_rejects_project_file_added_after_bound_approval(tmp_path: Path) -> None:
    import hashlib

    service, calls, _output_root = _service(tmp_path)
    board = tmp_path / "board.kicad_pcb"
    schematic = tmp_path / "board.kicad_sch"
    board.write_text("board\n", encoding="utf-8")
    schematic.write_text("schematic\n", encoding="utf-8")
    approved_files = [
        {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in (board, schematic)
    ]
    tree = hashlib.sha256()
    for item in approved_files:
        tree.update(item["path"].encode("utf-8"))
        tree.update(b"\0")
        tree.update(item["sha256"].encode("ascii"))
        tree.update(b"\n")
    approval = _approval_payload() | {
        "approved_project_files": approved_files,
        "project_state_digest": f"sha256:{tree.hexdigest()}",
    }
    evidence_path = tmp_path / "approval.json"
    evidence_path.write_text(json.dumps(approval), encoding="utf-8")
    (tmp_path / "unreviewed.kicad_dru").write_text("rules\n", encoding="utf-8")

    result, _progress, _rendered = await _run_export(
        service, approval_evidence_path="approval.json"
    )

    assert "approved project state digest mismatch" in result
    assert all(not calls[name] for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"))


@pytest.mark.anyio
async def test_reference_approval_filename_requires_project_state_bindings(tmp_path: Path) -> None:
    service, calls, _output_root = _service(tmp_path)
    evidence_path = tmp_path / "reference-manufacturing-approval.json"
    evidence_path.write_text(json.dumps(_approval_payload()), encoding="utf-8")

    result, _progress, _rendered = await _run_export(
        service, approval_evidence_path="reference-manufacturing-approval.json"
    )

    assert "reference approval requires bound project state" in result
    assert all(not calls[name] for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "approved_files, expected",
    [
        ([], "approved project files are invalid"),
        (["bad"], "approved project files are invalid"),
        ([{"path": 1, "sha256": "0" * 64}], "approved project files are invalid"),
        ([{"path": "board.kicad_pcb", "sha256": "bad"}], "approved project files are invalid"),
        (
            [
                {"path": "board.kicad_pcb", "sha256": "0" * 64},
                {"path": "board.kicad_pcb", "sha256": "0" * 64},
            ],
            "approved project files are invalid",
        ),
    ],
)
async def test_package_rejects_malformed_bound_file_manifests(
    tmp_path: Path, approved_files: object, expected: str
) -> None:
    service, calls, _output_root = _service(tmp_path)
    evidence_path = tmp_path / "approval.json"
    evidence_path.write_text(
        json.dumps(_approval_payload() | {"approved_project_files": approved_files}),
        encoding="utf-8",
    )

    result, _progress, _rendered = await _run_export(
        service, approval_evidence_path="approval.json"
    )

    assert expected in result
    assert result.splitlines() == [
        "Manufacturing evidence approved project files are invalid.",
        "- Manufacturing export stopped before artifact generation.",
        "- Obtain fresh human approval for the current project state.",
    ]
    assert all(not calls[name] for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"))


@pytest.mark.anyio
async def test_package_rejects_invalid_bound_state_digest(tmp_path: Path) -> None:
    import hashlib

    service, calls, _output_root = _service(tmp_path)
    board = tmp_path / "board.kicad_pcb"
    board.write_text("board\n", encoding="utf-8")
    approved_files = [
        {"path": board.name, "sha256": hashlib.sha256(board.read_bytes()).hexdigest()}
    ]
    evidence_path = tmp_path / "approval.json"
    evidence_path.write_text(
        json.dumps(
            _approval_payload()
            | {"approved_project_files": approved_files, "project_state_digest": "not-a-digest"}
        ),
        encoding="utf-8",
    )

    result, _progress, _rendered = await _run_export(
        service, approval_evidence_path="approval.json"
    )

    assert "approved project state digest is invalid" in result
    assert all(not calls[name] for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"))


@pytest.mark.anyio
async def test_package_rejects_invalid_project_root_for_bound_manifest(tmp_path: Path) -> None:
    import hashlib

    service, calls, _output_root = _service(tmp_path)
    board = tmp_path / "board.kicad_pcb"
    board.write_text("board\n", encoding="utf-8")
    evidence_path = tmp_path / "approval.json"
    evidence_path.write_text(
        json.dumps(
            _approval_payload()
            | {
                "approved_project_files": [
                    {"path": board.name, "sha256": hashlib.sha256(board.read_bytes()).hexdigest()}
                ]
            }
        ),
        encoding="utf-8",
    )
    original_resolver = service.resolve_project_path
    object.__setattr__(
        service,
        "resolve_project_path",
        lambda text: (
            (_ for _ in ()).throw(ValueError("root unavailable"))
            if text == "."
            else original_resolver(text)
        ),
    )

    result, _progress, _rendered = await _run_export(
        service, approval_evidence_path="approval.json"
    )

    assert "project root is invalid" in result
    assert all(not calls[name] for name in ("gerber", "drill", "bom", "pick", "ipc", "odb"))
