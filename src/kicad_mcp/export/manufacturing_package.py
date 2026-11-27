"""FastMCP-independent gated manufacturing release orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio

from ..utils.metadata_write import atomic_metadata_write
from .inventory import discover_drill_output_files, discover_gerber_output_files

GateEvaluator = Callable[[], list[Any]]
GateRenderer = Callable[[list[Any], str], str]
ProgressReporter = Callable[[int, int, str], Awaitable[None]]
VariantExport = Callable[[str | None], str]

_MISSING_APPROVAL_EVIDENCE = (
    "Manufacturing package export is hard-blocked until approval_evidence_path is supplied."
)
_APPROVED_PROJECT_SUFFIXES = frozenset({".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_dru"})
_APPROVED_PROJECT_METADATA = frozenset({".kicad-mcp/project_spec.json", ".kicad-mcp/variants.json"})
_REFERENCE_APPROVAL_FILENAME = "reference-manufacturing-approval.json"
_INVALID_APPROVED_PROJECT_FILES = "Manufacturing evidence approved project files are invalid."


def _parse_approved_project_files(raw_files: object) -> list[tuple[str, str]] | str:
    if not isinstance(raw_files, list) or not raw_files:
        return _INVALID_APPROVED_PROJECT_FILES
    seen: set[str] = set()
    approved_files: list[tuple[str, str]] = []
    for item in raw_files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            return _INVALID_APPROVED_PROJECT_FILES
        relative = item.get("path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            return _INVALID_APPROVED_PROJECT_FILES
        invalid_digest = len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        )
        if relative in seen or invalid_digest:
            return _INVALID_APPROVED_PROJECT_FILES
        seen.add(relative)
        approved_files.append((relative, expected))
    return approved_files


def _verify_project_state_digest(
    expected_state: object,
    current_files: tuple[tuple[str, str], ...],
) -> str | None:
    if expected_state is None:
        return None
    if not isinstance(expected_state, str) or not expected_state.startswith("sha256:"):
        return "Manufacturing evidence approved project state digest is invalid."
    tree = hashlib.sha256()
    for relative, digest in current_files:
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(digest.encode("ascii"))
        tree.update(b"\n")
    if expected_state != f"sha256:{tree.hexdigest()}":
        return "Manufacturing evidence approved project state digest mismatch."
    return None


@dataclass(frozen=True)
class ManufacturingApprovalService:
    """Shared project quality and human approval boundary for release packages."""

    resolve_project_path: Callable[[str], Path]

    def authorize(
        self,
        *,
        outcomes: list[Any],
        render_gate_report: GateRenderer,
        approval_evidence_path: str,
    ) -> tuple[Path, dict[str, Any]] | str:
        """Verify release eligibility before creating any manufacturing output."""
        blocking = [outcome for outcome in outcomes if outcome.status != "PASS"]
        if blocking:
            return render_gate_report(
                blocking,
                "- Manufacturing package export is hard-blocked until the full "
                "project quality gate passes.",
            )

        evidence = self._load_approval_evidence(approval_evidence_path)
        if isinstance(evidence, str):
            return "\n".join(
                [
                    evidence,
                    "- Run project_signoff_report() before final release export.",
                    "- Store reviewer approval in a project-local JSON evidence file.",
                ]
            )
        evidence_path, evidence_payload = evidence
        approved_files_error = self._verify_approved_project_files(evidence_path, evidence_payload)
        if approved_files_error is not None:
            return "\n".join(
                [
                    approved_files_error,
                    "- Manufacturing export stopped before artifact generation.",
                    "- Obtain fresh human approval for the current project state.",
                ]
            )
        return evidence_path, evidence_payload

    def _load_approval_evidence(self, path_text: str) -> tuple[Path, dict[str, Any]] | str:
        if not path_text.strip():
            return _MISSING_APPROVAL_EVIDENCE
        try:
            path = self.resolve_project_path(path_text)
        except ValueError as exc:
            return f"Manufacturing evidence path is invalid: {exc}"
        if not path.exists() or not path.is_file():
            return f"Manufacturing evidence file does not exist: {path}"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"Manufacturing evidence must be readable JSON: {exc}"
        if not isinstance(payload, dict):
            return "Manufacturing evidence must be a JSON object."
        missing = [
            key
            for key in ("approved_by", "approved_at_utc", "approval_scope")
            if not str(payload.get(key) or "").strip()
        ]
        if missing:
            return "Manufacturing evidence is missing: " + ", ".join(missing)
        return path, dict(payload)

    def _verify_approved_project_files(
        self, evidence_path: Path, payload: dict[str, Any]
    ) -> str | None:
        """Revalidate file-level approval bindings at the export boundary."""
        bound_reference_approval = evidence_path.name == _REFERENCE_APPROVAL_FILENAME
        raw_files = payload.get("approved_project_files")
        expected_state = payload.get("project_state_digest")
        if bound_reference_approval and (raw_files is None or expected_state is None):
            return "Manufacturing reference approval requires bound project state evidence."
        if raw_files is None:
            return "Manufacturing approval requires bound project state evidence."

        parsed = _parse_approved_project_files(raw_files)
        if isinstance(parsed, str):
            return parsed

        current_files = self._current_approved_project_files()
        if isinstance(current_files, str):
            return current_files

        approved_paths = tuple(relative for relative, _digest in parsed)
        current_paths = tuple(relative for relative, _digest in current_files)
        if approved_paths != current_paths:
            return "Manufacturing evidence approved project state digest mismatch."
        if tuple(parsed) != current_files:
            return "Manufacturing evidence approved project file digest mismatch."

        return _verify_project_state_digest(expected_state, current_files)

    def _current_approved_project_files(self) -> tuple[tuple[str, str], ...] | str:
        try:
            root = self.resolve_project_path(".")
        except ValueError:
            return "Manufacturing evidence project root is invalid."
        if root.is_symlink() or not root.is_dir():
            return "Manufacturing evidence project root is invalid."
        files: list[Path] = []
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            relevant = (
                path.suffix in _APPROVED_PROJECT_SUFFIXES or relative in _APPROVED_PROJECT_METADATA
            )
            if not relevant:
                continue
            if path.is_symlink() or not path.is_file():
                return "Manufacturing evidence approved project file is invalid."
            files.append(path)
        return tuple(
            (path.relative_to(root).as_posix(), self._file_sha256(path))
            for path in sorted(files, key=lambda item: item.relative_to(root).as_posix())
        )

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


@dataclass(frozen=True)
class _PackageStep:
    kind: str
    export: VariantExport
    success: str
    progress: int | None = None
    message: str = ""
    unsupported: str = ""


@dataclass(frozen=True)
class ExportManufacturingPackageService(ManufacturingApprovalService):
    """Generate a gated manufacturing handoff without depending on MCP types."""

    ensure_output_dir: Callable[[], Path]
    export_gerber: VariantExport
    export_drill: VariantExport
    export_bom: VariantExport
    export_pick_and_place: VariantExport
    export_ipc2581: VariantExport
    export_odb: VariantExport

    async def export(
        self,
        *,
        variant: str = "",
        approval_evidence_path: str = "",
        evaluate_project_gate: GateEvaluator,
        render_gate_report: GateRenderer,
        report_progress: ProgressReporter,
    ) -> str:
        variant_name = variant.strip() or None
        await report_progress(5, 100, "Running full project quality gate...")
        outcomes = await anyio.to_thread.run_sync(evaluate_project_gate)
        evidence = self.authorize(
            outcomes=outcomes,
            render_gate_report=render_gate_report,
            approval_evidence_path=approval_evidence_path,
        )
        if isinstance(evidence, str):
            return evidence
        evidence_path, evidence_payload = evidence

        root = self.ensure_output_dir()
        lock = root / ".manufacturing-package-in-progress"
        try:
            lock.mkdir()
        except FileExistsError:
            return "Manufacturing package export blocked: an existing export lock is present."
        try:
            return await self._export_approved(
                root,
                variant_name,
                evidence_path,
                evidence_payload,
                outcomes,
                approval_evidence_path,
                render_gate_report,
                report_progress,
            )
        finally:
            lock.rmdir()

    @staticmethod
    def _existing_outputs(root: Path) -> bool:
        for name in ("bom.csv", "manufacturing_release_report.json"):
            target = root / name
            if target.exists() or target.is_symlink():
                return True
        for name in ("gerber", "pos", "ipc2581", "odb"):
            target = root / name
            if target.is_symlink() or (
                target.exists() and (not target.is_dir() or any(target.iterdir()))
            ):
                return True
        return False

    @staticmethod
    def _artifact_paths(root: Path, kind: str) -> list[Path]:
        if kind == "gerber":
            candidates = discover_gerber_output_files(root / "gerber")
        elif kind == "drill":
            candidates = discover_drill_output_files(root / "gerber")
        else:
            names = {
                "bom": [root / "bom.csv"],
                "pick": list((root / "pos").glob("*.csv")),
                "ipc": [root / "ipc2581" / "board.ipc2581"],
                "odb": [root / "odb" / "board.odb"],
            }
            candidates = names[kind]
        return [
            path
            for path in candidates
            if not path.is_symlink()
            and path.is_file()
            and path.stat().st_size > 0
            and path.resolve().is_relative_to(root.resolve())
        ]

    def _steps(self) -> tuple[_PackageStep, ...]:
        return (
            _PackageStep(
                "gerber", self.export_gerber, "Gerber export completed", 25, "Exporting Gerbers..."
            ),
            _PackageStep(
                "drill", self.export_drill, "Drill export completed", 45, "Exporting drill files..."
            ),
            _PackageStep("bom", self.export_bom, "BOM exported to", 65, "Exporting BOM..."),
            _PackageStep(
                "pick",
                self.export_pick_and_place,
                "Pick and place data exported to",
                85,
                "Exporting pick-and-place data...",
            ),
            _PackageStep(
                "ipc",
                self.export_ipc2581,
                "IPC-2581 exported to",
                unsupported="IPC-2581 export is not supported",
            ),
            _PackageStep(
                "odb",
                self.export_odb,
                "ODB++ exported to",
                unsupported="ODB++ export is not supported",
            ),
        )

    async def _run_package_step(
        self,
        root: Path,
        step: _PackageStep,
        variant_name: str | None,
        report_progress: ProgressReporter,
    ) -> tuple[str, list[Path]] | str | None:
        if self._artifact_paths(root, step.kind):
            return f"Manufacturing package export failed: existing {step.kind} output appeared."
        if step.progress is not None:
            await report_progress(step.progress, 100, step.message)
        result = await anyio.to_thread.run_sync(step.export, variant_name)
        if step.unsupported and result.startswith(step.unsupported):
            return None
        files = self._artifact_paths(root, step.kind)
        if (
            not result.startswith(step.success)
            or not files
            or (step.kind == "gerber" and all(path.suffix.lower() == ".gbrjob" for path in files))
        ):
            return (
                f"Manufacturing package export failed ({step.kind}): {result}\n"
                "No release report published. Archive incomplete outputs before retrying."
            )
        return result, files

    async def _export_approved(
        self,
        root: Path,
        variant_name: str | None,
        evidence_path: Path,
        evidence_payload: dict[str, Any],
        outcomes: list[Any],
        approval_evidence_path: str,
        render_gate_report: GateRenderer,
        report_progress: ProgressReporter,
    ) -> str:
        if self._existing_outputs(root):
            return (
                "Manufacturing package export blocked: existing manufacturing outputs. "
                "Archive them before retrying; no existing artifacts were changed."
            )
        results: list[str] = []
        paths: list[Path] = []
        for step in self._steps():
            completed = await self._run_package_step(root, step, variant_name, report_progress)
            if isinstance(completed, str):
                return completed
            if completed is not None:
                result, files = completed
                results.append(result)
                paths.extend(files)
        fresh = self.authorize(
            outcomes=outcomes,
            render_gate_report=render_gate_report,
            approval_evidence_path=approval_evidence_path,
        )
        if isinstance(fresh, str):
            return f"Manufacturing package export failed: {fresh}"
        if fresh != (evidence_path, evidence_payload):
            return "Manufacturing package export failed: approval changed during export."
        if self.ensure_output_dir() != root:
            return "Manufacturing package export failed: active output directory changed."
        report_target = root / "manufacturing_release_report.json"
        if report_target.exists() or report_target.is_symlink():
            return "Manufacturing package export blocked: existing release report appeared."
        artifacts = self._manufacturing_artifacts(root, paths)
        report_path = self._write_handoff_report(
            out_dir=root,
            variant_name=variant_name,
            evidence_path=evidence_path,
            evidence=evidence_payload,
            outcomes=outcomes,
            results=results,
            artifacts=artifacts,
        )
        results.append(
            "\n".join(
                [
                    "Manufacturing release evidence:",
                    f"- Approval evidence: {evidence_path}",
                    f"- Release report: {report_path}",
                    f"- Linked artifacts: {len(artifacts)}",
                    "- Human approval is recorded as evidence, not replaced by automation.",
                ]
            )
        )
        await report_progress(100, 100, "Manufacturing package complete.")
        return "\n\n".join(results)

    def _manufacturing_artifacts(self, root: Path, files: list[Path]) -> list[dict[str, Any]]:
        return [
            {
                "path": str(path),
                "relative_path": str(path.relative_to(root)),
                "size_bytes": path.stat().st_size,
                "sha256": self._file_sha256(path),
            }
            for path in sorted(set(files))
        ]

    def _write_handoff_report(
        self,
        *,
        out_dir: Path,
        variant_name: str | None,
        evidence_path: Path,
        evidence: dict[str, Any],
        outcomes: list[Any],
        results: list[str],
        artifacts: list[dict[str, Any]],
    ) -> Path:
        report_path = out_dir / "manufacturing_release_report.json"
        payload = {
            "schema_version": "manufacturing_release.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "variant": variant_name or "default",
            "approval_evidence_path": str(evidence_path),
            "approval_evidence": evidence,
            "quality_gate": [
                {
                    "name": item.name,
                    "status": item.status,
                    "summary": item.summary,
                    "details": item.details,
                }
                for item in outcomes
            ],
            "export_results": results,
            "artifacts": artifacts,
        }
        atomic_metadata_write(report_path, json.dumps(payload, indent=2, sort_keys=True))
        return report_path
