"""Lossless, fail-closed staging for kicad-sch-api schematic saves.

Callers explicitly declare which symbols may move or which sheet may be added.
Every other KiCad root node must round-trip, including label connectivity,
title-block comments, text justification, and opaque future fields.
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from sexpdata import Symbol, loads

from ..errors import SchematicWriteUnsafeError


class _CanSave(Protocol):
    def save(self, path: Path, *, preserve_format: bool = True) -> object: ...


def _kind(node: object) -> str:
    if isinstance(node, list) and node:
        return str(node[0])
    return ""


def _canonical(value: object) -> object:
    if isinstance(value, Symbol):
        return ("symbol", str(value))
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, (int, float)):
        return ("number", f"{float(value):.12g}")
    if isinstance(value, list):
        return tuple(_canonical(child) for child in value)
    return value


def _symbol_reference(node: list[object]) -> str | None:
    for child in node[1:]:
        if _kind(child) == "property" and len(child) > 2 and child[1] == "Reference":
            return str(child[2])
    return None


def _expected_symbol(node: list[object], moved: set[str]) -> list[object]:
    if _symbol_reference(node) not in moved:
        return node
    result: list[object] = []
    found_at = False
    for child in node:
        if _kind(child) == "at":
            if not isinstance(child, list):
                raise SchematicWriteUnsafeError("Malformed symbol position")
            # Allow X/Y coordinate changes only; forbid angle, mirror or metadata changes.
            if len(child) != 4:
                raise SchematicWriteUnsafeError("Unexpected symbol location structure")
            result.append([child[0], "MOVED_XY", "MOVED_XY", child[3]])
            found_at = True
        else:
            result.append(child)
    if not found_at:
        raise SchematicWriteUnsafeError("Symbol position missing from serializer")
    return result


def _parse_nodes(content: str) -> list[list[object]]:
    try:
        parsed = loads(content)
    except Exception as exc:
        raise SchematicWriteUnsafeError("Could not parse staged KiCad schematic") from exc
    if not isinstance(parsed, list) or _kind(parsed) != "kicad_sch":
        raise SchematicWriteUnsafeError("Missing KiCad schematic root")
    return [v for v in parsed[1:] if isinstance(v, list)]


def _sheet_name(node: list[object]) -> str | None:
    for child in node[1:]:
        if _kind(child) == "property" and len(child) > 2 and child[1] == "Sheetname":
            return str(child[2])
    return None


def _safe_comparison(
    before: str,
    after: str,
    *,
    moved_references: Iterable[str] = (),
    added_sheet_name: str | None = None,
) -> bool:
    before_nodes = _parse_nodes(before)
    after_nodes = _parse_nodes(after)
    moved = set(moved_references)
    before_count = Counter(
        _canonical(_expected_symbol(node, moved) if _kind(node) == "symbol" else node)
        for node in before_nodes
    )
    added_sheet_found = 0
    after_normalized = []
    for node in after_nodes:
        if _kind(node) == "sheet" and added_sheet_name is not None:
            if _sheet_name(node) == added_sheet_name:
                added_sheet_found += 1
                continue
        after_normalized.append(
            _canonical(_expected_symbol(node, moved) if _kind(node) == "symbol" else node)
        )
    if added_sheet_found != (1 if added_sheet_name is not None else 0):
        raise SchematicWriteUnsafeError("Unexpected number or name of added schematic sheets")
    if before_count != Counter(after_normalized):
        raise SchematicWriteUnsafeError(
            "Refusing kicad-sch-api save: it modified schematic structure "
            "outside the requested symbol coordinates or added sheet."
        )
    return before != after


def guarded_kicad_api_save(
    schematic: _CanSave,
    path: Path,
    *,
    moved_references: Iterable[str] = (),
    added_sheet_name: str | None = None,
) -> bool:
    """Serialize beside the source, compare all nodes, and replace atomically.

    Return False when no file change is needed. Never write the source when
    a label, text justification, title metadata or other structure is lost.
    """
    target = path.resolve()
    original = target.read_bytes()
    fd, stage_name = tempfile.mkstemp(prefix=".kicad-safe-", suffix=".kicad_sch", dir=target.parent)
    os.close(fd)
    stage = Path(stage_name)
    try:
        schematic.save(stage, preserve_format=True)
        proposed = stage.read_bytes()
        changed = _safe_comparison(
            original.decode("utf-8"),
            proposed.decode("utf-8"),
            moved_references=moved_references,
            added_sheet_name=added_sheet_name,
        )
        if target.read_bytes() != original:
            raise SchematicWriteUnsafeError(
                "Refusing staged save: the target changed during serialization."
            )
        if changed:
            os.chmod(stage, stat.S_IMODE(target.stat().st_mode))
            stage.replace(target)
        return changed
    finally:
        stage.unlink(missing_ok=True)
