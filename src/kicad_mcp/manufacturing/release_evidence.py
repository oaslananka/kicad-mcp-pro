"""FastMCP-independent manufacturing release-evidence orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class DrcGateResult:
    passed: bool
    violations: int
    unconnected_items: int
    error: str | None = None


@dataclass(frozen=True)
class ErcGateResult:
    passed: bool
    violations: int
    error: str | None = None


@dataclass(frozen=True)
class ReleaseEvidenceContext:
    output_dir: Path
    project_dir: Path | None
    project_file: Path | None
    pcb_file: Path | None
    sch_file: Path | None
    kicad_cli: Path
    kicad_cli_version: str | None
    kicad_mcp_version: str


DrcRunner = Callable[[Path | None], DrcGateResult]
ErcRunner = Callable[[Path | None], ErcGateResult]
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
    """Evaluate manufacturing release gates and render deterministic evidence."""

    run_drc: DrcRunner
    run_erc: ErcRunner
    now: Clock = lambda: datetime.now(UTC)

    def create(
        self,
        context: ReleaseEvidenceContext,
        *,
        output_path: str = "",
        product_domain: str = "selv",
        voltage_v: float = 0.0,
        waive_missing_artifacts: bool = False,
        dry_run: bool = False,
    ) -> str:
        # Preserved public argument: existing implementation does not use output_path.
        _ = output_path
        out_dir = context.output_dir
        is_hv = product_domain == "hazardous_mains" or voltage_v > 60.0
        effective_domain = "hazardous_mains" if is_hv else "selv"
        gates: list[dict[str, object]] = []
        blocking: list[str] = []

        artifact_patterns = {
            "gerber": "*.gbr",
            "drill": "*.drl",
            "bom": "*.csv",
            "pick_and_place": "*.csv",
        }
        missing_artifacts: list[str] = []
        found_artifacts: list[str] = []
        if out_dir.exists():
            for artifact_type, pattern in artifact_patterns.items():
                if list(out_dir.glob(pattern)):
                    found_artifacts.append(artifact_type)
                else:
                    missing_artifacts.append(artifact_type)
        else:
            missing_artifacts = list(artifact_patterns)

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

        drc = self.run_drc(context.pcb_file)
        gates.append(
            {
                "gate": "drc",
                "passed": drc.passed,
                "violations": drc.violations,
                "unconnected_items": drc.unconnected_items,
                "error": drc.error,
            }
        )
        if not drc.passed:
            if drc.error:
                blocking.append(f"DRC could not run: {drc.error}")
            else:
                blocking.append(
                    f"DRC failed: {drc.violations} violation(s),"
                    f" {drc.unconnected_items} unconnected item(s)."
                )

        erc = self.run_erc(context.sch_file)
        gates.append(
            {
                "gate": "erc",
                "passed": erc.passed,
                "violations": erc.violations,
                "error": erc.error,
            }
        )
        if not erc.passed:
            if erc.error:
                blocking.append(f"ERC could not run: {erc.error}")
            else:
                blocking.append(f"ERC failed: {erc.violations} violation(s).")

        hv_gate_passed = True
        hv_gate_detail = "Not applicable (SELV domain)."
        if is_hv:
            dru_files = list(context.project_dir.glob("*.kicad_dru")) if context.project_dir else []
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
                "applicable": is_hv,
                "passed": hv_gate_passed,
                "detail": hv_gate_detail,
                "voltage_v": voltage_v,
                "domain": effective_domain,
            }
        )
        if is_hv and not hv_gate_passed:
            blocking.append(hv_gate_detail)

        verdict = "release_approved" if not blocking else "release_blocked"
        release_files = _find_release_files(out_dir) if out_dir.exists() else []
        file_hashes = sorted(
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
        source_hashes = {
            label: _sha256_file(path)
            for label, path in (
                ("project", context.project_file),
                ("pcb", context.pcb_file),
                ("schematic", context.sch_file),
            )
            if path is not None and path.exists()
        }
        provenance: dict[str, object] = {
            "kicad_mcp_version": context.kicad_mcp_version,
            "kicad_cli": str(context.kicad_cli),
            "kicad_cli_version": context.kicad_cli_version,
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
