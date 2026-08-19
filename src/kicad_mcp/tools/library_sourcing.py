"""FastMCP adapter for live component sourcing and BOM tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

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

    def check_derating_compliance(
        self,
        kind: str,
        parameter: str,
        rated_value: float,
        operating_value: float,
        manufacturer: str = "",
        approved_vendors: list[str] | None = None,
    ) -> str: ...

    def recommend_part(
        self,
        category: str,
        requirements: dict[str, Any],
        package: str = "",
        only_basic: bool = True,
        source: str = "jlcsearch",
        max_results: int = 10,
    ) -> str: ...

    def bind_part_to_symbol(
        self,
        sym_ref: str,
        lcsc_code_or_mpn: str,
        auto_assign_footprint: bool = True,
        source: str = "jlcsearch",
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


def register_compliance(mcp: FastMCP, deps: LibrarySourcingDependencies) -> None:
    """Register reliability/AVL compliance at its legacy public position."""

    @mcp.tool()
    @headless_compatible
    def lib_check_derating(
        kind: str,
        parameter: str,
        rated_value: float,
        operating_value: float,
        manufacturer: str = "",
        approved_vendors: list[str] | None = None,
    ) -> str:
        """Check a part choice for reliability derating and approved-vendor (AVL) compliance.

        Verifies the operating value stays within the derating limit for the
        component ``kind``/``parameter`` (e.g. capacitor/voltage <= 80% of rated),
        and — when ``approved_vendors`` is given — that ``manufacturer`` is on the
        approved-vendor list. Returns one PASS/WARN/FAIL verdict. Derating factors
        are conservative general-practice values, not a specific MIL/IPC mandate.
        """
        return deps.service.check_derating_compliance(
            kind,
            parameter,
            rated_value,
            operating_value,
            manufacturer,
            approved_vendors,
        )


def register_part_selection(mcp: FastMCP, deps: LibrarySourcingDependencies) -> None:
    """Register part recommendation and binding at their legacy public position."""

    @mcp.tool()
    @headless_compatible
    def lib_recommend_part(
        category: str,
        requirements: dict[str, Any],
        package: str = "",
        only_basic: bool = True,
        source: str = "jlcsearch",
        max_results: int = 10,
    ) -> str:
        """Recommend a purchasable part given electrical requirements.

        Args:
            category: Component category keyword to search (e.g. "LDO regulator",
                "N-channel MOSFET", "ferrite bead", "ESD protection").
            requirements: Dict of electrical parameter hints used for post-search
                filtering. Common keys: ``voltage_v``, ``current_a``, ``vgs_v``,
                ``rds_on_mohm``, ``psrr_db``, ``capacitance_uf``, ``resistance_ohm``.
                Values can be numbers (min) or ``{"min": x, "max": y}`` dicts.
            package: Optional SMD package filter (e.g. "SOT-23", "SOIC-8").
            only_basic: Prefer JLCPCB basic parts (lower assembly cost).
            source: Parts source: ``"jlcsearch"``, ``"nexar"``, or ``"digikey"``.
            max_results: Maximum number of recommendations to return.

        Returns:
            Ranked list of part recommendations with LCSC code, MPN, package, price.
        """
        return deps.service.recommend_part(
            category, requirements, package, only_basic, source, max_results
        )

    @mcp.tool()
    @headless_compatible
    def lib_bind_part_to_symbol(
        sym_ref: str,
        lcsc_code_or_mpn: str,
        auto_assign_footprint: bool = True,
        source: str = "jlcsearch",
    ) -> str:
        """Assign a live part (LCSC/MPN) to a schematic symbol and optionally its footprint.

        This is the recommended tool for closing the part-selection loop after
        lib_recommend_part() or lib_search_components() returns a suitable part.

        Args:
            sym_ref: Schematic reference designator (e.g. "U1", "C4").
            lcsc_code_or_mpn: LCSC part code or manufacturer part number.
            auto_assign_footprint: If True, attempts to assign the footprint from
                the live part data to the symbol. Requires the schematic backend.
            source: Parts source for detail lookup.

        Returns:
            Confirmation of LCSC/MPN assignment and footprint status.
        """
        return deps.service.bind_part_to_symbol(
            sym_ref, lcsc_code_or_mpn, auto_assign_footprint, source
        )
