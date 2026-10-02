"""Manufacturing release-evidence domain service and shared release-file helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CliRunner = Callable[..., tuple[int, str, str]]


@dataclass(frozen=True)
class ReleaseEvidenceContext:
    """Runtime inputs needed to evaluate manufacturing release evidence."""

    output_dir: Path
    project_dir: Path | None
    project_file: Path | None
    pcb_file: Path | None
    sch_file: Path | None
    kicad_cli: Path
    kicad_cli_version: str | None
    kicad_mcp_version: str


def sha256_file(path: Path) -> str:
    """Return a stable SHA256 digest for ``path`` or ``unavailable`` on I/O failure."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return "unavailable"
    return digest.hexdigest()


def find_release_files(output_dir: Path) -> list[Path]:
    """Return manufacturing release files using the repository's reviewed patterns."""
    patterns = ["*.gbr", "*.drl", "*.csv", "*.ipc", "*.step", "*.xml", "*.pdf"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(output_dir.glob(pattern))
    return sorted(set(files))


def _now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ReleaseEvidenceService:
    """Evaluate manufacturing release gates independently of FastMCP transport."""

    run_cli: CliRunner
    now_utc: Callable[[], datetime] = _now_utc

    def create_evidence(
        self,
        *,
        context: ReleaseEvidenceContext,
        output_path: str = "",
        product_domain: str = "selv",
        voltage_v: float = 0.0,
        waive_missing_artifacts: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Evaluate release gates and optionally write ``release_evidence.json``.

        ``output_path`` is intentionally retained but ignored to preserve the existing
        public MCP behavior during this structural extraction.
        """
        _ = output_path
        out_dir = context.output_dir

        is_hv = product_domain == "hazardous_mains" or voltage_v > 60.0
        effective_domain = "hazardous_mains" if is_hv else "selv"

        gates: list[dict[str, Any]] = []
        blocking: list[str] = []

        artifact_patterns: dict[str, str] = {
            "gerber": "*.gbr",
            "drill": "*.drl",
            "bom": "*.csv",
            "pick_and_place": "*.csv",
        }
        missing_artifacts: list[str] = []
        found_artifacts: list[str] = []
        if out_dir.exists():
            for artifact_type, pattern in artifact_patterns.items():
                matches = list(out_dir.glob(pattern))
                if matches:
                    found_artifacts.append(artifact_type)
                else:
                    missing_artifacts.append(artifact_type)
        else:
            missing_artifacts = list(artifact_patterns.keys())

        artifact_passed = not missing_artifacts or waive_missing_artifacts
        gates.append(
            {
                "gate": "artifact_coverage",
                "passed": artifact_passed,
                "found": found_artifacts,
                "missing": missing_artifacts,
                "waived": waive_missing_artifacts and bool(missing_artifacts),
            }
        )
        if not artifact_passed:
            blocking.append(
                f"Missing required artifacts: {', '.join(missing_artifacts)}. "
                "Run export_manufacturing_package() first."
            )

        drc_passed = False
        drc_violations = -1
        drc_unconnected = -1
        drc_error: str | None = None
        try:
            if context.pcb_file and context.pcb_file.exists():
                with tempfile.NamedTemporaryFile(
                    suffix=".json", delete=False, dir=context.pcb_file.parent
                ) as tmp:
                    tmp_path = tmp.name
                try:
                    code, stdout, stderr = self.run_cli(
                        "pcb",
                        "drc",
                        "--output",
                        tmp_path,
                        "--format",
                        "json",
                        "--schematic-parity",
                        str(context.pcb_file),
                    )
                    if code == 0 and os.path.exists(tmp_path):
                        report = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
                        violations = report.get("violations", [])
                        unconnected = report.get("unconnected_items", [])
                        drc_violations = len(violations) if isinstance(violations, list) else 0
                        drc_unconnected = len(unconnected) if isinstance(unconnected, list) else 0
                        drc_passed = drc_violations == 0 and drc_unconnected == 0
                    else:
                        drc_error = stderr or stdout or f"DRC exited with code {code}"
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            else:
                drc_error = "No PCB file configured."
        except Exception as exc:  # preserve fail-closed release evidence behavior
            drc_error = str(exc)

        gates.append(
            {
                "gate": "drc",
                "passed": drc_passed,
                "violations": drc_violations,
                "unconnected_items": drc_unconnected,
                "error": drc_error,
            }
        )
        if not drc_passed:
            if drc_error:
                blocking.append(f"DRC could not run: {drc_error}")
            else:
                blocking.append(
                    f"DRC failed: {drc_violations} violation(s),"
                    f" {drc_unconnected} unconnected item(s)."
                )

        erc_passed = False
        erc_violations = -1
        erc_error: str | None = None
        try:
            if context.sch_file and context.sch_file.exists():
                with tempfile.NamedTemporaryFile(
                    suffix=".json", delete=False, dir=context.sch_file.parent
                ) as tmp:
                    tmp_path = tmp.name
                try:
                    code, stdout, stderr = self.run_cli(
                        "sch",
                        "erc",
                        "--output",
                        tmp_path,
                        "--format",
                        "json",
                        str(context.sch_file),
                    )
                    if code == 0 and os.path.exists(tmp_path):
                        report = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
                        violations = report.get("violations", [])
                        erc_violations = len(violations) if isinstance(violations, list) else 0
                        erc_passed = erc_violations == 0
                    else:
                        erc_error = stderr or stdout or f"ERC exited with code {code}"
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            else:
                erc_error = "No schematic file configured."
        except Exception as exc:  # preserve fail-closed release evidence behavior
            erc_error = str(exc)

        gates.append(
            {
                "gate": "erc",
                "passed": erc_passed,
                "violations": erc_violations,
                "error": erc_error,
            }
        )
        if not erc_passed:
            if erc_error:
                blocking.append(f"ERC could not run: {erc_error}")
            else:
                blocking.append(f"ERC failed: {erc_violations} violation(s).")

        hv_gate_applicable = is_hv
        hv_gate_passed = True
        hv_gate_detail = "Not applicable (SELV domain)."
        if hv_gate_applicable:
            dru_files = list(context.project_dir.glob("*.kicad_dru")) if context.project_dir else []
            hv_dru: Path | None = None
            for dru in dru_files:
                text = dru.read_text(encoding="utf-8", errors="ignore")
                if "creepage" in text.lower() or "clearance" in text.lower():
                    hv_dru = dru
                    break
            if hv_dru:
                hv_gate_detail = f"HV design rules found in {hv_dru.name}."
            else:
                hv_gate_passed = False
                hv_gate_detail = (
                    f"No .kicad_dru with creepage/clearance rules found for "
                    f"{voltage_v:.0f} V {effective_domain} design. "
                    "Run generate_board_constraints() to create HV safety rules."
                )
        gates.append(
            {
                "gate": "hv_safety",
                "applicable": hv_gate_applicable,
                "passed": hv_gate_passed,
                "detail": hv_gate_detail,
                "voltage_v": voltage_v,
                "domain": effective_domain,
            }
        )
        if hv_gate_applicable and not hv_gate_passed:
            blocking.append(hv_gate_detail)

        verdict = "release_approved" if not blocking else "release_blocked"
        release_files = find_release_files(out_dir) if out_dir.exists() else []
        file_hashes: list[dict[str, str]] = sorted(
            (
                {
                    "filename": path.name,
                    "sha256": sha256_file(path),
                    "size_bytes": str(path.stat().st_size),
                }
                for path in release_files
            ),
            key=lambda entry: entry["filename"],
        )
        source_hashes = {
            label: sha256_file(path)
            for label, path in (
                ("project", context.project_file),
                ("pcb", context.pcb_file),
                ("schematic", context.sch_file),
            )
            if path is not None and path.exists()
        }
        provenance: dict[str, Any] = {
            "kicad_mcp_version": context.kicad_mcp_version,
            "kicad_cli": str(context.kicad_cli),
            "kicad_cli_version": context.kicad_cli_version,
            "product_domain": effective_domain,
            "voltage_v": voltage_v,
            "source_hashes": source_hashes,
        }
        content_basis = json.dumps(
            {"files": file_hashes, "provenance": provenance, "gates": gates}, sort_keys=True
        )
        content_hash = hashlib.sha256(content_basis.encode()).hexdigest()

        evidence: dict[str, Any] = {
            "verdict": verdict,
            "generated_utc": self.now_utc().isoformat(),
            "content_hash": content_hash,
            "product_domain": effective_domain,
            "voltage_v": voltage_v,
            "gates": gates,
            "blocking_reasons": blocking,
            "provenance": provenance,
            "file_count": len(release_files),
            "files": file_hashes,
        }
        if dry_run:
            return json.dumps({**evidence, "dry_run": True, "evidence_path": None}, indent=2)

        out_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = out_dir / "release_evidence.json"
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return json.dumps({**evidence, "evidence_path": str(evidence_path)}, indent=2)
