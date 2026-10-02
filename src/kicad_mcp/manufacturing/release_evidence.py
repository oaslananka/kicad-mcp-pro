"""FastMCP-independent manufacturing release-evidence orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


class CliCapabilities(Protocol):
    @property
    def version(self) -> str | None: ...


@dataclass(frozen=True)
class ReleaseEvidenceContext:
    output_dir: Path
    project_dir: Path | None
    project_file: Path | None
    pcb_file: Path | None
    sch_file: Path | None
    kicad_cli: Path


CliRunner = Callable[..., tuple[int, str, str]]
ContextProvider = Callable[[], ReleaseEvidenceContext]
CapabilitiesProvider = Callable[[Path], CliCapabilities]
Clock = Callable[[], datetime]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return "unavailable"
    return digest.hexdigest()


def _find_release_files(output_dir: Path) -> list[Path]:
    patterns = ["*.gbr", "*.drl", "*.csv", "*.ipc", "*.step", "*.xml", "*.pdf"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(output_dir.glob(pattern))
    return sorted(set(files))


@dataclass(frozen=True)
class ManufacturingReleaseEvidenceService:
    """Evaluate manufacturing release gates and emit reproducible evidence metadata."""

    get_context: ContextProvider
    run_cli: CliRunner
    get_cli_capabilities: CapabilitiesProvider
    package_version: str
    now: Clock = lambda: datetime.now(UTC)

    def create(
        self,
        output_path: str = "",
        product_domain: str = "selv",
        voltage_v: float = 0.0,
        waive_missing_artifacts: bool = False,
        dry_run: bool = False,
    ) -> str:
        # Preserve the existing public contract: output_path is accepted but the
        # configured manufacturing output directory remains authoritative.
        _ = output_path
        ctx = self.get_context()
        out_dir = ctx.output_dir

        is_hv = product_domain == "hazardous_mains" or voltage_v > 60.0
        effective_domain = "hazardous_mains" if is_hv else "selv"

        gates: list[dict[str, object]] = []
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
            if ctx.pcb_file and ctx.pcb_file.exists():
                with tempfile.NamedTemporaryFile(
                    suffix=".json", delete=False, dir=ctx.pcb_file.parent
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
                        str(ctx.pcb_file),
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
        except Exception as exc:
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
            if ctx.sch_file and ctx.sch_file.exists():
                with tempfile.NamedTemporaryFile(
                    suffix=".json", delete=False, dir=ctx.sch_file.parent
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
                        str(ctx.sch_file),
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
        except Exception as exc:
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
            dru_files = list(ctx.project_dir.glob("*.kicad_dru")) if ctx.project_dir else []
            hv_dru = None
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
        release_files = _find_release_files(out_dir) if out_dir.exists() else []
        file_hashes: list[dict[str, str]] = sorted(
            (
                {
                    "filename": path.name,
                    "sha256": _sha256_file(path),
                    "size_bytes": str(path.stat().st_size),
                }
                for path in release_files
            ),
            key=lambda entry: entry["filename"],
        )

        caps = self.get_cli_capabilities(ctx.kicad_cli)
        source_hashes = {
            label: _sha256_file(path)
            for label, path in (
                ("project", ctx.project_file),
                ("pcb", ctx.pcb_file),
                ("schematic", ctx.sch_file),
            )
            if path is not None and path.exists()
        }
        provenance: dict[str, object] = {
            "kicad_mcp_version": self.package_version,
            "kicad_cli": str(ctx.kicad_cli),
            "kicad_cli_version": caps.version,
            "product_domain": effective_domain,
            "voltage_v": voltage_v,
            "source_hashes": source_hashes,
        }

        content_basis = json.dumps(
            {"files": file_hashes, "provenance": provenance, "gates": gates},
            sort_keys=True,
        )
        content_hash = hashlib.sha256(content_basis.encode()).hexdigest()
        evidence: dict[str, object] = {
            "verdict": verdict,
            "generated_utc": self.now().isoformat(),
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
