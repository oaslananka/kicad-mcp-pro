"""Strict source-sheet inventory for the native graph snapshot adapter."""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath
from uuid import UUID

from kicad_mcp.schematic.sheet_pins import (
    _block_end,
    _children,
    _uuid_value,
    parse_sheet_blocks,
    parse_skipped_sheet_blocks,
    schematic_uuid,
)

# Reviewed fixture formats and the actual KiCad 10.0.8 upgrade format.
_SUPPORTED_VERSIONS = frozenset({"20240101", "20250114", "20250316", "20260306"})
_VERSION = re.compile(r"\A\s*\(kicad_sch\s+\(version\s+(\d+)\)")
_MAX_SHEET_BYTES = 32 * 1024 * 1024
_MAX_INSTANCES = 4096


def _canonical_uuid(value: str) -> str:
    if not value or str(UUID(value)) != value:
        raise ValueError("invalid source sheet UUID")
    return value


def _safe_sheet_name(name: str) -> Path:
    path = Path(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or PureWindowsPath(name).drive
        or ".." in path.parts
        or path.suffix != ".kicad_sch"
    ):
        raise ValueError("unsafe source sheet filename")
    return path


def _read_sheet(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or linked source sheet")
    with path.open("rb") as stream:
        data = stream.read(_MAX_SHEET_BYTES + 1)
    if len(data) > _MAX_SHEET_BYTES:
        raise ValueError("source sheet exceeds safety limit")
    text = data.decode("utf-8")
    match = _VERSION.match(text)
    if match is None or match.group(1) not in _SUPPORTED_VERSIONS:
        raise ValueError("unsupported native schematic version")
    return text


def _placed_stamps(text: str) -> frozenset[str]:
    """Read only direct placed-symbol UUIDs, not library/pin UUIDs."""
    start = text.index("(kicad_sch")
    end = _block_end(text, start)
    if text[end:].strip():
        raise ValueError("unexpected trailing schematic content")
    stamps: set[str] = set()
    for tag, begin, finish in _children(text, start, end):
        if tag != "symbol":
            continue
        values = [
            _canonical_uuid(_uuid_value(text, child_start, child_end))
            for child_tag, child_start, child_end in _children(text, begin, finish)
            if child_tag == "uuid"
        ]
        if len(values) != 1 or values[0] in stamps:
            raise ValueError("invalid or duplicate placed symbol UUID")
        stamps.add(values[0])
    return frozenset(stamps)


def inspect_sheet_instances(
    root: Path, root_name: str, native_sources: tuple[str, ...]
) -> tuple[str, dict[str, tuple[str, str]], dict[str, frozenset[str]]]:
    """Enumerate reachable instances in a validated, isolated native source copy.

    Reused sheets remain distinct by full UUID path. Unreferenced sources remain
    tracked by the source manifest but are not claimed as part of the circuit.
    """
    start = _safe_sheet_name(root_name)
    root_text = _read_sheet(root / start)
    root_uuid = _canonical_uuid(schematic_uuid(root_text))
    sources = set(native_sources)
    sheets: dict[str, tuple[str, str]] = {}
    # Explicit stack avoids recursion and lets us reject cycles per ancestry.
    pending: list[tuple[Path, str, str, frozenset[Path]]] = [
        (start, f"/{root_uuid}", "/", frozenset())
    ]
    cache = {start: root_text}
    stamp_cache: dict[Path, frozenset[str]] = {}
    stamps: dict[str, frozenset[str]] = {}
    while pending:
        relative, instance, names, ancestors = pending.pop()
        if relative in ancestors or instance in sheets or len(sheets) >= _MAX_INSTANCES:
            raise ValueError("cyclic, duplicate or excessive sheet instances")
        if relative.as_posix() not in sources:
            raise ValueError("sheet is not in the validated project manifest")
        if relative not in cache:
            cache[relative] = _read_sheet(root / relative)
        text = cache[relative]
        if parse_skipped_sheet_blocks(text):
            raise ValueError("unaddressable native child sheet")
        sheets[instance] = (names, relative.name)
        if relative not in stamp_cache:
            stamp_cache[relative] = _placed_stamps(text)
        stamps[instance] = stamp_cache[relative]
        for sheet in parse_sheet_blocks(text):
            child = relative.parent / _safe_sheet_name(sheet.filename)
            child_id = _canonical_uuid(sheet.uuid)
            pending.append(
                (child, f"{instance}/{child_id}", f"{names}{sheet.name}/", ancestors | {relative})
            )
    return root_uuid, sheets, stamps
