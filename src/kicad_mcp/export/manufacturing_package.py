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

GateEvaluator = Callable[[], list[Any]]
GateRenderer = Callable[[list[Any], str], str]
ProgressReporter = Callable[[int, int, str], Awaitable[None]]
VariantExport = Callable[[str | None], str]

_MISSING_APPROVAL_EVIDENCE = (
    "Manufacturing package export is hard-blocked until approval_evidence_path is supplied."
)
_APPROVED_PROJECT_SUFFIXES = frozenset({".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_dru"})
_APPROVED_PROJECT_SPEC = ".kicad-mcp/project_spec.json"
_REFERENCE_APPROVAL_FILENAME = "reference-manufacturing-approval.json"
_INVALID_APPROVED_PROJECT_FILES = "Manufacturing evidence approved project files are invalid."


@dataclass(frozen=True)
class ExportManufacturingPackageService:
    """Generate a gated manufacturing handoff without depending on MCP types."""

    resolve_project_path: Callable[[str], Path]
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

        await report_progress(25, 100, "Exporting Gerbers...")
        results = [
            await anyio.to_thread.run_sync(lambda: self.export_gerber(variant_name)),
        ]
        await report_progress(45, 100, "Exporting drill files...")
        results.append(await anyio.to_thread.run_sync(lambda: self.export_drill(variant_name)))
        await report_progress(65, 100, "Exporting BOM...")
        results.append(await anyio.to_thread.run_sync(lambda: self.export_bom(variant_name)))
        await report_progress(85, 100, "Exporting pick-and-place data...")
        results.append(
            await anyio.to_thread.run_sync(lambda: self.export_pick_and_place(variant_name))
        )

        ipc_result = await anyio.to_thread.run_sync(lambda: self.export_ipc2581(variant_name))
        if not ipc_result.startswith("IPC-2581 export is not supported"):
            results.append(ipc_result)
        odb_result = await anyio.to_thread.run_sync(lambda: self.export_odb(variant_name))
        if not odb_result.startswith("ODB++ export is not supported"):
            results.append(odb_result)

        report_path = self._write_handoff_report(
            variant_name=variant_name,
            evidence_path=evidence_path,
            evidence=evidence_payload,
            outcomes=outcomes,
            results=results,
        )
        artifact_count = len(self._manufacturing_artifacts())
        results.append(
            "\n".join(
                [
                    "Manufacturing release evidence:",
                    f"- Approval evidence: {evidence_path}",
                    f"- Release report: {report_path}",
                    f"- Linked artifacts: {artifact_count}",
                    "- Human approval is recorded as evidence, not replaced by automation.",
                ]
            )
        )
        await report_progress(100, 100, "Manufacturing package complete.")
        return "\n\n".join(results)

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
        """Revalidate reference file-level approval bindings at the export boundary."""
        bound_reference_approval = evidence_path.name == _REFERENCE_APPROVAL_FILENAME
        raw_files = payload.get("approved_project_files")
        expected_state = payload.get("project_state_digest")
        if bound_reference_approval and (raw_files is None or expected_state is None):
            return "Manufacturing reference approval requires bound project state evidence."
        if raw_files is None:
            return None
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

        current_files = self._current_approved_project_files()
        if isinstance(current_files, str):
            return current_files
        approved_paths = tuple(relative for relative, _digest in approved_files)
        current_paths = tuple(relative for relative, _digest in current_files)
        if approved_paths != current_paths:
            return "Manufacturing evidence approved project state digest mismatch."
        if tuple(approved_files) != current_files:
            return "Manufacturing evidence approved project file digest mismatch."

        if expected_state is not None:
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
                path.suffix in _APPROVED_PROJECT_SUFFIXES or relative == _APPROVED_PROJECT_SPEC
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

    def _manufacturing_artifacts(self) -> list[dict[str, Any]]:
        root = self.ensure_output_dir()
        files: list[Path] = []
        for subdir in (root, root / "gerber", root / "pos", root / "ipc2581", root / "odb"):
            if subdir.exists():
                files.extend(path for path in subdir.rglob("*") if path.is_file())
        records = []
        for path in sorted(set(files)):
            relative = str(path.relative_to(root)) if path.is_relative_to(root) else path.name
            records.append(
                {
                    "path": str(path),
                    "relative_path": relative,
                    "size_bytes": path.stat().st_size,
                    "sha256": self._file_sha256(path),
                }
            )
        return records

    def _write_handoff_report(
        self,
        *,
        variant_name: str | None,
        evidence_path: Path,
        evidence: dict[str, Any],
        outcomes: list[Any],
        results: list[str],
    ) -> Path:
        out_dir = self.ensure_output_dir()
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
            "artifacts": self._manufacturing_artifacts(),
        }
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return report_path
