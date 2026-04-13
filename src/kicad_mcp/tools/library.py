"""Symbol and footprint library tools."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..utils.component_search import (
    ComponentRecord,
    ComponentSearchClient,
    DigiKeyClient,
    JLCSearchClient,
    NexarClient,
    normalize_lcsc_code,
)
from ..utils.sexpr import _extract_block
from .schematic import get_schematic_backend, update_symbol_property

_symbol_index: dict[str, dict[str, str]] | None = None
_symbol_index_lock = threading.Lock()


def _symbol_library_dir() -> Path:
    cfg = get_config()
    if cfg.symbol_library_dir is None or not cfg.symbol_library_dir.exists():
        raise FileNotFoundError("No KiCad symbol library directory is configured.")
    return cfg.symbol_library_dir


def _footprint_library_dir() -> Path:
    cfg = get_config()
    if cfg.footprint_library_dir is None or not cfg.footprint_library_dir.exists():
        raise FileNotFoundError("No KiCad footprint library directory is configured.")
    return cfg.footprint_library_dir


def _build_symbol_index() -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for sym_file in _symbol_library_dir().glob("*.kicad_sym"):
        library = sym_file.stem
        try:
            content = sym_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r'\(symbol\s+"([^"]+)"', content):
            symbol_name = match.group(1)
            if re.search(r"_\d+_\d+$", symbol_name):
                continue
            key = f"{library}:{symbol_name}"
            description_match = re.search(
                rf'\(symbol\s+"{re.escape(symbol_name)}".*?\(property\s+"Description"\s+"([^"]*)"',
                content,
                re.DOTALL,
            )
            keyword_match = re.search(
                rf'\(symbol\s+"{re.escape(symbol_name)}".*?\(property\s+"ki_keywords"\s+"([^"]*)"',
                content,
                re.DOTALL,
            )
            index[key] = {
                "library": library,
                "name": symbol_name,
                "description": description_match.group(1) if description_match else "",
                "keywords": keyword_match.group(1) if keyword_match else "",
            }
    return index


def _get_symbol_index() -> dict[str, dict[str, str]]:
    global _symbol_index
    if _symbol_index is None:
        with _symbol_index_lock:
            if _symbol_index is None:
                _symbol_index = _build_symbol_index()
    return _symbol_index


def _read_symbol_file(library: str) -> str | None:
    path = _symbol_library_dir() / f"{library}.kicad_sym"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="ignore")


def _footprint_file(library: str, footprint: str) -> Path:
    return _footprint_library_dir() / f"{library}.pretty" / f"{footprint}.kicad_mod"


def _component_search_client(source: str) -> ComponentSearchClient:
    normalized = source.strip().casefold()
    if normalized == "jlcsearch":
        return JLCSearchClient()
    if normalized == "nexar":
        return NexarClient()
    if normalized == "digikey":
        return DigiKeyClient()
    raise ValueError("Unknown component source. Use 'jlcsearch', 'nexar', or 'digikey'.")


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
        lines.append(
            f"- {item.lcsc_code} | {item.mpn} | {item.package or '(no package)'} | "
            f"stock {stock} | {price} | {basic}{preferred}{description}"
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
    sch_file = _active_schematic_file()
    parsed = get_schematic_backend().parse_schematic_file(sch_file)
    raw_content = sch_file.read_text(encoding="utf-8", errors="ignore")

    rows_by_reference: dict[str, dict[str, str]] = {
        str(symbol["reference"]): {
            "reference": str(symbol["reference"]),
            "value": str(symbol["value"]),
            "footprint": str(symbol.get("footprint", "")),
            "lib_id": str(symbol.get("lib_id", "")),
            "lcsc": "",
        }
        for symbol in parsed["symbols"]
        if not str(symbol["reference"]).startswith("#")
    }

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
    return list(rows_by_reference.values())


def _lookup_component(
    client: ComponentSearchClient,
    *,
    lcsc_code: str,
    value: str,
) -> ComponentRecord | None:
    identifier = lcsc_code or value
    if not identifier:
        return None
    return client.get_part(identifier)


def _group_bom_rows(symbol_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in symbol_rows:
        key = (row["lcsc"], row["value"], row["footprint"])
        entry = grouped.setdefault(
            key,
            {
                "lcsc": row["lcsc"],
                "value": row["value"],
                "footprint": row["footprint"],
                "references": [],
            },
        )
        cast(list[str], entry["references"]).append(row["reference"])
    return list(grouped.values())


def register(mcp: FastMCP) -> None:
    """Register library tools."""

    @mcp.tool()
    def lib_list_libraries() -> str:
        """List configured symbol and footprint libraries."""
        symbol_libs = sorted(path.stem for path in _symbol_library_dir().glob("*.kicad_sym"))
        footprint_libs = sorted(path.name for path in _footprint_library_dir().glob("*.pretty"))
        lines = [f"Symbol libraries ({len(symbol_libs)} total):"]
        lines.extend(f"- {name}" for name in symbol_libs[:50])
        lines.append("")
        lines.append(f"Footprint libraries ({len(footprint_libs)} total):")
        lines.extend(f"- {name}" for name in footprint_libs[:50])
        return "\n".join(lines)

    @mcp.tool()
    def lib_search_symbols(query: str, library_filter: str = "") -> str:
        """Search symbol libraries by name, description, or keywords."""
        index = _get_symbol_index()
        query_lower = query.lower()
        results = []
        for item in index.values():
            if library_filter and item["library"].lower() != library_filter.lower():
                continue
            haystack = f"{item['name']} {item['description']} {item['keywords']}".lower()
            if query_lower in haystack:
                results.append(item)
        if not results:
            return f"No symbols matched '{query}'."
        lines = [f"Symbol matches for '{query}' ({len(results)} total):"]
        for item in results[: get_config().max_items_per_response]:
            suffix = f" - {item['description']}" if item["description"] else ""
            lines.append(f"- {item['library']}:{item['name']}{suffix}")
        return "\n".join(lines)

    @mcp.tool()
    def lib_get_symbol_info(library: str, symbol_name: str) -> str:
        """Return details for a single symbol."""
        content = _read_symbol_file(library)
        if content is None:
            return f"Symbol library '{library}' was not found."

        start = content.find(f'(symbol "{symbol_name}"')
        if start == -1:
            return f"Symbol '{library}:{symbol_name}' was not found."
        block, _ = _extract_block(content, start)
        description = re.search(r'\(property\s+"Description"\s+"([^"]*)"', block)
        keywords = re.search(r'\(property\s+"ki_keywords"\s+"([^"]*)"', block)
        datasheet = re.search(r'\(property\s+"Datasheet"\s+"([^"]*)"', block)
        footprint = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', block)
        pins = re.findall(
            r'\(pin\s+(\w+)\s+\w+.*?\(name\s+"([^"]*)".*?\(number\s+"([^"]*)"', block, re.DOTALL
        )
        lines = [f"Symbol: {library}:{symbol_name}"]
        if description:
            lines.append(f"- Description: {description.group(1)}")
        if keywords:
            lines.append(f"- Keywords: {keywords.group(1)}")
        if footprint:
            lines.append(f"- Default footprint: {footprint.group(1)}")
        if datasheet:
            lines.append(f"- Datasheet: {datasheet.group(1)}")
        if pins:
            lines.append(f"- Pins: {len(pins)}")
            for pin in pins[:20]:
                lines.append(f"  - {pin[2]} {pin[1]} ({pin[0]})")
        return "\n".join(lines)

    @mcp.tool()
    def lib_search_footprints(query: str, library_filter: str = "") -> str:
        """Search footprint libraries by footprint name."""
        root = _footprint_library_dir()
        results: list[str] = []
        for library in root.glob("*.pretty"):
            if library_filter and library_filter.lower() not in library.stem.lower():
                continue
            for footprint in library.glob("*.kicad_mod"):
                if query.lower() in footprint.stem.lower():
                    results.append(f"{library.stem}:{footprint.stem}")
        if not results:
            return f"No footprints matched '{query}'."
        lines = [f"Footprint matches for '{query}' ({len(results)} total):"]
        lines.extend(f"- {item}" for item in results[: get_config().max_items_per_response])
        return "\n".join(lines)

    @mcp.tool()
    def lib_list_footprints(library: str) -> str:
        """List footprints in a specific library."""
        library_dir = _footprint_library_dir() / f"{library}.pretty"
        if not library_dir.exists():
            return f"Footprint library '{library}' was not found."
        footprints = sorted(path.stem for path in library_dir.glob("*.kicad_mod"))
        lines = [f"Footprints in {library} ({len(footprints)} total):"]
        lines.extend(f"- {name}" for name in footprints[: get_config().max_items_per_response])
        return "\n".join(lines)

    @mcp.tool()
    def lib_rebuild_index() -> str:
        """Rebuild the in-memory symbol search index."""
        global _symbol_index
        with _symbol_index_lock:
            _symbol_index = _build_symbol_index()
            count = len(_symbol_index)
        return f"Rebuilt the symbol index with {count} entries."

    @mcp.tool()
    def lib_get_footprint_info(library: str, footprint: str) -> str:
        """Return details for a single footprint."""
        path = _footprint_file(library, footprint)
        if not path.exists():
            return f"Footprint '{library}:{footprint}' was not found."
        content = path.read_text(encoding="utf-8", errors="ignore")
        model_match = re.search(r'\(model\s+"([^"]+)"', content)
        return "\n".join(
            [
                f"Footprint: {library}:{footprint}",
                f"- File: {path}",
                f"- 3D model: {model_match.group(1) if model_match else '(none)'}",
            ]
        )

    @mcp.tool()
    def lib_get_footprint_3d_model(library: str, footprint: str) -> str:
        """Return the configured 3D model path for a footprint."""
        path = _footprint_file(library, footprint)
        if not path.exists():
            return f"Footprint '{library}:{footprint}' was not found."
        content = path.read_text(encoding="utf-8", errors="ignore")
        model_match = re.search(r'\(model\s+"([^"]+)"', content)
        if model_match is None:
            return f"Footprint '{library}:{footprint}' does not define a 3D model."
        return model_match.group(1)

    @mcp.tool()
    def lib_assign_footprint(reference: str, library: str, footprint: str) -> str:
        """Assign a footprint property to a schematic symbol."""
        path = _footprint_file(library, footprint)
        if not path.exists():
            return f"Footprint '{library}:{footprint}' was not found."
        assignment = f"{library}:{footprint}"
        update_symbol_property(reference, "Footprint", assignment)
        return f"Assigned footprint '{assignment}' to '{reference}'."

    @mcp.tool()
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
                f'\t\t\t(name "{pin_name}" (effects (font (size 1.27 1.27))))\n'
                f'\t\t\t(number "{pin_number}" (effects (font (size 1.27 1.27))))\n'
                "\t\t)\n"
            )
            y -= 2.54

        symbol_block = (
            f'\t(symbol "{name}"\n'
            '\t\t(property "Reference" "U" (id 0) (at 0 5.08 0) '
            "(effects (font (size 1.27 1.27))))\n"
            f'\t\t(property "Value" "{name}" (id 1) (at 0 -5.08 0) '
            "(effects (font (size 1.27 1.27))))\n" + "".join(pin_blocks) + "\t)\n"
        )
        if content.rstrip().endswith(")"):
            content = content.rstrip()[:-1] + f"\n{symbol_block})\n"
        else:
            content += symbol_block
        library_file.write_text(content, encoding="utf-8")
        return f"Created custom symbol '{name}' in {library_file}."

    @mcp.tool()
    def lib_get_datasheet_url(library: str, symbol_name: str) -> str:
        """Return a datasheet URL from the symbol library when available."""
        content = _read_symbol_file(library)
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
    def lib_search_components(
        keyword: str,
        package: str = "",
        only_basic: bool = True,
        source: str = "jlcsearch",
        min_stock: int = 10,
        sort_by: str = "price",
    ) -> str:
        """Search live component sources for purchasable parts."""
        try:
            client = _component_search_client(source)
            results = client.search(
                keyword,
                package=package or None,
                only_basic=only_basic,
                limit=min(get_config().max_items_per_response, 20),
            )
        except (RuntimeError, ValueError, OSError) as exc:
            return f"Live component search failed: {exc}"

        filtered = [item for item in results if item.stock >= min_stock]
        ordered = _sort_component_results(filtered, sort_by=sort_by)
        return _format_component_lines(
            f"Live component matches for '{keyword}' from {source} ({len(ordered)} total):",
            ordered,
        )

    @mcp.tool()
    def lib_get_component_details(lcsc_code_or_mpn: str, source: str = "jlcsearch") -> str:
        """Return live component detail for a specific LCSC code or MPN."""
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
        return "\n".join(lines)

    @mcp.tool()
    def lib_assign_lcsc_to_symbol(reference: str, lcsc_code: str) -> str:
        """Assign an LCSC part code to a schematic symbol property."""
        normalized = normalize_lcsc_code(lcsc_code)
        update_symbol_property(reference, "LCSC", normalized)
        return f"Assigned LCSC code '{normalized}' to '{reference}'."

    @mcp.tool()
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
            mpn = part.mpn if part is not None else row["value"]
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
                lines.append(f"- {row['reference']}: unresolved ({row['value']})")
                continue
            price = f"${part.price:.6f}" if part.price is not None else "(n/a)"
            lines.append(
                f"- {row['reference']}: {part.lcsc_code} | {part.mpn} | "
                f"stock {part.stock:,} | {price}"
            )
        return "\n".join(lines)

    @mcp.tool()
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
            and (
                max_price is None
                or item.price is None
                or item.price <= max_price
            )
        ]
        ordered = _sort_component_results(alternatives, sort_by="price")
        return _format_component_lines(
            f"Alternative parts for {base_part.lcsc_code} from {source} ({len(ordered)} total):",
            ordered,
            max_items=10,
        )
