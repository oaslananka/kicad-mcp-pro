"""Thin FastMCP adapter for manufacturing release-evidence generation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver import MCPServer as FastMCP

from .. import __version__
from ..config import get_config
from ..discovery import get_cli_capabilities
from ..manufacturing.release_evidence import (
    DrcGateResult,
    ErcGateResult,
    ManufacturingReleaseEvidenceService,
    ReleaseEvidenceContext,
)
from .metadata import headless_compatible

ContextProvider = Callable[[], ReleaseEvidenceContext]


@dataclass(frozen=True)
class ManufacturingReleaseEvidenceDependencies:
    service: ManufacturingReleaseEvidenceService
    context_provider: ContextProvider


def _run_drc(pcb_file: Path | None) -> DrcGateResult:
    if pcb_file is None or not pcb_file.exists():
        return DrcGateResult(False, -1, -1, "No PCB file configured.")
    try:
        from .export_support import _run_cli

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, dir=pcb_file.parent) as tmp:
            tmp_path = tmp.name
        try:
            code, stdout, stderr = _run_cli(
                "pcb",
                "drc",
                "--output",
                tmp_path,
                "--format",
                "json",
                "--schematic-parity",
                str(pcb_file),
            )
            if code != 0 or not os.path.exists(tmp_path):
                return DrcGateResult(
                    False, -1, -1, stderr or stdout or f"DRC exited with code {code}"
                )
            report = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
            violations = report.get("violations", [])
            unconnected = report.get("unconnected_items", [])
            violation_count = len(violations) if isinstance(violations, list) else 0
            unconnected_count = len(unconnected) if isinstance(unconnected, list) else 0
            return DrcGateResult(
                violation_count == 0 and unconnected_count == 0,
                violation_count,
                unconnected_count,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as exc:
        return DrcGateResult(False, -1, -1, str(exc))


def _run_erc(sch_file: Path | None) -> ErcGateResult:
    if sch_file is None or not sch_file.exists():
        return ErcGateResult(False, -1, "No schematic file configured.")
    try:
        from .export_support import _run_cli

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, dir=sch_file.parent) as tmp:
            tmp_path = tmp.name
        try:
            code, stdout, stderr = _run_cli(
                "sch", "erc", "--output", tmp_path, "--format", "json", str(sch_file)
            )
            if code != 0 or not os.path.exists(tmp_path):
                return ErcGateResult(False, -1, stderr or stdout or f"ERC exited with code {code}")
            report = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
            violations = report.get("violations", [])
            violation_count = len(violations) if isinstance(violations, list) else 0
            return ErcGateResult(violation_count == 0, violation_count)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as exc:
        return ErcGateResult(False, -1, str(exc))


def _context() -> ReleaseEvidenceContext:
    cfg = get_config()
    out_dir = cfg.output_dir or (cfg.project_dir / "output")  # type: ignore[operator]
    caps = get_cli_capabilities(cfg.kicad_cli)
    return ReleaseEvidenceContext(
        output_dir=out_dir,
        project_dir=cfg.project_dir,
        project_file=cfg.project_file,
        pcb_file=cfg.pcb_file,
        sch_file=cfg.sch_file,
        kicad_cli=cfg.kicad_cli,
        kicad_cli_version=caps.version,
        kicad_mcp_version=__version__,
    )


def _default_dependencies() -> ManufacturingReleaseEvidenceDependencies:
    return ManufacturingReleaseEvidenceDependencies(
        service=ManufacturingReleaseEvidenceService(run_drc=_run_drc, run_erc=_run_erc),
        context_provider=_context,
    )


def register(
    mcp: FastMCP,
    dependencies: ManufacturingReleaseEvidenceDependencies | None = None,
) -> None:
    """Register manufacturing release-evidence generation."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @headless_compatible
    def mfg_create_release_evidence(
        output_path: str = "",
        product_domain: str = "selv",
        voltage_v: float = 0.0,
        waive_missing_artifacts: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Generate a machine-readable manufacturing release evidence bundle.

        Runs compliance gates, checks required artifacts, and produces a
        signed evidence JSON with a ``release_approved`` / ``release_blocked`` verdict.

        Gates evaluated:
        - **Artifact coverage**: Gerber, drill, BOM, and pick-and-place files must exist
          in the output directory.
        - **DRC gate**: PCB design rule violations must be zero.
        - **ERC gate**: Schematic electrical rule violations must be zero.
        - **HV safety gate**: If ``voltage_v`` > 60 V or ``product_domain`` is
          ``hazardous_mains``, a ``*.kicad_dru`` file with HV creepage rules must exist.

        Args:
            output_path: Output directory for the evidence bundle (default: project output/).
            product_domain: ``"selv"`` (Safety Extra-Low Voltage, ≤ 60 V DC) or
                ``"hazardous_mains"`` (> 60 V DC, requires HV safety gate).
            voltage_v: Working voltage in volts; used to auto-select safety domain.
            waive_missing_artifacts: If True, missing artifact types do not block release.
            dry_run: Evaluate gates without writing the evidence file.

        Returns:
            JSON with ``verdict``, ``gates``, ``blocking_reasons``, and ``evidence_path``.
        """
        return deps.service.create(
            deps.context_provider(),
            output_path=output_path,
            product_domain=product_domain,
            voltage_v=voltage_v,
            waive_missing_artifacts=waive_missing_artifacts,
            dry_run=dry_run,
        )
