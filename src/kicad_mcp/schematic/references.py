"""Reference generation helpers for schematic writers."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

UsedReferences = Callable[[Path, bool], set[str]]
"""Return the references used in the project.

Called as ``used(target, include_target)``: every schematic reachable from the
project's top-level sheet, plus ``target`` when ``include_target`` is true, or
minus ``target`` when it is false (the target is about to be replaced).
"""

_STRING = r'"((?:[^"\\]|\\.)*)"'
_REFERENCE_PROPERTY_RE = re.compile(r"\(property\s+\"Reference\"\s+" + _STRING)
_INSTANCE_REFERENCE_RE = re.compile(r"\(reference\s+" + _STRING + r"\s*\)")
_SHEETFILE_RE = re.compile(r"\(property\s+\"Sheetfile\"\s+" + _STRING)


def power_reference_from_uuid(uuid_value: str) -> str:
    """Return a validator-safe KiCad power-symbol reference from a UUID.

    KiCad power references use the ``#PWR`` prefix followed by decimal digits.
    Preserve the existing 16-bit UUID-prefix entropy while rendering it in base 10
    so every emitted reference satisfies that contract.
    """
    return f"#PWR{int(uuid_value[:4], 16)}"


def power_reference_prefix(value: str) -> str:
    """Return KiCad's reference prefix for a power symbol: ``#FLG`` or ``#PWR``."""
    return "#FLG" if value.strip().upper() == "PWR_FLAG" else "#PWR"


class PowerReferenceAllocator:
    """Hand out ``#PWR``/``#FLG`` references that no symbol in ``used`` has."""

    def __init__(self, used: Iterable[str]) -> None:
        self._used = set(used)
        self._next: dict[str, int] = {}

    def allocate(self, value: str) -> str:
        """Return the lowest free reference for a power symbol with this value."""
        prefix = power_reference_prefix(value)
        number = self._next.get(prefix, 1)
        while f"{prefix}{number:03d}" in self._used:
            number += 1
        reference = f"{prefix}{number:03d}"
        self._used.add(reference)
        self._next[prefix] = number + 1
        return reference


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def references_in_text(text: str) -> set[str]:
    """Return every Reference property and instance reference in schematic text."""
    return set(_REFERENCE_PROPERTY_RE.findall(text)) | set(_INSTANCE_REFERENCE_RE.findall(text))


def hierarchy_files(root_file: Path) -> list[Path]:
    """Return ``root_file`` and every schematic reachable from it through sheet blocks."""
    root = root_file.resolve()
    ordered: list[Path] = []
    pending = [root]
    seen: set[Path] = set()
    while pending:
        current = pending.pop(0)
        if current in seen:
            continue
        seen.add(current)
        text = _read(current)
        if text is None:
            continue
        ordered.append(current)
        pending.extend((current.parent / name).resolve() for name in _SHEETFILE_RE.findall(text))
    return ordered


def project_references(root_file: Path | None, target: Path, *, include_target: bool) -> set[str]:
    """Return references used across the hierarchy, with or without ``target``."""
    files = set(hierarchy_files(root_file)) if root_file is not None else set()
    resolved_target = target.resolve()
    if include_target:
        files.add(resolved_target)
    else:
        files.discard(resolved_target)
    used: set[str] = set()
    for file in files:
        text = _read(file)
        if text is not None:
            used |= references_in_text(text)
    return used
