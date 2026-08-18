"""FastMCP adapter for live component sourcing and BOM tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from ..models.verdict import VerdictReport
from .metadata import headless_compatible


class LibrarySourcingServiceProtocol(Protocol):
    def search_components(
        self,
        query: str | None = None,
        keyword: str | None = None,
        package: str = "",
        only_basic: bool = True,
        source: str = "jlcsearch",
        min_stock: int = 10,
        sort_by: str = "price",
        rohs_compliant: bool | None = None,
        lifecycle: str = "",
    ) -> str: ...

    def get_component_details(self, lcsc_code_or_mpn: str, source: str = "jlcsearch") -> str: ...

    def check_sourcing_policy(
        self,
        lcsc_code_or_mpn: str,
        source: str = "jlcsearch",
        min_stock: int = 10,
        max_unit_price: float | None = None,
        allowed_lifecycle: list[str] | None = None,
        require_rohs: bool = False,
        approved_manufacturers: list[str] | None = None,
    ) -> VerdictReport: ...

    def assign_lcsc_to_symbol(self, reference: str, lcsc_code: str) -> str: ...

    def get_bom_with_pricing(self, quantity: int = 1, source: str = "jlcsearch") -> str: ...

    def check_stock_availability(
        self,
        refs: list[str] | None = None,
        source: str = "jlcsearch",
        mpns: list[str] | None = None,
    ) -> str: ...

    def find_alternative_parts(
        self, lcsc_code: str, tolerance_percent: float = 10.0, source: str = "jlcsearch"
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class LibrarySourcingDependencies:
    service: LibrarySourcingServiceProtocol


def register(mcp: FastMCP, deps: LibrarySourcingDependencies) -> None:
    """Register live component sourcing and BOM tools."""

    @mcp.tool()
    @headless_compatible
    def lib_search_components(
        query: str | None = None,
        keyword: str | None = None,
        package: str = "",
        only_basic: bool = True,
        source: str = "jlcsearch",
        min_stock: int = 10,
        sort_by: str = "price",
        rohs_compliant: bool | None = None,
        lifecycle: str = "",
    ) -> str:
        """Search live component sources for purchasable parts.

        ``source``: ``jlcsearch`` (JLCPCB public catalog, no credentials; default),
        ``nexar`` (requires NEXAR_CLIENT_ID/NEXAR_CLIENT_SECRET), ``digikey``
        (requires DIGIKEY_CLIENT_ID/DIGIKEY_CLIENT_SECRET), or ``mouser`` (requires
        MOUSER_API_KEY). The authenticated sources are inactive until their
        credentials are configured (loaded from ``.env`` at server startup).

        Set ``rohs_compliant`` to ``true`` to filter to RoHS-compliant parts only.
        ``lifecycle`` filters to a specific lifecycle status (e.g. ``Active``,
        ``NRND``, ``EOL``) when the provider reports it.
        """
        return deps.service.search_components(
            query,
            keyword,
            package,
            only_basic,
            source,
            min_stock,
            sort_by,
            rohs_compliant,
            lifecycle,
        )

    @mcp.tool()
    @headless_compatible
    def lib_get_component_details(lcsc_code_or_mpn: str, source: str = "jlcsearch") -> str:
        """Return live component detail for a specific LCSC code or MPN.

        Displays sourcing metadata (lifecycle, RoHS compliance) and a datasheet
        URL when the provider reports them.
        """
        return deps.service.get_component_details(lcsc_code_or_mpn, source)

    @mcp.tool()
    @headless_compatible
    def lib_check_sourcing_policy(
        lcsc_code_or_mpn: str,
        source: str = "jlcsearch",
        min_stock: int = 10,
        max_unit_price: float | None = None,
        allowed_lifecycle: list[str] | None = None,
        require_rohs: bool = False,
        approved_manufacturers: list[str] | None = None,
    ) -> VerdictReport:
        """Return a structured sourcing policy verdict for one live part."""
        return deps.service.check_sourcing_policy(
            lcsc_code_or_mpn,
            source,
            min_stock,
            max_unit_price,
            allowed_lifecycle,
            require_rohs,
            approved_manufacturers,
        )

    @mcp.tool()
    @headless_compatible
    def lib_assign_lcsc_to_symbol(reference: str, lcsc_code: str) -> str:
        """Assign an LCSC part code to a schematic symbol property."""
        return deps.service.assign_lcsc_to_symbol(reference, lcsc_code)

    @mcp.tool()
    @headless_compatible
    def lib_get_bom_with_pricing(quantity: int = 1, source: str = "jlcsearch") -> str:
        """Generate a live BOM summary with unit and extended pricing."""
        return deps.service.get_bom_with_pricing(quantity, source)

    @mcp.tool()
    @headless_compatible
    def lib_check_stock_availability(
        refs: list[str] | None = None,
        source: str = "jlcsearch",
        mpns: list[str] | None = None,
    ) -> str:
        """Check live stock availability by schematic reference or part number.

        Provide ``refs`` to look up stock for schematic references (resolving each
        reference to its part number via the active schematic), or ``mpns`` to look
        up stock directly by manufacturer part number / LCSC code without needing a
        schematic. This lets you vet a BOM before the schematic exists. Supply at
        least one of ``refs`` or ``mpns``.
        """
        return deps.service.check_stock_availability(refs, source, mpns)

    @mcp.tool()
    @headless_compatible
    def lib_find_alternative_parts(
        lcsc_code: str,
        tolerance_percent: float = 10.0,
        source: str = "jlcsearch",
    ) -> str:
        """Find nearby alternative parts for the supplied LCSC code."""
        return deps.service.find_alternative_parts(lcsc_code, tolerance_percent, source)
