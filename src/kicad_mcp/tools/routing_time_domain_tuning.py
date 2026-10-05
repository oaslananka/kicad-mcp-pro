"""Thin FastMCP adapter for time-domain routing tuning."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..routing.time_domain_tuning import (
    PatternTrackLengthProvider,
    RoutingTimeDomainTuningService,
    RuleWriter,
    StackupContextProvider,
)
from .metadata import headless_compatible


@dataclass(frozen=True)
class RoutingTimeDomainTuningDependencies:
    service: RoutingTimeDomainTuningService


def dependencies(
    *,
    current_track_length_for_pattern_mm: PatternTrackLengthProvider,
    stackup_context_for_layer: StackupContextProvider,
    write_rule: RuleWriter,
) -> RoutingTimeDomainTuningDependencies:
    return RoutingTimeDomainTuningDependencies(
        service=RoutingTimeDomainTuningService(
            get_project_dir=lambda: get_config().project_dir,
            current_track_length_for_pattern_mm=current_track_length_for_pattern_mm,
            stackup_context_for_layer=stackup_context_for_layer,
            write_rule=write_rule,
        )
    )


def register(
    mcp: FastMCP,
    dependencies: RoutingTimeDomainTuningDependencies,
) -> None:
    """Register time-domain routing-tuning tools."""
    deps = dependencies

    @mcp.tool()
    @headless_compatible
    def route_tune_time_domain(
        net_or_group: str,
        target_delay_ps: float,
        tolerance_ps: float = 10.0,
        layer: str | None = None,
    ) -> str:
        """Create a time-domain tuning rule for one concrete net; wildcards are rejected."""
        return deps.service.tune(
            net_or_group,
            target_delay_ps,
            tolerance_ps,
            layer,
        )
