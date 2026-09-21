"""FastMCP adapter for project design spec management tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from ..project.design_spec import (
    ProjectImportDesignSpecPayload,
    ProjectSpecPayload,
    ProjectSpecValidationPayload,
)
from ..utils.cache import ttl_cache
from .metadata import headless_compatible


class ProjectDesignSpecServiceProtocol(Protocol):
    def set_design_intent(
        self,
        connector_refs: list[str] | None = None,
        critical_nets: list[str] | None = None,
        power_tree_refs: list[str] | None = None,
        analog_refs: list[str] | None = None,
        digital_refs: list[str] | None = None,
        sensor_cluster_refs: list[str] | None = None,
        required_sheets: list[str] | None = None,
        optional_sheets: list[str] | None = None,
        manufacturer: str | None = None,
        manufacturer_tier: str | None = None,
        functional_spacing_mm: float | None = None,
        thermal_hotspots: list[str] | None = None,
        critical_frequencies_mhz: list[float] | None = None,
        decoupling_pairs: list[dict[str, Any]] | None = None,
        rf_keepout_regions: list[dict[str, Any]] | None = None,
        power_rails: list[dict[str, Any]] | None = None,
        interfaces: list[dict[str, Any]] | None = None,
        mechanical: dict[str, Any] | None = None,
        compliance: list[dict[str, Any]] | None = None,
        cost: dict[str, Any] | None = None,
        thermal: dict[str, Any] | None = None,
    ) -> str: ...

    def import_design_spec(
        self,
        path: str | None = None,
        markdown: str | None = None,
        strict: bool = True,
        dry_run: bool = True,
    ) -> ProjectImportDesignSpecPayload: ...

    def get_design_intent(self) -> str: ...

    def get_design_spec(self) -> ProjectSpecPayload: ...

    def infer_design_spec(self) -> ProjectSpecPayload: ...

    def validate_design_spec(self) -> ProjectSpecValidationPayload: ...

    def generate_design_prompt(
        self,
        circuit_description: str = "",
        target_fab: str = "",
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ProjectDesignSpecDependencies:
    service: ProjectDesignSpecServiceProtocol


def register(mcp: FastMCP, deps: ProjectDesignSpecDependencies) -> None:
    """Register project design spec management tools at their legacy public position."""

    @mcp.tool()
    @headless_compatible
    def project_set_design_intent(
        connector_refs: list[str] | None = None,
        critical_nets: list[str] | None = None,
        power_tree_refs: list[str] | None = None,
        analog_refs: list[str] | None = None,
        digital_refs: list[str] | None = None,
        sensor_cluster_refs: list[str] | None = None,
        required_sheets: list[str] | None = None,
        optional_sheets: list[str] | None = None,
        manufacturer: str | None = None,
        manufacturer_tier: str | None = None,
        functional_spacing_mm: float | None = None,
        thermal_hotspots: list[str] | None = None,
        critical_frequencies_mhz: list[float] | None = None,
        decoupling_pairs: list[dict[str, Any]] | None = None,
        rf_keepout_regions: list[dict[str, Any]] | None = None,
        power_rails: list[dict[str, Any]] | None = None,
        interfaces: list[dict[str, Any]] | None = None,
        mechanical: dict[str, Any] | None = None,
        compliance: list[dict[str, Any]] | None = None,
        cost: dict[str, Any] | None = None,
        thermal: dict[str, Any] | None = None,
    ) -> str:
        """Persist high-level project design intent and structural group constraints."""
        return deps.service.set_design_intent(
            connector_refs=connector_refs,
            critical_nets=critical_nets,
            power_tree_refs=power_tree_refs,
            analog_refs=analog_refs,
            digital_refs=digital_refs,
            sensor_cluster_refs=sensor_cluster_refs,
            required_sheets=required_sheets,
            optional_sheets=optional_sheets,
            manufacturer=manufacturer,
            manufacturer_tier=manufacturer_tier,
            functional_spacing_mm=functional_spacing_mm,
            thermal_hotspots=thermal_hotspots,
            critical_frequencies_mhz=critical_frequencies_mhz,
            decoupling_pairs=decoupling_pairs,
            rf_keepout_regions=rf_keepout_regions,
            power_rails=power_rails,
            interfaces=interfaces,
            mechanical=mechanical,
            compliance=compliance,
            cost=cost,
            thermal=thermal,
        )

    @mcp.tool()
    @headless_compatible
    def project_import_design_spec(
        path: str | None = None,
        markdown: str | None = None,
        strict: bool = True,
        dry_run: bool = True,
    ) -> ProjectImportDesignSpecPayload:
        """Import structured product/spec text into ProjectDesignIntent conservatively.

        Accepts JSON or YAML frontmatter/fenced blocks. The importer only persists
        explicit supported ProjectDesignIntent fields; it reports missing mandatory
        decisions, placeholders, and extra fields such as MPN/LCSC/populate lists
        without inventing values. Use ``dry_run=True`` first, then re-run with
        ``dry_run=False`` after reviewing the parsed result.
        """
        return deps.service.import_design_spec(
            path=path,
            markdown=markdown,
            strict=strict,
            dry_run=dry_run,
        )

    @mcp.tool()
    @headless_compatible
    @ttl_cache(ttl_seconds=2)
    def project_get_design_intent() -> str:
        """Show the persisted project design intent used by placement and release gates."""
        return deps.service.get_design_intent()

    @mcp.tool()
    @headless_compatible
    def project_get_design_spec() -> ProjectSpecPayload:
        """Return the resolved project design spec with explicit and inferred fields."""
        return deps.service.get_design_spec()

    @mcp.tool()
    @headless_compatible
    def project_infer_design_spec() -> ProjectSpecPayload:
        """Infer a design spec from the active PCB without writing it to disk."""
        return deps.service.infer_design_spec()

    @mcp.tool()
    @headless_compatible
    def project_validate_design_spec() -> ProjectSpecValidationPayload:
        """Validate the resolved design spec against the active project PCB."""
        return deps.service.validate_design_spec()

    @mcp.tool()
    @headless_compatible
    def project_generate_design_prompt(
        circuit_description: str = "",
        target_fab: str = "",
    ) -> str:
        """Generate a professional workflow prompt tailored to the resolved project spec."""
        return deps.service.generate_design_prompt(
            circuit_description=circuit_description,
            target_fab=target_fab,
        )
