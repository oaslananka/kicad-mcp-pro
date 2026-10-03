"""Thin FastMCP adapter for manufacturing release-manifest generation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from .. import __version__
from ..config import get_config
from ..discovery import get_cli_capabilities
from ..manufacturing.release_manifest import (
    DesignIntentLike,
    ReleaseManifestContext,
    ReleaseManifestPrerequisiteError,
    ReleaseManifestService,
)
from ..project.design_spec import load_design_intent
from .metadata import headless_compatible


@dataclass(frozen=True)
class ManufacturingReleaseManifestDependencies:
    service: ReleaseManifestService
    intent_provider: Callable[[], DesignIntentLike]
    context_provider: Callable[[], ReleaseManifestContext]


def _release_context() -> ReleaseManifestContext:
    cfg = get_config()
    output_dir = cfg.output_dir or (cfg.project_dir / "output")  # type: ignore[operator]
    caps = get_cli_capabilities(cfg.kicad_cli)
    return ReleaseManifestContext(
        output_dir=output_dir,
        project_file=cfg.project_file,
        pcb_file=cfg.pcb_file,
        sch_file=cfg.sch_file,
        kicad_cli=cfg.kicad_cli,
        kicad_cli_version=caps.version,
        kicad_mcp_version=__version__,
    )


def _default_dependencies() -> ManufacturingReleaseManifestDependencies:
    return ManufacturingReleaseManifestDependencies(
        service=ReleaseManifestService(),
        intent_provider=load_design_intent,
        context_provider=_release_context,
    )


def register(
    mcp: FastMCP,
    dependencies: ManufacturingReleaseManifestDependencies | None = None,
) -> None:
    """Register the manufacturing release-manifest tool."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @headless_compatible
    def mfg_generate_release_manifest(output_path: str = "") -> str:
        """Generate a SHA256-signed release manifest for the manufacturing package.

        Collects all files in the output directory, computes SHA256 hashes, and
        records tool versions, intent hash, and gate status into a ``manifest.json``
        and ``MANIFEST.txt``.

        Args:
            output_path: Subdirectory inside the project (defaults to ``output/``).

        Returns:
            Confirmation with manifest path and file count.
        """
        try:
            return deps.service.create_manifest(
                intent=deps.intent_provider(),
                context=deps.context_provider(),
                output_path=output_path,
            )
        except ReleaseManifestPrerequisiteError as exc:
            return str(exc)
