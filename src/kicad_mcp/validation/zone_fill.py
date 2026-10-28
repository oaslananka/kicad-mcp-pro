"""Read-only evidence about copper-zone fill for the PCB quality gate.

Nothing here writes a board file. ``scan_zone_fill`` inspects the saved board text,
``fill_geometry_changes`` compares the stored fill with the fill of a refilled scratch copy
and ``drc_outcome_changes`` compares two DRC JSON reports, so a caller can tell whether the
fill stored in the board still matches what KiCad would compute.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

from .drc_report import Report, report_entries

_ZONE_START = re.compile(r"\(zone(?=[\s)])")
_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[()]')
_NAME = re.compile(r'\((?:net_name|net)\s+"((?:\\.|[^"\\])*)"\)')
_LAYERS = re.compile(r"\((?:layers|layer)((?:\s+\"(?:\\.|[^\"\\])*+\")++)\s*\)")
_LAYER_NAME = re.compile(r'"((?:\\.|[^"\\])*)"')
_FILL_ENABLED = re.compile(r"\(fill\s+yes[\s)]")
_FILLED_START = re.compile(r"\(filled_polygon(?=[\s)])")
_FILL_LAYER = re.compile(r'\(layer\s+"((?:\\.|[^"\\])*)"\)')
_UUID = re.compile(r'\(uuid\s+"([^"]*)"\)')
_NUMBER = r"(-?[\d.]+(?:e[+-]?\d+)?)"
_POINT = re.compile(rf"\((?:xy|start|mid|end)\s+{_NUMBER}\s+{_NUMBER}\)")
_OUTER_PAIR_NAME = "F&B.Cu"
_OUTER_PAIR = ("F.Cu", "B.Cu")
_WILDCARD_COPPER = "*.Cu"
_GEOMETRY_SCALE = 10_000  # 0.1 micrometre

_COMPARED_KEYS = ("violations", "unconnected_items")


@dataclass(frozen=True, slots=True)
class ZoneFillScan:
    """Result of inspecting every copper zone in a saved board."""

    copper_zones: int = 0
    unfilled: list[str] = field(default_factory=list)


def _zone_blocks(text: str) -> Iterator[str]:
    for start in _ZONE_START.finditer(text):
        depth = 0
        for token in _TOKEN.finditer(text, start.start()):
            if token.group() == "(":
                depth += 1
            elif token.group() == ")":
                depth -= 1
                if depth == 0:
                    yield text[start.start() : token.end()]
                    break


def _is_copper(layer: str) -> bool:
    return layer.endswith(".Cu")


def _intended_copper_layers(layers: list[str]) -> list[str]:
    """Expand a zone's layer list into the copper layers that each need their own fill.

    KiCad writes a zone on exactly the outer copper pair as the shorthand ``F&B.Cu``.
    """
    expanded: list[str] = []
    for layer in layers:
        names = _OUTER_PAIR if layer == _OUTER_PAIR_NAME else (layer,)
        expanded.extend(name for name in names if _is_copper(name) and name not in expanded)
    return expanded


def _filled_polygons(block: str, zone_layers: list[str]) -> list[tuple[str, tuple[int, ...]]]:
    """Return ``(layer, flattened coordinates)`` for every ``filled_polygon`` of a zone."""
    polygons: list[tuple[str, tuple[int, ...]]] = []
    for start in _FILLED_START.finditer(block):
        depth = 0
        for token in _TOKEN.finditer(block, start.start()):
            if token.group() == "(":
                depth += 1
            elif token.group() == ")":
                depth -= 1
                if depth == 0:
                    body = block[start.start() : token.end()]
                    layer_match = _FILL_LAYER.search(body)
                    layer = layer_match.group(1) if layer_match else ""
                    if not layer and len(zone_layers) == 1:
                        layer = zone_layers[0]
                    coords = tuple(
                        round(float(value) * _GEOMETRY_SCALE)
                        for pair in _POINT.finditer(body)
                        for value in pair.groups()
                    )
                    polygons.append((layer, coords))
                    break
    return polygons


def scan_zone_fill(board_text: str) -> ZoneFillScan:
    """Find copper zones that lack a stored fill on any of their copper layers.

    Rule areas (keepouts) and zones on non-copper layers are not copper pours and are
    skipped. A copper zone counts as filled only when every copper layer it is intended for
    (``F&B.Cu`` means ``F.Cu`` and ``B.Cu``) carries at least one ``filled_polygon``.
    """
    copper = 0
    unfilled: list[str] = []
    for block in _zone_blocks(board_text):
        layers_match = _LAYERS.search(block)
        if layers_match is None or "(keepout" in block:
            continue
        layers = _LAYER_NAME.findall(layers_match.group(1))
        intended = _intended_copper_layers(layers)
        if not intended:
            continue
        copper += 1
        filled = {layer for layer, _ in _filled_polygons(block, intended)}
        if _WILDCARD_COPPER in intended:
            # "*.Cu" cannot be expanded without the stackup: require some fill at least.
            missing = [] if filled else [_WILDCARD_COPPER]
        else:
            missing = [layer for layer in intended if layer not in filled]
        if not missing:
            continue
        name_match = _NAME.search(block)
        name = name_match.group(1) if name_match and name_match.group(1) else "(no net)"
        reason = "no stored fill" if _FILL_ENABLED.search(block) else "fill disabled"
        unfilled.append(
            f"zone on net {name} ({', '.join(layers)}): {reason} on {', '.join(missing)}"
        )
    return ZoneFillScan(copper_zones=copper, unfilled=unfilled)


def _fill_geometry(board_text: str) -> dict[tuple[str, str], Counter[tuple[int, ...]]]:
    """Normalised stored fill per ``(zone, layer)``.

    Each polygon is reduced to its sorted set of integer-nanometre-ish points, so the
    start vertex, winding direction and whitespace of the file do not matter.
    """
    geometry: dict[tuple[str, str], Counter[tuple[int, ...]]] = {}
    index = 0
    for block in _zone_blocks(board_text):
        layers_match = _LAYERS.search(block)
        if layers_match is None or "(keepout" in block:
            continue
        intended = _intended_copper_layers(_LAYER_NAME.findall(layers_match.group(1)))
        if not intended:
            continue
        uuid_match = _UUID.search(block)
        zone_id = uuid_match.group(1) if uuid_match else f"#{index}"
        index += 1
        for layer in intended:
            geometry[(zone_id, layer)] = Counter()
        for layer, coords in _filled_polygons(block, intended):
            pairs = sorted(zip(coords[0::2], coords[1::2], strict=False))
            polygon = tuple(value for pair in pairs for value in pair)
            geometry.setdefault((zone_id, layer), Counter())[polygon] += 1
    return geometry


def fill_geometry_changes(stored_text: str, refilled_text: str) -> list[str]:
    """Describe where a fresh refill's fill geometry differs from the stored fill.

    Both arguments are board texts: the original and the copy that KiCad refilled and
    saved. DRC output can be identical for different fills, so the geometry is compared.
    """
    stored = _fill_geometry(stored_text)
    fresh = _fill_geometry(refilled_text)
    changes: list[str] = []
    for key in sorted(stored.keys() | fresh.keys()):
        before = stored.get(key, Counter())
        after = fresh.get(key, Counter())
        if before == after:
            continue
        zone, layer = key
        changes.append(
            f"zone {zone} on {layer}: {sum(before.values())} stored polygon(s) vs "
            f"{sum(after.values())} after refill, {sum((before - after).values())} stored "
            f"polygon(s) differ"
        )
    return changes


def _signature(report: Report, key: str) -> Counter[tuple[str, tuple[str, ...]]]:
    signature: Counter[tuple[str, tuple[str, ...]]] = Counter()
    for entry in report_entries(report, key):
        items = entry.get("items")
        descriptions = (
            sorted(str(item.get("description", "")) for item in items if isinstance(item, dict))
            if isinstance(items, list)
            else []
        )
        signature[(str(entry.get("type", "")), tuple(descriptions))] += 1
    return signature


def drc_outcome_changes(stored: Report, refilled: Report) -> list[str]:
    """Describe how a fresh refill changes the DRC result compared with the stored fill."""
    changes: list[str] = []
    for key in _COMPARED_KEYS:
        before = _signature(stored, key)
        after = _signature(refilled, key)
        if before == after:
            continue
        gone = sum((before - after).values())
        new = sum((after - before).values())
        changes.append(
            f"{key} {sum(before.values())} -> {sum(after.values())} "
            f"({gone} no longer reported, {new} newly reported)"
        )
    return changes
