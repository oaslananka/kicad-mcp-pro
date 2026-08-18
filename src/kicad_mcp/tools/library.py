"""Symbol and footprint library tools."""

from __future__ import annotations

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
from ..library.component_contract import LibraryComponentContractService
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
    library_local_authoring,
    library_sourcing,
)
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
    library_sourcing.register(
        mcp,
        library_sourcing.LibrarySourcingDependencies(service=sourcing_service),
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
