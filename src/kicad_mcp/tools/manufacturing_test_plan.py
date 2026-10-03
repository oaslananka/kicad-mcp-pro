"""Thin FastMCP adapter for manufacturing bring-up test-plan generation."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..manufacturing.test_plan import DesignIntentLike, ManufacturingTestPlanService
from ..project.design_spec import load_design_intent
from .metadata import headless_compatible


@dataclass(frozen=True)
class ManufacturingTestPlanDependencies:
    service: ManufacturingTestPlanService
    load_design_intent: Callable[[], DesignIntentLike]


def _default_dependencies() -> ManufacturingTestPlanDependencies:
    return ManufacturingTestPlanDependencies(
        service=ManufacturingTestPlanService(
            resolve_output_path=lambda path: get_config().resolve_within_project(path),
        ),
        load_design_intent=load_design_intent,
    )


def register(
    mcp: FastMCP,
    dependencies: ManufacturingTestPlanDependencies | None = None,
) -> None:
    """Register the manufacturing bring-up test-plan tool."""
    deps = dependencies or _default_dependencies()

    @mcp.tool()
    @headless_compatible
    def mfg_generate_test_plan(output_path: str = "", confirm_overwrite: bool = False) -> str:
        """Generate a bring-up test plan from the project design intent.

        Produces a structured markdown checklist covering:
        - Power-on sequence and current limit checks for each power rail.
        - Protocol loopback / link-up checks for each interface.
        - Critical-net continuity probes.
        - Visual inspection items.

        Args:
            output_path: Optional relative path for saving the plan (e.g.
                ``"test_plan.md"``). If omitted, returns the plan as text only.
            confirm_overwrite: If True, allow overwriting an existing output file.

        Returns:
            Bring-up test plan in markdown format.
        """
        return deps.service.create(
            deps.load_design_intent(),
            output_path=output_path,
            confirm_overwrite=confirm_overwrite,
        )
