"""Lossless, fail-closed staging for kicad-sch-api schematic saves.

Callers explicitly declare which symbols may move or which sheet may be added.
Every other KiCad root node must round-trip, including label connectivity,
title-block comments, text justification, and opaque future fields.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from sexpdata import Symbol, loads  # type: ignore[import-untyped]

from ..errors import SchematicWriteUnsafeError

_TAG_RE = re.compile(r"[a-zA-Z0-9_-]+")


class _CanSave(Protocol):
    def save(self, path: Path, /, *, preserve_format: bool) -> object: ...


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
        if (
            isinstance(child, list)
            and _kind(child) == "property"
            and len(child) > 2
            and child[1] == "Reference"
        ):
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
        if (
            isinstance(child, list)
            and _kind(child) == "property"
            and len(child) > 2
            and child[1] == "Sheetname"
        ):
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


def _unquoted_parentheses(source: str) -> Iterable[tuple[int, str]]:
    """Yield only structural parentheses; escaped quoted content stays opaque."""
    quoted = False
    escaped = False
    for index, char in enumerate(source):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "()":
            yield index, char
    if quoted:
        raise SchematicWriteUnsafeError("Unbalanced quoted schematic text")


def _root_child_span(source: str, start: int, end: int) -> tuple[str, int, int]:
    """Describe one complete direct child without reparsing its contents."""
    match = _TAG_RE.match(source, start + 1)
    return (match.group(0) if match else "", start, end)


def _root_children_spans(source: str) -> list[tuple[str, int, int]]:
    """Return root-child text offsets without interpreting quoted text as nodes."""
    depth = 0
    start = -1
    found: list[tuple[str, int, int]] = []
    for index, paren in _unquoted_parentheses(source):
        if paren == "(":
            if depth == 1:
                start = index
            depth += 1
        else:
            if depth == 2 and start >= 0:
                found.append(_root_child_span(source, start, index + 1))
                start = -1
            depth -= 1
    if depth != 0:
        raise SchematicWriteUnsafeError("Unbalanced schematic while locating symbol nodes")
    return found


def _direct_position(node: list[object]) -> tuple[float, float, float]:
    positions = [child for child in node[1:] if isinstance(child, list) and _kind(child) == "at"]
    if len(positions) != 1 or len(positions[0]) != 4:
        raise SchematicWriteUnsafeError("Expected exactly one direct symbol position")
    return (float(positions[0][1]), float(positions[0][2]), float(positions[0][3]))


def _symbol_identity(node: list[object]) -> tuple[str | None, int]:
    """A ref has distinct movable roots when the symbol has multiple units."""
    units = [
        child[1]
        for child in node[1:]
        if isinstance(child, list) and _kind(child) == "unit" and len(child) == 2
    ]
    if len(units) > 1:
        raise SchematicWriteUnsafeError("Symbol has multiple unit identifiers")
    unit = units[0] if units else 1
    if not isinstance(unit, int) or isinstance(unit, bool) or unit < 1:
        raise SchematicWriteUnsafeError("Invalid symbol unit identifier")
    return _symbol_reference(node), unit


def _mapped_symbols(content: str) -> dict[tuple[str | None, int], list[object]]:
    symbols: dict[tuple[str | None, int], list[object]] = {}
    for node in _parse_nodes(content):
        if _kind(node) != "symbol":
            continue
        identity = _symbol_identity(node)
        if identity in symbols:
            raise SchematicWriteUnsafeError("Duplicate symbol reference and unit")
        symbols[identity] = node
    return symbols


def _validated_moved_units(
    original: str, serialized: str, moved_references: set[str]
) -> tuple[
    dict[tuple[str | None, int], list[object]],
    dict[tuple[str | None, int], list[object]],
    set[tuple[str | None, int]],
]:
    before = _mapped_symbols(original)
    after = _mapped_symbols(serialized)
    if not moved_references.issubset({identity[0] for identity in before}):
        raise SchematicWriteUnsafeError("Requested symbol reference is missing from source")
    requested = {key for key in before if key[0] in moved_references}
    if not requested.issubset(after):
        raise SchematicWriteUnsafeError(
            "Requested symbol reference or unit is missing from staged save"
        )
    for identity in requested:
        old_symbol, staged_symbol = before[identity], after[identity]
        if _direct_position(old_symbol)[2] != _direct_position(staged_symbol)[2]:
            raise SchematicWriteUnsafeError("Staged serializer unexpectedly rotated a symbol")
        for tag in ("lib_id", "uuid"):
            old_values = [
                child for child in old_symbol[1:] if isinstance(child, list) and _kind(child) == tag
            ]
            staged_values = [
                child
                for child in staged_symbol[1:]
                if isinstance(child, list) and _kind(child) == tag
            ]
            if old_values != staged_values:
                raise SchematicWriteUnsafeError("Staged symbol identity changed")
    return before, after, requested


def _coordinate_patch(raw: str, x: float, y: float) -> tuple[int, int, str]:
    positions = [(start, end) for name, start, end in _root_children_spans(raw) if name == "at"]
    if len(positions) != 1:
        raise SchematicWriteUnsafeError("Cannot identify one direct symbol position")
    start, end = positions[0]
    match = re.fullmatch(
        r"(\(at\s+)([-+\d.]+)(\s+)([-+\d.]+)(\s+[-+\d.]+\s*\))",
        raw[start:end],
    )
    if match is None:
        raise SchematicWriteUnsafeError("Unexpected KiCad symbol coordinate format")
    return start, end, f"{match.group(1)}{x:.6f}{match.group(3)}{y:.6f}{match.group(5)}"


def _collect_position_patches(
    original: str,
    before: dict[tuple[str | None, int], list[object]],
    after: dict[tuple[str | None, int], list[object]],
    requested: set[tuple[str | None, int]],
) -> list[tuple[int, int, str]]:
    patches: list[tuple[int, int, str]] = []
    seen: set[tuple[str | None, int]] = set()
    for tag, start, end in _root_children_spans(original):
        if tag != "symbol":
            continue
        raw = original[start:end]
        identity = _symbol_identity(loads(raw))
        if identity not in requested:
            continue
        seen.add(identity)
        new_xy = _direct_position(after[identity])
        if new_xy[:2] != _direct_position(before[identity])[:2]:
            local_start, local_end, replacement = _coordinate_patch(raw, *new_xy[:2])
            patches.append((start + local_start, start + local_end, replacement))
    if seen != requested:
        raise SchematicWriteUnsafeError("Some symbol units were not found in source text")
    return patches


def _merge_only_symbol_positions(original: str, serialized: str, moved_references: set[str]) -> str:
    """Transfer only requested symbol X/Y; preserve all other original bytes."""
    before, after, requested = _validated_moved_units(original, serialized, moved_references)
    patches = _collect_position_patches(original, before, after, requested)
    updated = original
    for start, end, replacement in reversed(patches):
        updated = updated[:start] + replacement + updated[end:]
    _safe_comparison(original, updated, moved_references=moved_references)
    return updated


def _create_validated_stage(target: Path, candidate: bytes, original_mode: int) -> Path:
    """Create new, non-reopened staging inode; no user path enters its write API."""
    fd, name = tempfile.mkstemp(prefix=".kicad-validated-", suffix=".kicad_sch", dir=target.parent)
    stage = Path(name)
    try:
        with os.fdopen(fd, "wb") as destination:
            destination.write(candidate)
            destination.flush()
        os.chmod(stage, original_mode)
        return stage
    except BaseException:
        stage.unlink(missing_ok=True)
        raise


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
    # Coordinate with the existing transactional tools using their shared lock.
    # Lazy import avoids a module initialization cycle through the schematic API.
    from ..tools.schematic import _SCHEMATIC_WRITE_LOCK

    with _SCHEMATIC_WRITE_LOCK:
        target = path.resolve()
        original = target.read_bytes()
        fd, stage_name = tempfile.mkstemp(
            prefix=".kicad-safe-", suffix=".kicad_sch", dir=target.parent
        )
        os.close(fd)
        stage = Path(stage_name)
        try:
            schematic.save(stage, preserve_format=True)
            serialized = stage.read_bytes().decode("utf-8")
            source = original.decode("utf-8")
            moved = set(moved_references)
            if moved and added_sheet_name is None:
                # kicad-sch-api drops KiCad 10 fields during serialize. Do not
                # trust its whole-file output: transfer requested XY values only.
                candidate = _merge_only_symbol_positions(source, serialized, moved)
            else:
                candidate = serialized
            changed = _safe_comparison(
                source,
                candidate,
                moved_references=moved,
                added_sheet_name=added_sheet_name,
            )
            if target.read_bytes() != original:
                raise SchematicWriteUnsafeError(
                    "Refusing staged save: the target changed during serialization."
                )
            if changed:
                validated = _create_validated_stage(
                    target, candidate.encode("utf-8"), stat.S_IMODE(target.stat().st_mode)
                )
                try:
                    # Never trust the serializer's original temporary path for
                    # writes: only the protected mkstemp file descriptor owns
                    # the complete, structurally validated replacement bytes.
                    if target.read_bytes() != original:
                        raise SchematicWriteUnsafeError("Target changed before atomic replacement")
                    validated.replace(target)
                finally:
                    validated.unlink(missing_ok=True)
            return changed
        finally:
            stage.unlink(missing_ok=True)
