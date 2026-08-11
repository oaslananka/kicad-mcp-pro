"""Symbol and footprint library tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..library.catalog import (
    LibraryCatalogService,
    get_symbol_index,
    read_symbol_file,
    rebuild_symbol_index,
    symbol_library_dir,
)
from ..library_resolution import (
    footprint_file as _footprint_file,
)
from ..library_resolution import (
    footprint_library_dirs as _footprint_library_dirs,
)
from ..models import contract_verifier as cv
from ..models.component_contracts import find_component_contract
from ..models.verdict import Finding, Verdict, VerdictReport, stable_finding_id
from ..utils.component_search import (
    ComponentRecord,
    ComponentSearchClient,
    DigiKeyClient,
    JLCSearchClient,
    MouserClient,
    NexarClient,
    normalize_lcsc_code,
)
from ..utils.library_tables import parse_lib_table as _shared_parse_lib_table
from ..utils.library_tables import resolve_kicad_env
from ..utils.sexpr import _extract_block, _sexpr_string
from . import library_catalog
from .metadata import headless_compatible
from .schematic import get_schematic_backend, project_schematic_files, update_symbol_property

# Compatibility alias retained for downstream/tests that historically imported it here.
_parse_lib_table = _shared_parse_lib_table


def _footprint_library_dir() -> Path:
    cfg = get_config()
    if cfg.footprint_library_dir is None or not cfg.footprint_library_dir.exists():
        raise FileNotFoundError("No KiCad footprint library directory is configured.")
    return cfg.footprint_library_dir


def _resolve_kicad_env(uri: str, project_dir: Path | None) -> str:
    """Compatibility wrapper around shared KiCad environment substitution."""
    return resolve_kicad_env(uri, project_dir)


def _component_search_client(source: str) -> ComponentSearchClient:
    normalized = source.strip().casefold()
    if normalized == "jlcsearch":
        return JLCSearchClient()
    if normalized == "nexar":
        return NexarClient()
    if normalized == "digikey":
        return DigiKeyClient()
    if normalized == "mouser":
        return MouserClient()
    raise ValueError("Unknown component source. Use 'jlcsearch', 'nexar', 'digikey', or 'mouser'.")


_PASSIVE_PACKAGES = {"0201", "0402", "0603", "0805", "1206", "1210", "2512"}


@dataclass(frozen=True)
class PassiveParametricQuery:
    kind: str
    value: str
    variants: tuple[str, ...]
    package: str | None = None
    tolerance: str | None = None
    voltage: str | None = None

    def catalog_keyword(self, original_keyword: str) -> str:
        parts = [self.value, self.kind]
        if self.package:
            parts.append(self.package)
        if self.tolerance:
            parts.append(self.tolerance)
        if self.voltage:
            parts.append(self.voltage)
        keyword = " ".join(part for part in parts if part).strip()
        return keyword or original_keyword


def _compact_component_text(item: ComponentRecord) -> str:
    return (
        " ".join(
            part for part in (item.lcsc_code, item.mpn, item.description, item.package) if part
        )
        .casefold()
        .replace("µ", "u")
        .replace("ω", "ohm")
    )


def _passive_value_variants(value: str, kind: str) -> tuple[str, ...]:
    normalized = value.strip().casefold().replace(" ", "").replace("µ", "u").replace("ω", "ohm")
    variants = {normalized}
    if kind == "resistor":
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(r|k|m|ohm)?", normalized)
        if match:
            number = float(match.group(1))
            suffix = match.group(2) or "ohm"
            multiplier = {"r": 1.0, "ohm": 1.0, "k": 1_000.0, "m": 1_000_000.0}[suffix]
            ohms = number * multiplier
            if suffix == "k":
                variants.add(f"{number:g}k")
                variants.add(f"{number:g}kohm")
            elif suffix == "m":
                variants.add(f"{number:g}m")
                variants.add(f"{number:g}mohm")
            else:
                variants.add(f"{number:g}r")
                variants.add(f"{number:g}ohm")
            variants.add(f"{ohms:g}")
            variants.add(f"{ohms:g}ohm")
    else:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(p|n|u|µ|m)?f", normalized)
        if match:
            number = float(match.group(1))
            suffix = (match.group(2) or "").replace("µ", "u")
            variants.add(f"{number:g}{suffix}f")
            if suffix == "n":
                variants.add(f"{number / 1000:g}uf")
            elif suffix == "u":
                variants.add(f"{number * 1000:g}nf")
    return tuple(sorted(variants, key=len, reverse=True))


def _parse_passive_parametric_query(
    keyword: str, package: str = ""
) -> PassiveParametricQuery | None:
    text = keyword.casefold().replace("µ", "u").replace("ω", "ohm")
    explicit_package = package.strip() or ""
    package_match = re.search(r"\b(0201|0402|0603|0805|1206|1210|2512)\b", text)
    parsed_package = explicit_package or (package_match.group(1) if package_match else "")

    tolerance_match = re.search(r"(?<!\w)(0\.1%|0\.5%|1%|2%|5%|10%)(?!\w)", text)
    voltage_match = re.search(r"(?<!\w)(\d+(?:\.\d+)?\s*v)(?!\w)", text)

    resistor_match = re.search(
        r"\b(\d+(?:\.\d+)?\s*(?:r|k|m|ohm|kohm|mohm|Ω|kΩ|mΩ))\b",
        text,
    )
    capacitor_match = re.search(r"\b(\d+(?:\.\d+)?\s*(?:pf|nf|uf|µf|mf))\b", text)

    kind = ""
    value = ""
    if "resistor" in text or "resistance" in text or resistor_match:
        kind = "resistor"
        value = resistor_match.group(1) if resistor_match else ""
    if ("capacitor" in text or "capacitance" in text or capacitor_match) and capacitor_match:
        kind = "capacitor"
        value = capacitor_match.group(1)
    if not kind or not value:
        return None

    normalized_value = value.replace(" ", "").replace("Ω", "ohm").replace("µ", "u")
    return PassiveParametricQuery(
        kind=kind,
        value=normalized_value,
        variants=_passive_value_variants(normalized_value, kind),
        package=parsed_package or None,
        tolerance=tolerance_match.group(1) if tolerance_match else None,
        voltage=voltage_match.group(1).replace(" ", "") if voltage_match else None,
    )


def _rank_passive_parametric_results(
    results: list[ComponentRecord],
    query: PassiveParametricQuery | None,
) -> tuple[list[ComponentRecord], dict[str, list[str]]]:
    if query is None:
        return results, {}

    evidence: dict[str, list[str]] = {}

    def score(item: ComponentRecord) -> tuple[int, float, int, str]:
        text = _compact_component_text(item)
        points = 0
        reasons: list[str] = []
        if any(variant in text for variant in query.variants):
            points += 80
            reasons.append(f"value≈{query.value}")
        if query.package and query.package.casefold() in item.package.casefold():
            points += 30
            reasons.append(f"package={query.package}")
        if query.tolerance and query.tolerance.casefold() in text:
            points += 10
            reasons.append(f"tolerance={query.tolerance}")
        if query.voltage and query.voltage.casefold() in text:
            points += 10
            reasons.append(f"voltage={query.voltage}")
        if item.is_basic:
            points += 3
            reasons.append("basic")
        if item.is_preferred:
            points += 2
            reasons.append("preferred")
        evidence[item.lcsc_code or item.mpn] = reasons or ["catalog fallback"]
        return (
            -points,
            item.price if item.price is not None else float("inf"),
            -item.stock,
            item.mpn,
        )

    return sorted(results, key=score), evidence


def _format_passive_parametric_lines(
    heading: str,
    results: list[ComponentRecord],
    evidence: dict[str, list[str]],
    *,
    max_items: int | None = None,
) -> str:
    text = _format_component_lines(heading, results, max_items=max_items)
    if not results or not evidence:
        return text
    lines = text.splitlines()
    annotated: list[str] = []
    for line in lines:
        if line.startswith("- "):
            code = line.split(" | ", 1)[0][2:]
            reasons = evidence.get(code)
            if reasons:
                line = f"{line} | match: {', '.join(reasons)}"
        annotated.append(line)
    return "\n".join(annotated)


def _sort_component_results(
    results: list[ComponentRecord],
    *,
    sort_by: str,
) -> list[ComponentRecord]:
    if sort_by == "stock":
        return sorted(results, key=lambda item: (-item.stock, item.price or float("inf"), item.mpn))
    if sort_by == "mpn":
        return sorted(results, key=lambda item: (item.mpn.casefold(), item.price or float("inf")))
    return sorted(
        results,
        key=lambda item: (
            item.price is None,
            item.price if item.price is not None else float("inf"),
            -item.stock,
            item.mpn.casefold(),
        ),
    )


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


def _format_component_lines(
    heading: str,
    results: list[ComponentRecord],
    *,
    max_items: int | None = None,
) -> str:
    if not results:
        return f"{heading}\nNo live component matches were found."
    limit = max_items or get_config().max_items_per_response
    lines = [heading]
    for item in results[:limit]:
        stock = f"{item.stock:,}"
        price = f"${item.price:.6f}" if item.price is not None else "(n/a)"
        basic = "basic" if item.is_basic else "extended"
        preferred = " preferred" if item.is_preferred else ""
        description = f" - {item.description}" if item.description else ""
        sourcing = ""
        if item.lifecycle:
            sourcing += f" | lifecycle {item.lifecycle}"
        if item.rohs:
            sourcing += f" | RoHS {item.rohs}"
        lines.append(
            f"- {item.lcsc_code} | {item.mpn} | {item.package or '(no package)'} | "
            f"stock {stock} | {price} | {basic}{preferred}{sourcing}{description}"
        )
    if len(results) > limit:
        lines.append(f"... and {len(results) - limit} more matches")
    return "\n".join(lines)


def _active_schematic_file() -> Path:
    cfg = get_config()
    if cfg.sch_file is None or not cfg.sch_file.exists():
        raise FileNotFoundError(
            "No schematic file is configured. Call kicad_set_project() before requesting BOM data."
        )
    return cfg.sch_file


def _symbol_property(block: str, name: str) -> str:
    match = re.search(
        rf'\(property\s+"{re.escape(name)}"\s+"((?:\\.|[^"\\])*)"',
        block,
    )
    if match is None:
        return ""
    return match.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def _schematic_component_rows() -> list[dict[str, str]]:
    _ = _active_schematic_file()
    rows_by_reference: dict[str, dict[str, str]] = {}

    for sch_file in project_schematic_files():
        parsed = get_schematic_backend().parse_schematic_file(sch_file)
        raw_content = sch_file.read_text(encoding="utf-8", errors="ignore")

        for symbol in parsed["symbols"]:
            reference = str(symbol["reference"])
            if reference.startswith("#"):
                continue
            rows_by_reference.setdefault(
                reference,
                {
                    "reference": reference,
                    "value": str(symbol["value"]),
                    "footprint": str(symbol.get("footprint", "")),
                    "lib_id": str(symbol.get("lib_id", "")),
                    "lcsc": "",
                    "mpn": "",
                    "manufacturer": "",
                    "populate": "",
                },
            )

        search_start = 0
        while True:
            block_start = raw_content.find("(symbol", search_start)
            if block_start < 0:
                break
            block, consumed = _extract_block(raw_content, block_start)
            search_start = block_start + max(consumed, 1)
            if '(lib_id "' not in block:
                continue
            reference = _symbol_property(block, "Reference")
            if not reference or reference.startswith("#") or reference not in rows_by_reference:
                continue
            lcsc_code = _symbol_property(block, "LCSC") or _symbol_property(block, "LCSC Part")
            if lcsc_code:
                rows_by_reference[reference]["lcsc"] = normalize_lcsc_code(lcsc_code)

            mpn = _symbol_property(block, "MPN") or _symbol_property(
                block,
                "Manufacturer Part Number",
            )
            if mpn:
                rows_by_reference[reference]["mpn"] = mpn

            manufacturer = _symbol_property(block, "Manufacturer") or _symbol_property(block, "MFR")
            if manufacturer:
                rows_by_reference[reference]["manufacturer"] = manufacturer

            dnp = _symbol_property(block, "DNP") or _symbol_property(block, "Do Not Populate")
            native_dnp = re.search(r"\(dnp\s+yes\)", block) is not None
            exclude_from_bom = _symbol_property(block, "Exclude from BOM")
            populate_value = _symbol_property(block, "Populate")
            if populate_value:
                rows_by_reference[reference]["populate"] = populate_value
            elif native_dnp or dnp.lower() in {"1", "true", "yes", "y", "dnp"}:
                rows_by_reference[reference]["populate"] = "DNP"
            elif exclude_from_bom.lower() in {"1", "true", "yes", "y"}:
                rows_by_reference[reference]["populate"] = "DNP"
            else:
                rows_by_reference[reference]["populate"] = (
                    rows_by_reference[reference].get("populate", "Populate") or "Populate"
                )
    return list(rows_by_reference.values())


def _lookup_component(
    client: ComponentSearchClient,
    *,
    lcsc_code: str,
    value: str,
) -> ComponentRecord | None:
    _ = value
    if not lcsc_code:
        return None
    return client.get_part(lcsc_code)


def _group_bom_rows(symbol_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for row in symbol_rows:
        key = (
            row.get("lcsc", ""),
            row.get("mpn", ""),
            row.get("manufacturer", ""),
            row.get("populate", ""),
            row["value"],
            row["footprint"],
        )
        entry = grouped.setdefault(
            key,
            {
                "lcsc": row.get("lcsc", ""),
                "mpn": row.get("mpn", ""),
                "manufacturer": row.get("manufacturer", ""),
                "populate": row.get("populate", ""),
                "value": row["value"],
                "footprint": row["footprint"],
                "references": [],
            },
        )
        cast(list[str], entry["references"]).append(row["reference"])
    return list(grouped.values())


def register(mcp: FastMCP) -> None:
    """Register library tools."""
    catalog_service = LibraryCatalogService(
        symbol_library_dir=symbol_library_dir,
        footprint_library_dirs=_footprint_library_dirs,
        get_symbol_index=get_symbol_index,
        read_symbol_file=read_symbol_file,
        rebuild_symbol_index=rebuild_symbol_index,
        footprint_file=_footprint_file,
        max_items_per_response=lambda: get_config().max_items_per_response,
    )
    library_catalog.register(
        mcp,
        library_catalog.LibraryCatalogDependencies(service=catalog_service),
    )

    @mcp.tool()
    @headless_compatible
    def lib_verify_component_contract(reference: str) -> str:
        """Verify a placed component's symbol, footprint, and pins actually match.

        For the given schematic reference designator this checks, entirely from
        local project files (no network access):

        - symbol pin count vs footprint connectable pad count
        - pin numbers vs pad numbers
        - footprint courtyard / fabrication / silkscreen completeness
        - 3D model presence (advisory)
        - datasheet evidence (advisory; never auto-filled)

        Returns a JSON object with a ``status`` of PASS / WARN / FAIL and a list
        of per-check ``findings``. FAIL marks a structural contract violation,
        WARN marks a quality/completeness smell, and INFO is advisory evidence
        that never changes the overall status.
        """
        reference = reference.strip()
        if not reference:
            return json.dumps({"error": "reference must not be empty."})

        resolved: tuple[str, str] | None = None
        symbol_block: str | None = None
        for sch_file in project_schematic_files():
            try:
                sch_text = sch_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found = cv.find_symbol_instance(sch_text, reference)
            if found is not None:
                resolved = found
                symbol_block = cv.extract_lib_symbol_block(sch_text, found[0])
                break

        if resolved is None:
            return json.dumps(
                {"error": f"No placed symbol with reference '{reference}' was found."}
            )

        lib_id, footprint_id = resolved
        pins = cv.parse_symbol_pins(symbol_block) if symbol_block else ()
        datasheet = ""
        if symbol_block:
            ds_match = re.search(r'\(property\s+"Datasheet"\s+"([^"]*)"', symbol_block)
            if ds_match and ds_match.group(1) not in ("", "~"):
                datasheet = ds_match.group(1)

        footprint_shape = cv.FootprintShape()
        footprint_read = False
        if footprint_id and ":" in footprint_id:
            fp_library, fp_name = footprint_id.split(":", 1)
            try:
                fp_path = _footprint_file(fp_library, fp_name)
            except (OSError, ValueError):
                fp_path = None
            if fp_path is not None and fp_path.exists():
                footprint_shape = cv.parse_footprint(
                    fp_path.read_text(encoding="utf-8", errors="ignore")
                )
                footprint_read = True

        contract = find_component_contract(lib_id=lib_id, footprint=footprint_id)
        report = cv.verify_contract(
            reference=reference,
            lib_id=lib_id,
            footprint_id=footprint_id,
            pins=pins,
            footprint=footprint_shape,
            datasheet=datasheet,
            known_contract_category=contract.category if contract else "",
        )
        result = report.as_dict()
        notes: list[str] = []
        if footprint_id and not footprint_read:
            notes.append("Footprint file could not be located; pad-level checks were skipped.")
        elif not footprint_id:
            notes.append("No footprint is assigned to this reference; pad checks were skipped.")
        if notes:
            result["notes"] = notes
        return json.dumps(result, indent=2)

    @mcp.tool()
    @headless_compatible
    def lib_assign_footprint(reference: str, library: str, footprint: str) -> str:
        """Assign a footprint property to a schematic symbol."""
        path = _footprint_file(library, footprint)
        if not path.exists():
            return f"Footprint '{library}:{footprint}' was not found."
        assignment = f"{library}:{footprint}"
        update_symbol_property(reference, "Footprint", assignment)
        return f"Assigned footprint '{assignment}' to '{reference}'."

    @mcp.tool()
    @headless_compatible
    def lib_create_custom_symbol(name: str, pins: list[dict[str, Any]]) -> str:
        """Create a simple custom symbol in the active project directory."""
        cfg = get_config()
        if cfg.project_dir is None:
            return "No active project is configured."

        library_file = cfg.project_dir / "custom_symbols.kicad_sym"
        if library_file.exists():
            content = library_file.read_text(encoding="utf-8", errors="ignore")
        else:
            content = '(kicad_symbol_lib (version 20250316) (generator "kicad-mcp-pro"))\n'

        pin_blocks = []
        x = 0.0
        y = 0.0
        for index, pin in enumerate(pins, start=1):
            pin_number = str(pin.get("number", index))
            pin_name = str(pin.get("name", f"PIN{index}"))
            pin_blocks.append(
                "\t\t(pin passive line\n"
                f"\t\t\t(at {x} {y} 180)\n"
                "\t\t\t(length 2.54)\n"
                f"\t\t\t(name {_sexpr_string(pin_name)} "
                "(effects (font (size 1.27 1.27))))\n"
                f"\t\t\t(number {_sexpr_string(pin_number)} "
                "(effects (font (size 1.27 1.27))))\n"
                "\t\t)\n"
            )
            y -= 2.54

        symbol_block = (
            f"\t(symbol {_sexpr_string(name)}\n"
            '\t\t(property "Reference" "U" (id 0) (at 0 5.08 0) '
            "(effects (font (size 1.27 1.27))))\n"
            f'\t\t(property "Value" {_sexpr_string(name)} (id 1) (at 0 -5.08 0) '
            "(effects (font (size 1.27 1.27))))\n" + "".join(pin_blocks) + "\t)\n"
        )
        if content.rstrip().endswith(")"):
            content = content.rstrip()[:-1] + f"\n{symbol_block})\n"
        else:
            content += symbol_block
        library_file.write_text(content, encoding="utf-8")
        return f"Created custom symbol '{name}' in {library_file}."

    @mcp.tool()
    @headless_compatible
    def lib_get_datasheet_url(library: str, symbol_name: str) -> str:
        """Return a datasheet URL from the symbol library when available."""
        content = catalog_service.read_symbol_file(library)
        if content is None:
            return f"Symbol library '{library}' was not found."
        match = re.search(
            rf'\(symbol\s+"{re.escape(symbol_name)}".*?\(property\s+"Datasheet"\s+"([^"]*)"',
            content,
            re.DOTALL,
        )
        if match is None or not match.group(1):
            return f"No datasheet URL was found for '{library}:{symbol_name}'."
        return match.group(1)

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
        if query and keyword:
            return "Provide either query or keyword, not both."
        search_term = query or keyword
        if not search_term:
            return "Provide a query string to search live component sources."

        passive_query = _parse_passive_parametric_query(search_term, package)
        catalog_keyword = (
            passive_query.catalog_keyword(search_term) if passive_query else search_term
        )
        catalog_package = (
            passive_query.package if passive_query and passive_query.package else package or None
        )
        try:
            client = _component_search_client(source)
            results = client.search(
                catalog_keyword,
                package=catalog_package,
                only_basic=only_basic,
                limit=min(get_config().max_items_per_response, 20),
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
            ranked_below_stock, evidence = _rank_passive_parametric_results(results, passive_query)
            ordered_below_stock = (
                ranked_below_stock
                if passive_query
                else _sort_component_results(results, sort_by=sort_by)
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
            return _format_passive_parametric_lines(
                heading,
                ordered_below_stock,
                evidence,
            )

        ranked, evidence = _rank_passive_parametric_results(filtered, passive_query)
        ordered = ranked if passive_query else _sort_component_results(filtered, sort_by=sort_by)
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
        return _format_passive_parametric_lines(
            heading,
            ordered,
            evidence,
        )

    @mcp.tool()
    @headless_compatible
    def lib_get_component_details(lcsc_code_or_mpn: str, source: str = "jlcsearch") -> str:
        """Return live component detail for a specific LCSC code or MPN.

        Displays sourcing metadata (lifecycle, RoHS compliance) and a datasheet
        URL when the provider reports them.
        """
        try:
            client = _component_search_client(source)
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
        try:
            client = _component_search_client(source)
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

    @mcp.tool()
    @headless_compatible
    def lib_assign_lcsc_to_symbol(reference: str, lcsc_code: str) -> str:
        """Assign an LCSC part code to a schematic symbol property."""
        normalized = normalize_lcsc_code(lcsc_code)
        update_symbol_property(reference, "LCSC", normalized)
        return f"Assigned LCSC code '{normalized}' to '{reference}'."

    @mcp.tool()
    @headless_compatible
    def lib_get_bom_with_pricing(quantity: int = 1, source: str = "jlcsearch") -> str:
        """Generate a live BOM summary with unit and extended pricing."""
        if quantity < 1:
            return "Quantity must be at least 1."
        try:
            client = _component_search_client(source)
            grouped_rows = _group_bom_rows(_schematic_component_rows())
        except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
            return f"Live BOM generation failed: {exc}"

        if not grouped_rows:
            return "No schematic symbols were available for BOM generation."

        lines = [f"Live BOM with pricing from {source}:"]
        total_cost = 0.0
        for row in grouped_rows[: get_config().max_items_per_response]:
            references = cast(list[str], row["references"])
            part = _lookup_component(
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

    @mcp.tool()
    @headless_compatible
    def lib_check_stock_availability(refs: list[str], source: str = "jlcsearch") -> str:
        """Check live stock availability for the requested schematic references."""
        wanted = {ref.strip().upper() for ref in refs if ref.strip()}
        if not wanted:
            return "No references were supplied."
        try:
            client = _component_search_client(source)
            rows = _schematic_component_rows()
        except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
            return f"Stock availability check failed: {exc}"

        matches = [row for row in rows if row["reference"].upper() in wanted]
        if not matches:
            return "None of the requested references were found in the active schematic."

        lines = [f"Stock availability from {source}:"]
        for row in matches:
            part = _lookup_component(
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

    @mcp.tool()
    @headless_compatible
    def lib_find_alternative_parts(
        lcsc_code: str,
        tolerance_percent: float = 10.0,
        source: str = "jlcsearch",
    ) -> str:
        """Find nearby alternative parts for the supplied LCSC code."""
        try:
            client = _component_search_client(source)
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
        ordered = _sort_component_results(alternatives, sort_by="price")
        return _format_component_lines(
            f"Alternative parts for {base_part.lcsc_code} from {source} ({len(ordered)} total):",
            ordered,
            max_items=10,
        )

    @mcp.tool()
    @headless_compatible
    def lib_generate_footprint_ipc7351(
        package: str,
        density: str = "B",
        pin_count: int | None = None,
        pitch_mm: float | None = None,
        body_l_mm: float | None = None,
        body_w_mm: float | None = None,
        rows: int = 1,
        exposed_pad_mm: float | None = None,
        ball_diameter_mm: float | None = None,
        output_path: str = "",
    ) -> str:
        """Generate an IPC-7351B compliant KiCad footprint (.kicad_mod) and save it.

        Supported packages: 0201, 0402, 0603, 0805, 1206, 1210, 2512 (chip passives),
        SOT-23, SOT-223, SOT-89, SOT-363/SOT-26, SC-70/SOT-323, SOD-123, SOD-323,
        SMA/SMB/SMC (DO-214), DPAK/TO-252, D2PAK/TO-263,
        SOIC, SOP, SSOP, TSSOP (dual SMD), QFP, LQFP, TQFP (quad flat),
        QFN, DFN (no-lead), BGA (ball grid array), PinHeader (through-hole).

        Args:
            package: Package family name (case-insensitive).
            density: IPC-7351B density level: A (generous), B (nominal), C (compact).
            pin_count: Number of leads / balls (required for multi-lead packages).
            pitch_mm: Lead pitch in mm.
            body_l_mm: Body length in mm.
            body_w_mm: Body width in mm (QFP only; defaults to body_l_mm).
            rows: BGA rows or PinHeader row count (1 or 2).
            exposed_pad_mm: Exposed pad size for QFN in mm.
            ball_diameter_mm: BGA ball diameter in mm.
            output_path: Optional relative path inside output_dir. Defaults to
                ``footprints/<package>.kicad_mod``.

        Returns:
            Confirmation with the saved file path, or an error message.
        """
        from ..utils.footprint_gen import generate_footprint

        if density not in ("A", "B", "C"):
            return f"Invalid density '{density}'. Must be A, B, or C."

        try:
            sexpr = generate_footprint(
                package,
                pin_count=pin_count,
                pitch_mm=pitch_mm,
                body_l_mm=body_l_mm,
                body_w_mm=body_w_mm,
                density=density,  # type: ignore[arg-type]
                rows=rows,
                exposed_pad_mm=exposed_pad_mm,
                ball_diameter_mm=ball_diameter_mm,
            )
        except ValueError as exc:
            return f"Footprint generation failed: {exc}"

        cfg = get_config()
        if output_path:
            out_file = cfg.resolve_within_project(output_path)
        else:
            out_dir = (cfg.output_dir or cfg.project_dir / "output") / "footprints"  # type: ignore[operator]
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_name = package.upper().replace("/", "_").replace(" ", "_")
            if pin_count:
                safe_name += f"-{pin_count}"
            out_file = out_dir / f"{safe_name}.kicad_mod"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(sexpr, encoding="utf-8")
        return (
            f"Footprint saved to {out_file}\n"
            f"Package: {package}, Density: {density}"
            + (f", {pin_count} pins" if pin_count else "")
            + (f", {pitch_mm:.2f}mm pitch" if pitch_mm else "")
        )

    @mcp.tool()
    @headless_compatible
    def lib_validate_footprint_ipc7351(
        footprint_path: str,
        size_code: str,
        density: str = "B",
        tolerance_mm: float = 0.12,
    ) -> str:
        """Validate a two-terminal chip footprint against its IPC-7351B nominal (hard gate).

        Reads the .kicad_mod at ``footprint_path`` (relative to the project), parses its
        SMD pads, and compares pad width/height/pitch to the IPC-7351B nominal for the
        given chip ``size_code`` and ``density``. Gross deviation is a blocking FAIL,
        minor deviation WARNs, a match PASSes. Scope: chip passives (0201–2512) against
        the IPC-7351B *standard* nominal — not a datasheet-specific land-pattern check.
        """
        from ..utils.footprint_validate import parse_smd_pads, validate_chip_footprint

        if density not in ("A", "B", "C"):
            return f"Invalid density '{density}'. Must be A, B, or C."
        cfg = get_config()
        try:
            path = cfg.resolve_within_project(footprint_path)
        except Exception as exc:  # noqa: BLE001 - surface any path-safety rejection
            return f"Invalid footprint path: {exc}"
        if not path.exists():
            return f"Footprint file not found: {path}"
        text = path.read_text(encoding="utf-8", errors="ignore")
        pads = parse_smd_pads(text)
        try:
            result = validate_chip_footprint(
                size_code,
                pads,
                density=density,  # type: ignore[arg-type]
                tol_mm=tolerance_mm,
            )
        except ValueError as exc:
            return f"Validation failed: {exc}"
        lines = [f"Footprint IPC-7351B validation: {result.verdict}", f"- {result.summary}"]
        lines.extend(f"  - {finding}" for finding in result.findings)
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def lib_certify_footprint(footprint_path: str) -> str:
        """Certify a footprint against package, documentation, and standard checks (#201).

        Reads the .kicad_mod at ``footprint_path`` (relative to the project) and runs
        package-agnostic certification: pad count vs the package name (SOIC/QFP/QFN/
        SOT/DIP…), documentation-layer completeness (courtyard/fab/silkscreen), and the
        recorded IPC-7351 density. Returns one aggregate PASS/WARN/FAIL with per-check
        findings; a missing courtyard or too-few pads is a blocking FAIL. Headless — no
        KiCad IPC. For two-terminal chip *geometry* use lib_validate_footprint_ipc7351.
        """
        import re as _re

        from ..utils.footprint_validate import (
            FootprintCheck,
            check_footprint_documentation_layers,
            check_footprint_pad_count,
            parse_ipc_density,
        )

        cfg = get_config()
        try:
            path = cfg.resolve_within_project(footprint_path)
        except Exception as exc:  # noqa: BLE001 - surface any path-safety rejection
            return f"Invalid footprint path: {exc}"
        if not path.exists():
            return f"Footprint file not found: {path}"
        text = path.read_text(encoding="utf-8", errors="ignore")
        name_match = _re.search(r'\(footprint\s+"([^"]+)"', text)
        footprint_name = name_match.group(1) if name_match else path.stem

        checks: list[tuple[str, FootprintCheck]] = []
        pad_check = check_footprint_pad_count(footprint_name, text)
        if pad_check is not None:
            checks.append(("pad-count", pad_check))
        checks.append(("documentation-layers", check_footprint_documentation_layers(text)))

        verdicts = {check.verdict for _, check in checks}
        overall = "FAIL" if "FAIL" in verdicts else "WARN" if "WARN" in verdicts else "PASS"

        density = parse_ipc_density(text)
        lines = [
            f"Footprint certification: {overall}",
            f"- Footprint: {footprint_name}",
            f"- IPC-7351 density recorded: {density}"
            if density
            else "- IPC-7351 density: not recorded",
        ]
        if pad_check is None:
            lines.append(
                "- [INFO] pad-count: package name does not encode a certifiable pin count."
            )
        for label, check in checks:
            lines.append(f"- [{check.verdict}] {label}: {check.summary}")
            lines.extend(f"    - {finding}" for finding in check.findings)
        return "\n".join(lines)

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
        from ..utils.derating import _worst, avl_check, derating_check

        try:
            derating = derating_check(kind, parameter, rated_value, operating_value)
        except ValueError as exc:
            return f"Derating check failed: {exc}"
        avl_verdict, avl_summary = avl_check(manufacturer, approved_vendors or [])
        overall = _worst(derating.verdict, avl_verdict)
        lines = [
            f"Part sourcing compliance: {overall}",
            f"- Derating [{derating.verdict}]: {derating.summary}",
            f"- AVL [{avl_verdict}]: {avl_summary}",
        ]
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def lib_generate_symbol_from_pintable(
        name: str,
        pins: list[dict[str, Any]],
        reference_prefix: str = "U",
        description: str = "",
        datasheet: str = "",
        footprint_hint: str = "",
        output_path: str = "",
    ) -> str:
        """Generate a KiCad symbol (.kicad_sym) from a pin table and save it.

        Each pin dict must contain:
            ``number`` (str | int), ``name`` (str).
        Optional per-pin keys:
            ``pin_type`` (input/output/bidirectional/passive/power_in/power_out/…),
            ``side`` (left/right/top/bottom), ``unit`` (int ≥ 1).

        Args:
            name: Symbol name, used as both the library entry and the default value.
            pins: List of pin specification dicts.
            reference_prefix: Ref-des prefix (U, J, Q, R, …).
            description: Short human description.
            datasheet: Datasheet URL or path.
            footprint_hint: Default footprint (e.g. "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm").
            output_path: Optional relative path inside output_dir. Defaults to
                ``symbols/<name>.kicad_sym``.

        Returns:
            Confirmation with the saved file path, or an error message.
        """
        from ..utils.symbol_gen import PinSpec, generate_symbol

        pin_specs: list[PinSpec] = []
        for raw in pins:
            try:
                pin_specs.append(
                    PinSpec(
                        number=raw["number"],
                        name=raw["name"],
                        pin_type=raw.get("pin_type", "bidirectional"),
                        side=raw.get("side", "left"),
                        unit=int(raw.get("unit", 1)),
                    )
                )
            except (KeyError, ValueError) as exc:
                return f"Invalid pin specification: {exc} — raw: {raw}"

        try:
            sexpr = generate_symbol(
                name,
                pin_specs,
                reference_prefix=reference_prefix,
                description=description,
                datasheet=datasheet,
                footprint_hint=footprint_hint,
            )
        except Exception as exc:
            return f"Symbol generation failed: {exc}"

        cfg = get_config()
        if output_path:
            out_file = cfg.resolve_within_project(output_path)
        else:
            out_dir = (cfg.output_dir or cfg.project_dir / "output") / "symbols"  # type: ignore[operator]
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_name = name.replace(" ", "_").replace("/", "_")
            out_file = out_dir / f"{safe_name}.kicad_sym"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(sexpr, encoding="utf-8")
        return (
            f"Symbol saved to {out_file}\n"
            f"Name: {name}, Pins: {len(pin_specs)}, Ref prefix: {reference_prefix}"
        )

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
        try:
            client = _component_search_client(source)
            results = client.search(
                category,
                package=package or None,
                only_basic=only_basic,
                limit=50,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Part recommendation search failed: {exc}"

        filtered = [r for r in results if r.stock > 0]

        # Requirements filter — extract numbers from description and check constraints.
        # Keys follow a convention: suffix _v (voltage), _a (current), _db (decibels),
        # _mohm (milli-ohm), _uf (microfarad), _ohm (ohm), _mhz (MHz), _khz (kHz).
        # A value can be a scalar (treated as minimum) or {"min": x, "max": y}.
        import re as _re

        num_re = _re.compile(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?")

        def _extract_numbers(text: str) -> list[float]:
            return [float(m) for m in num_re.findall(text.lower())]

        def _unit_scale(key: str) -> float:
            """Convert requirement value to the same unit found in descriptions."""
            key = key.lower()
            if key.endswith("_mohm"):
                return 0.001  # milli-ohm -> ohm for description matching
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
            return 1.0  # _v, _a, _db, _ohm need no scaling

        def _matches(r: ComponentRecord) -> bool:
            if not requirements:
                return True
            desc = (r.description or "").lower()
            nums = _extract_numbers(desc)
            for key, val in requirements.items():
                scale = _unit_scale(key)
                if isinstance(val, dict):
                    lo = float(val.get("min", float("-inf"))) * scale
                    hi = float(val.get("max", float("inf"))) * scale
                    # Pass if any number in the description falls within [lo, hi]
                    if not any(lo <= n <= hi for n in nums):
                        return False
                elif isinstance(val, int | float):
                    target = float(val) * scale
                    # Pass if any number in the description is >= target (treat as minimum)
                    if nums and not any(n >= target * 0.8 for n in nums):
                        # 20% tolerance to handle rounding in descriptions
                        return False
                # String values are ignored by numeric filter (let agent decide)
            return True

        matched = [r for r in filtered if _matches(r)]
        ordered = _sort_component_results(matched, sort_by="price")[:max_results]

        lines = [f"Part recommendations for '{category}' (source={source}):"]
        if requirements:
            req_str = ", ".join(f"{k}={v}" for k, v in list(requirements.items())[:5])
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
        return _format_component_lines("\n".join(lines), ordered, max_items=max_results)

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
        try:
            client = _component_search_client(source)
            part = client.get_part(lcsc_code_or_mpn)
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Part lookup failed: {exc}"

        if part is None:
            return f"No part found for '{lcsc_code_or_mpn}' on {source}."

        # Assign LCSC code
        try:
            update_symbol_property(sym_ref, "LCSC", part.lcsc_code)
            update_symbol_property(sym_ref, "MPN", part.mpn or "")
        except Exception as exc:
            return f"Could not update schematic properties for '{sym_ref}': {exc}"

        lines = [
            f"Bound '{lcsc_code_or_mpn}' to {sym_ref}:",
            f"- LCSC: {part.lcsc_code}",
            f"- MPN: {part.mpn or '(n/a)'}",
            f"- Description: {part.description or '(n/a)'}",
            f"- Package: {part.package or '(n/a)'}",
        ]

        if auto_assign_footprint and part.package:
            # Try to find a matching footprint in the library index
            fp_assigned = False
            fp_assign_error = ""
            try:
                # Map common package strings to KiCad footprint search terms
                pkg_map = {
                    "SOT-23": "SOT-23",
                    "SOT-223": "SOT-223",
                    "SOIC-8": "SOIC-8_3.9x4.9mm_P1.27mm",
                    "SSOP-20": "SSOP-20_4.4x6.5mm_P0.65mm",
                }
                hint = pkg_map.get(part.package.upper(), part.package)
                update_symbol_property(sym_ref, "Footprint", hint)
                fp_assigned = True
            except Exception as exc:
                fp_assign_error = str(exc)

            if fp_assigned:
                lines.append(f"- Footprint hint: {part.package} (assigned to symbol)")
            else:
                error_suffix = (
                    f" (automatic assignment failed: {fp_assign_error})" if fp_assign_error else ""
                )
                lines.append(
                    f"- Footprint hint: {part.package} — "
                    "run lib_generate_footprint_ipc7351() or lib_assign_footprint() manually."
                    f"{error_suffix}"
                )
        elif auto_assign_footprint:
            lines.append(
                "- Footprint: package info unavailable — run lib_assign_footprint() manually."
            )

        return "\n".join(lines)
