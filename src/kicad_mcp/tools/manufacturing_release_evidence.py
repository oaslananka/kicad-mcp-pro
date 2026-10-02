"""Thin FastMCP adapter for manufacturing release-evidence generation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from .. import __version__
from ..config import get_config
from ..discovery import get_cli_capabilities
from ..manufacturing.release_evidence import ReleaseEvidenceContext, ReleaseEvidenceService
from .metadata import headless_compatible


@dataclass(frozen=True)
class ManufacturingReleaseEvidenceDependencies:
    service: ReleaseEvidenceService
    context_provider: Callable[[], ReleaseEvidenceContext]


def _run_cli(*args: str) -> tuple[int, str, str]:
    from . import export_support

    return export_support._run_cli(*args)


def _release_context() -> ReleaseEvidenceContext:
    cfg = get_config()
    output_dir = cfg.output_dir or (cfg.project_dir / "output")  # type: ignore[operator]
    caps = get_cli_capabilities(cfg.kicad_cli)
    return ReleaseEvidenceContext(
        output_dir=output_dir,
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
        service=ReleaseEvidenceService(run_cli=_run_cli),
        context_provider=_release_context,
    )


def register(
    mcp: FastMCP,
    dependencies: ManufacturingReleaseEvidenceDependencies | None = None,
) -> None:
    """Register the manufacturing release-evidence tool."""
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
        return deps.service.create_evidence(
            context=deps.context_provider(),
            output_path=output_path,
            product_domain=product_domain,
            voltage_v=voltage_v,
            waive_missing_artifacts=waive_missing_artifacts,
            dry_run=dry_run,
        )
