"""Live component sourcing behavior independent of FastMCP."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from ..models.verdict import Finding, Verdict, VerdictReport, stable_finding_id
from ..utils.component_search import ComponentRecord, ComponentSearchClient, normalize_lcsc_code

_RECOMMENDATION_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?")
_PACKAGE_FOOTPRINT_HINTS = {
    "SOT-23": "SOT-23",
    "SOT-223": "SOT-223",
    "SOIC-8": "SOIC-8_3.9x4.9mm_P1.27mm",
    "SSOP-20": "SSOP-20_4.4x6.5mm_P0.65mm",
}


def _footprint_binding_line(
    update_symbol_property: Callable[[str, str, str], object],
    sym_ref: str,
    package: str,
) -> str:
    if not package:
        return "- Footprint: package info unavailable — run lib_assign_footprint() manually."

    hint = _PACKAGE_FOOTPRINT_HINTS.get(package.upper(), package)
    try:
        update_symbol_property(sym_ref, "Footprint", hint)
    except Exception as exc:
        return (
            f"- Footprint hint: {package} — "
            "run lib_generate_footprint_ipc7351() or lib_assign_footprint() manually."
            f" (automatic assignment failed: {exc})"
        )
    return f"- Footprint hint: {package} (assigned to symbol)"


def _recommendation_unit_scale(key: str) -> float:
    key = key.lower()
    if key.endswith("_mohm"):
        return 0.001
    if key.endswith("_uf"):
        return 1.0
    if key.endswith("_nf"):
        return 0.001
    if key.endswith("_pf"):
        return 1e-6
    if key.endswith("_mhz"):
        return 1.0
    if key.endswith("_khz"):
        return 0.001
    return 1.0


def _matches_recommendation_requirements(
    item: ComponentRecord, requirements: dict[str, Any]
) -> bool:
    if not requirements:
        return True
    numbers = [
        float(match) for match in _RECOMMENDATION_NUMBER_RE.findall(item.description.lower())
    ]
    for key, value in requirements.items():
        scale = _recommendation_unit_scale(key)
        if isinstance(value, dict):
            lower = float(value.get("min", float("-inf"))) * scale
            upper = float(value.get("max", float("inf"))) * scale
            if not any(lower <= number <= upper for number in numbers):
                return False
        elif isinstance(value, int | float):
            target = float(value) * scale
            if numbers and not any(number >= target * 0.8 for number in numbers):
                return False
    return True


def _worst_verdict(values: list[Verdict]) -> Verdict:
    if "FAIL" in values:
        return "FAIL"
    if "WARN" in values:
        return "WARN"
    return "PASS"


def _policy_finding(
    *,
    policy: str,
    verdict: Verdict,
    description: str,
    evidence: dict[str, Any],
    remediation: str,
) -> Finding | None:
    if verdict == "PASS":
        return None
    return Finding(
        id=stable_finding_id("sourcing_policy", policy, description),
        severity=VerdictReport.severity_for(verdict),
        location=policy,
        description=description,
        evidence=[evidence],
        remediation=remediation,
        retryable=False,
        failure_mode="design",
    )


@dataclass(frozen=True, slots=True)
class LibrarySourcingService:
    """Live component sourcing and BOM behavior."""

    component_search_client: Callable[[str], ComponentSearchClient]
    parse_passive_parametric_query: Callable[..., Any]
    rank_passive_parametric_results: Callable[
        ..., tuple[list[ComponentRecord], dict[str, list[str]]]
    ]
    format_passive_parametric_lines: Callable[..., str]
    sort_component_results: Callable[..., list[ComponentRecord]]
    format_component_lines: Callable[..., str]
    max_items_per_response: Callable[[], int]
    schematic_component_rows: Callable[[], list[dict[str, str]]]
    group_bom_rows: Callable[[list[dict[str, str]]], list[dict[str, Any]]]
    lookup_component: Callable[..., ComponentRecord | None]
    update_symbol_property: Callable[[str, str, str], object]

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
        if query and keyword:
            return "Provide either query or keyword, not both."
        search_term = query or keyword
        if not search_term:
            return "Provide a query string to search live component sources."

        passive_query = self.parse_passive_parametric_query(search_term, package)
        catalog_keyword = (
            passive_query.catalog_keyword(search_term) if passive_query else search_term
        )
        catalog_package = (
            passive_query.package if passive_query and passive_query.package else package or None
        )
        try:
            client = self.component_search_client(source)
            results = client.search(
                catalog_keyword,
                package=catalog_package,
                only_basic=only_basic,
                limit=min(self.max_items_per_response(), 20),
            )
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Live component search failed: {exc}"

        # Apply lifecycle/rohs filters post-search.
        _filter_notes: list[str] = []
        if rohs_compliant is True:
            results = [
                item
                for item in results
                if item.rohs and item.rohs.casefold() in {"yes", "compliant", "rohs compliant"}
            ]
            _filter_notes.append("RoHS compliant only")
        if lifecycle:
            needle = lifecycle.casefold()
            results = [item for item in results if needle in item.lifecycle.casefold()]
            _filter_notes.append(f"lifecycle={lifecycle}")
        filter_info = f" [{', '.join(_filter_notes)}]" if _filter_notes else ""

        filtered = [item for item in results if item.stock >= min_stock]
        if results and not filtered:
            ranked_below_stock, evidence = self.rank_passive_parametric_results(
                results, passive_query
            )
            ordered_below_stock = (
                ranked_below_stock
                if passive_query
                else self.sort_component_results(results, sort_by=sort_by)
            )
            heading = (
                f"Live component matches for '{search_term}' from {source}"
                f"{filter_info} "
                f"({len(ordered_below_stock)} total below min_stock={min_stock}):\n"
                "Matches exist, but all are below the requested stock threshold."
            )
            if passive_query:
                heading += (
                    f"\nParsed passive query: kind={passive_query.kind}, "
                    f"value={passive_query.value}, "
                    f"package={passive_query.package or '(any)'}"
                )
            return self.format_passive_parametric_lines(
                heading,
                ordered_below_stock,
                evidence,
            )

        ranked, evidence = self.rank_passive_parametric_results(filtered, passive_query)
        ordered = (
            ranked if passive_query else self.sort_component_results(filtered, sort_by=sort_by)
        )
        heading = (
            f"Live component matches for '{search_term}' from {source}{filter_info} "
            f"({len(ordered)} total):"
        )
        if passive_query:
            heading += (
                f"\nParsed passive query: kind={passive_query.kind}, "
                f"value={passive_query.value}, package={passive_query.package or '(any)'}"
            )
            if passive_query.tolerance:
                heading += f", tolerance={passive_query.tolerance}"
            if passive_query.voltage:
                heading += f", voltage={passive_query.voltage}"
        return self.format_passive_parametric_lines(
            heading,
            ordered,
            evidence,
        )

    def get_component_details(self, lcsc_code_or_mpn: str, source: str = "jlcsearch") -> str:
        """Return live component detail for a specific LCSC code or MPN.

        Displays sourcing metadata (lifecycle, RoHS compliance) and a datasheet
        URL when the provider reports them.
        """
        try:
            client = self.component_search_client(source)
            part = client.get_part(lcsc_code_or_mpn)
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Component detail lookup failed: {exc}"
        if part is None:
            return f"No component details were found for '{lcsc_code_or_mpn}'."

        price = f"${part.price:.6f}" if part.price is not None else "(n/a)"
        lines = [
            f"Component details from {source}:",
            f"- LCSC: {part.lcsc_code}",
            f"- MPN: {part.mpn}",
            f"- Package: {part.package or '(none)'}",
            f"- Description: {part.description or '(none)'}",
            f"- Stock: {part.stock:,}",
            f"- Unit price: {price}",
            f"- Basic: {'yes' if part.is_basic else 'no'}",
            f"- Preferred: {'yes' if part.is_preferred else 'no'}",
        ]
        if part.lifecycle:
            lines.append(f"- Lifecycle: {part.lifecycle}")
        if part.rohs:
            lines.append(f"- RoHS: {part.rohs}")
        if part.datasheet_url:
            lines.append(f"- Datasheet: {part.datasheet_url}")
        return "\n".join(lines)

    def check_sourcing_policy(
        self,
        lcsc_code_or_mpn: str,
        source: str = "jlcsearch",
        min_stock: int = 10,
        max_unit_price: float | None = None,
        allowed_lifecycle: list[str] | None = None,
        require_rohs: bool = False,
        approved_manufacturers: list[str] | None = None,
    ) -> VerdictReport:
        """Return a structured sourcing policy verdict for one live part."""
        try:
            client = self.component_search_client(source)
            part = client.get_part(lcsc_code_or_mpn)
        except (RuntimeError, ValueError, OSError) as exc:
            return VerdictReport.from_text_verdict(
                text=f"Sourcing policy check failed: {exc}",
                summary="Sourcing backend was unavailable.",
                verdict="FAIL",
                source="lib_check_sourcing_policy",
                evidence=[{"source": source, "error": str(exc)}],
                remediation="Configure the sourcing backend and retry.",
                retryable=True,
                failure_mode="environment",
            )
        if part is None:
            return VerdictReport.from_text_verdict(
                text=f"No component details were found for '{lcsc_code_or_mpn}'.",
                summary="Requested part was not found.",
                verdict="FAIL",
                source="lib_check_sourcing_policy",
                evidence=[{"source": source, "part": lcsc_code_or_mpn}],
                remediation="Use a valid LCSC code or MPN from lib_search_components().",
                failure_mode="configuration",
            )
        evidence = {
            "source": source,
            "lcsc_code": part.lcsc_code,
            "mpn": part.mpn,
            "stock": part.stock,
            "price": part.price,
            "lifecycle": part.lifecycle,
            "rohs": part.rohs,
        }
        checks: list[tuple[str, Verdict, str, str]] = []
        checks.append(
            (
                "stock",
                "PASS" if part.stock >= min_stock else "FAIL",
                f"stock {part.stock:,} / required {min_stock:,}",
                "Select an alternative part with sufficient stock.",
            )
        )
        if max_unit_price is not None:
            price_ok = part.price is not None and part.price <= max_unit_price
            checks.append(
                (
                    "price",
                    "PASS" if price_ok else "FAIL",
                    (
                        f"unit price {part.price if part.price is not None else 'n/a'} "
                        f"/ limit {max_unit_price}"
                    ),
                    "Select an alternative part below the price ceiling.",
                )
            )
        if allowed_lifecycle:
            allowed = [item.casefold() for item in allowed_lifecycle if item.strip()]
            lifecycle_ok = part.lifecycle and any(
                item in part.lifecycle.casefold() for item in allowed
            )
            checks.append(
                (
                    "lifecycle",
                    "PASS" if lifecycle_ok else ("WARN" if not part.lifecycle else "FAIL"),
                    f"lifecycle {part.lifecycle or 'missing'} / allowed {allowed_lifecycle}",
                    "Choose an active/in-production part or attach lifecycle evidence.",
                )
            )
        if require_rohs:
            rohs_text = part.rohs.casefold()
            rohs_ok = rohs_text in {"yes", "compliant", "rohs compliant"}
            checks.append(
                (
                    "rohs",
                    "PASS" if rohs_ok else ("WARN" if not rohs_text else "FAIL"),
                    f"RoHS {part.rohs or 'missing'}",
                    "Select a RoHS-compliant part or attach compliance evidence.",
                )
            )
        if approved_manufacturers:
            checks.append(
                (
                    "avl",
                    "WARN",
                    (
                        "approved_manufacturers configured but provider manufacturer "
                        "metadata is unavailable"
                    ),
                    (
                        "Verify AVL status manually or use provider records with "
                        "manufacturer metadata."
                    ),
                )
            )
        verdict = _worst_verdict([item[1] for item in checks])
        findings = [
            item
            for item in (
                _policy_finding(
                    policy=name,
                    verdict=status,
                    description=detail,
                    evidence=evidence,
                    remediation=remediation,
                )
                for name, status, detail, remediation in checks
            )
            if item is not None
        ]
        lines = [f"Sourcing policy verdict: {verdict}", f"- Part: {part.lcsc_code} | {part.mpn}"]
        lines.extend(f"- {name} [{status}]: {detail}" for name, status, detail, _ in checks)
        return VerdictReport(
            text="\n".join(lines),
            summary=f"Sourcing policy check completed with {verdict} verdict.",
            verdict=verdict,
            severity=VerdictReport.severity_for(verdict),
            failure_mode="none" if verdict == "PASS" else "design",
            evidence=[evidence],
            remediation="Resolve sourcing policy findings before binding this part."
            if verdict != "PASS"
            else "",
            findings=findings,
            next_action="Part satisfies configured sourcing policy."
            if verdict == "PASS"
            else "Use lib_find_alternative_parts() or relax policy constraints.",
            metadata={"source": source, "checks": [name for name, *_ in checks]},
        )

    def assign_lcsc_to_symbol(self, reference: str, lcsc_code: str) -> str:
        """Assign an LCSC part code to a schematic symbol property."""
        normalized = normalize_lcsc_code(lcsc_code)
        self.update_symbol_property(reference, "LCSC", normalized)
        return f"Assigned LCSC code '{normalized}' to '{reference}'."

    def get_bom_with_pricing(self, quantity: int = 1, source: str = "jlcsearch") -> str:
        """Generate a live BOM summary with unit and extended pricing."""
        if quantity < 1:
            return "Quantity must be at least 1."
        try:
            client = self.component_search_client(source)
            grouped_rows = self.group_bom_rows(self.schematic_component_rows())
        except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
            return f"Live BOM generation failed: {exc}"

        if not grouped_rows:
            return "No schematic symbols were available for BOM generation."

        lines = [f"Live BOM with pricing from {source}:"]
        total_cost = 0.0
        for row in grouped_rows[: self.max_items_per_response()]:
            references = cast(list[str], row["references"])
            part = self.lookup_component(
                client,
                lcsc_code=str(row["lcsc"]),
                value=str(row["value"]),
            )
            part_label = part.lcsc_code if part is not None else "(unresolved)"
            mpn = (
                part.mpn
                if part is not None
                else (f"{row['value']} (add LCSC field; value-only matching disabled)")
            )
            stock = f"{part.stock:,}" if part is not None else "n/a"
            price = part.price if part is not None else None
            unit_price = f"${price:.6f}" if price is not None else "(n/a)"
            extended = price * len(references) * quantity if price is not None else None
            if extended is not None:
                total_cost += extended
            extended_text = f"${extended:.6f}" if extended is not None else "(n/a)"
            total_quantity = len(references) * quantity
            lines.append(
                f"- {', '.join(references)} | {part_label} | {mpn} | qty {total_quantity} | "
                f"stock {stock} | unit {unit_price} | ext {extended_text}"
            )
        if total_cost > 0:
            lines.append(f"Estimated total: ${total_cost:.6f}")
        return "\n".join(lines)

    def check_stock_availability(
        self,
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
        wanted_mpns = [mpn.strip() for mpn in (mpns or []) if mpn.strip()]
        wanted = {ref.strip().upper() for ref in (refs or []) if ref.strip()}
        if not wanted and not wanted_mpns:
            if refs is None and mpns is None:
                return "Provide at least one of 'refs' or 'mpns'."
            return "No references were supplied."
        try:
            client = self.component_search_client(source)
        except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
            return f"Stock availability check failed: {exc}"

        if wanted_mpns:
            lines = [f"Stock availability from {source}:"]
            for mpn in wanted_mpns:
                part = client.get_part(mpn)
                if part is None:
                    lines.append(f"- {mpn}: unresolved (no matching part found)")
                    continue
                price = f"${part.price:.6f}" if part.price is not None else "(n/a)"
                lines.append(
                    f"- {mpn}: {part.lcsc_code} | {part.mpn} | stock {part.stock:,} | {price}"
                )
            return "\n".join(lines)

        try:
            rows = self.schematic_component_rows()
        except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
            return f"Stock availability check failed: {exc}"

        matches = [row for row in rows if row["reference"].upper() in wanted]
        if not matches:
            return "None of the requested references were found in the active schematic."

        lines = [f"Stock availability from {source}:"]
        for row in matches:
            part = self.lookup_component(
                client,
                lcsc_code=row["lcsc"],
                value=row["value"],
            )
            if part is None:
                lines.append(
                    f"- {row['reference']}: unresolved ({row['value']}; add an LCSC field)"
                )
                continue
            price = f"${part.price:.6f}" if part.price is not None else "(n/a)"
            lines.append(
                f"- {row['reference']}: {part.lcsc_code} | {part.mpn} | "
                f"stock {part.stock:,} | {price}"
            )
        return "\n".join(lines)

    def find_alternative_parts(
        self,
        lcsc_code: str,
        tolerance_percent: float = 10.0,
        source: str = "jlcsearch",
    ) -> str:
        """Find nearby alternative parts for the supplied LCSC code."""
        try:
            client = self.component_search_client(source)
            base_part = client.get_part(lcsc_code)
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Alternative part search failed: {exc}"
        if base_part is None:
            return f"No base component details were found for '{lcsc_code}'."

        try:
            candidates = client.search(
                base_part.mpn or base_part.lcsc_code,
                package=base_part.package or None,
                only_basic=base_part.is_basic,
                limit=20,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Alternative part search failed: {exc}"

        max_price = None
        if base_part.price is not None:
            max_price = base_part.price * (1.0 + tolerance_percent / 100.0)

        alternatives = [
            item
            for item in candidates
            if item.lcsc_code != base_part.lcsc_code
            and item.stock > 0
            and (max_price is None or item.price is None or item.price <= max_price)
        ]
        ordered = self.sort_component_results(alternatives, sort_by="price")
        return self.format_component_lines(
            f"Alternative parts for {base_part.lcsc_code} from {source} ({len(ordered)} total):",
            ordered,
            max_items=10,
        )

    def recommend_part(
        self,
        category: str,
        requirements: dict[str, Any],
        package: str = "",
        only_basic: bool = True,
        source: str = "jlcsearch",
        max_results: int = 10,
    ) -> str:
        """Recommend a purchasable part given electrical requirements."""
        try:
            client = self.component_search_client(source)
            results = client.search(
                category,
                package=package or None,
                only_basic=only_basic,
                limit=50,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Part recommendation search failed: {exc}"

        filtered = [item for item in results if item.stock > 0]
        matched = [
            item for item in filtered if _matches_recommendation_requirements(item, requirements)
        ]
        ordered = self.sort_component_results(matched, sort_by="price")[:max_results]

        lines = [f"Part recommendations for '{category}' (source={source}):"]
        if requirements:
            req_str = ", ".join(f"{key}={value}" for key, value in list(requirements.items())[:5])
            lines.append(f"Requirements: {req_str}")
        if not ordered:
            lines.append("No matching parts found. Try broadening the category or requirements.")
        else:
            lines.extend(
                [
                    "",
                    "Use lib_bind_part_to_symbol() to assign the chosen part to a schematic ref.",
                ]
            )
        return self.format_component_lines("\n".join(lines), ordered, max_items=max_results)

    def bind_part_to_symbol(
        self,
        sym_ref: str,
        lcsc_code_or_mpn: str,
        auto_assign_footprint: bool = True,
        source: str = "jlcsearch",
    ) -> str:
        """Assign a live part to a schematic symbol and optionally its footprint."""
        try:
            client = self.component_search_client(source)
            part = client.get_part(lcsc_code_or_mpn)
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Part lookup failed: {exc}"

        if part is None:
            return f"No part found for '{lcsc_code_or_mpn}' on {source}."

        try:
            self.update_symbol_property(sym_ref, "LCSC", part.lcsc_code)
            self.update_symbol_property(sym_ref, "MPN", part.mpn or "")
        except Exception as exc:
            return f"Could not update schematic properties for '{sym_ref}': {exc}"

        lines = [
            f"Bound '{lcsc_code_or_mpn}' to {sym_ref}:",
            f"- LCSC: {part.lcsc_code}",
            f"- MPN: {part.mpn or '(n/a)'}",
            f"- Description: {part.description or '(n/a)'}",
            f"- Package: {part.package or '(n/a)'}",
        ]

        if auto_assign_footprint:
            lines.append(
                _footprint_binding_line(self.update_symbol_property, sym_ref, part.package)
            )

        return "\n".join(lines)
