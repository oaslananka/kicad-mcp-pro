"""Hierarchical symbol instance paths.

KiCad keys each placed symbol by the sheet path from the top-level schematic:
``/<root uuid>`` on the root sheet and ``/<root uuid>/<sheet uuid>[/...]`` for a
child sheet, where each ``<sheet uuid>`` is the UUID of the ``(sheet ...)`` block
in its parent (not the UUID inside the child file). A writer that uses the
edited file's own UUID puts child-sheet symbols on a path that does not exist in
the hierarchy.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from .sheet_pins import parse_sheet_blocks, schematic_uuid

InstancePathFor = Callable[[Path], str | None]
"""Return the instance path for symbols written into a schematic file, or ``None``."""


def no_instance_path(_target: Path) -> None:
    """Default resolver: no hierarchy known, so callers keep their own path."""
    return None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def find_instance_path(root_file: Path, target: Path) -> str | None:
    """Return the instance path of ``target`` in the hierarchy rooted at ``root_file``.

    The root itself gives ``/<root uuid>``. A child sheet gives the path of its
    first occurrence, depth-first in file order; a sheet used more than once
    still has its other instances added by KiCad's annotation. Returns ``None``
    when ``target`` is not reachable from ``root_file`` or a UUID is missing, so
    the caller can fall back to its previous behaviour.
    """
    root = root_file.resolve()
    wanted = target.resolve()
    root_text = _read(root)
    if root_text is None:
        return None
    root_uuid = schematic_uuid(root_text)
    if not root_uuid:
        return None

    def visit(file: Path, text: str, prefix: str, seen: frozenset[Path]) -> str | None:
        if file == wanted:
            return prefix
        for block in parse_sheet_blocks(text):
            if not block.uuid or not block.filename:
                continue
            child = (file.parent / block.filename).resolve()
            if child in seen:
                continue
            child_text = _read(child)
            if child_text is None:
                continue
            found = visit(child, child_text, f"{prefix}/{block.uuid}", seen | {child})
            if found is not None:
                return found
        return None

    return visit(root, root_text, f"/{root_uuid}", frozenset({root}))


class InstancePathKwargs(TypedDict, total=False):
    """Optional ``instance_path`` keyword for a symbol-block builder."""

    instance_path: str


def instance_path_kwargs(instance_path: str) -> InstancePathKwargs:
    """Pass ``instance_path`` only when known, so older injected builders keep working."""
    return {"instance_path": instance_path} if instance_path else {}
