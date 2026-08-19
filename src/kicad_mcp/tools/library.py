"""Symbol and footprint library tools."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..file_formats import upgrade_generated_file
from ..library.catalog import (
    LibraryCatalogService,
    get_symbol_index,
    read_symbol_file,
    rebuild_symbol_index,
    symbol_library_dir,
)
from ..library.component_contract import LibraryComponentContractService
from ..library.footprint_engineering import LibraryFootprintEngineeringService
from ..library.local_authoring import LibraryLocalAuthoringService
from ..library.sourcing import LibrarySourcingService
from ..library_resolution import (
    footprint_file as _footprint_file,
)
from ..library_resolution import (
    footprint_library_dirs as _footprint_library_dirs,
)
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
from ..utils.sexpr import _extract_block
from . import (
    library_catalog,
    library_component_contract,
    library_datasheet,
    library_footprint_engineering,
    library_local_authoring,
    library_sourcing,
)
from .export_support import _run_cli
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

    component_contract_service = LibraryComponentContractService(
        project_schematic_files=project_schematic_files,
        footprint_file=_footprint_file,
    )
    library_component_contract.register(
        mcp,
        library_component_contract.LibraryComponentContractDependencies(
            service=component_contract_service
        ),
    )

    local_authoring_service = LibraryLocalAuthoringService(
        footprint_file=lambda library, footprint: _footprint_file(library, footprint),
        update_symbol_property=lambda reference, field, value: update_symbol_property(
            reference, field, value
        ),
        project_dir=lambda: get_config().project_dir,
        upgrade_symbol_library=lambda path: upgrade_generated_file(
            path, "sym", _run_cli, allowed_root=get_config().workspace
        ),
    )
    library_local_authoring.register(
        mcp,
        library_local_authoring.LibraryLocalAuthoringDependencies(service=local_authoring_service),
    )

    library_datasheet.register(
        mcp,
        library_datasheet.LibraryDatasheetDependencies(service=catalog_service),
    )

    sourcing_service = LibrarySourcingService(
        component_search_client=lambda source: _component_search_client(source),
        parse_passive_parametric_query=lambda keyword, package="": _parse_passive_parametric_query(
            keyword, package
        ),
        rank_passive_parametric_results=lambda results, query: _rank_passive_parametric_results(
            results, query
        ),
        format_passive_parametric_lines=lambda heading, results, evidence, *, max_items=None: (
            _format_passive_parametric_lines(heading, results, evidence, max_items=max_items)
        ),
        sort_component_results=lambda results, *, sort_by: _sort_component_results(
            results, sort_by=sort_by
        ),
        format_component_lines=lambda heading, results, *, max_items=None: _format_component_lines(
            heading, results, max_items=max_items
        ),
        max_items_per_response=lambda: get_config().max_items_per_response,
        schematic_component_rows=lambda: _schematic_component_rows(),
        group_bom_rows=lambda rows: _group_bom_rows(rows),
        lookup_component=lambda client, *, lcsc_code, value: _lookup_component(
            client, lcsc_code=lcsc_code, value=value
        ),
        update_symbol_property=lambda reference, field, value: update_symbol_property(
            reference, field, value
        ),
    )
    sourcing_deps = library_sourcing.LibrarySourcingDependencies(service=sourcing_service)
    library_sourcing.register(mcp, sourcing_deps)

    footprint_engineering_service = LibraryFootprintEngineeringService(
        resolve_within_project=lambda path: get_config().resolve_within_project(path),
        default_output_dir=lambda: (
            get_config().output_dir or cast(Path, get_config().project_dir) / "output"
        ),
        upgrade_generated_footprint=lambda path: upgrade_generated_file(
            path, "fp", _run_cli, allowed_root=get_config().workspace
        ),
    )
    library_footprint_engineering.register(
        mcp,
        library_footprint_engineering.LibraryFootprintEngineeringDependencies(
            service=footprint_engineering_service
        ),
    )

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
        format_upgrade = upgrade_generated_file(
            out_file, "sym", _run_cli, allowed_root=cfg.workspace
        )
        result = (
            f"Symbol saved to {out_file}\n"
            f"Name: {name}, Pins: {len(pin_specs)}, Ref prefix: {reference_prefix}"
        )
        if not format_upgrade.upgraded:
            result += (
                "\nFormat note: kept repository writer dialect; "
                f"KiCad migration was unavailable ({format_upgrade.detail})."
            )
        return result

    library_sourcing.register_part_selection(mcp, sourcing_deps)
