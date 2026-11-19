"""Hierarchical symbol instance paths.

KiCad keys each placed symbol by the sheet path from the top-level schematic:
``/<root uuid>`` on the root sheet and ``/<root uuid>/<sheet uuid>[/...]`` for a
child sheet, where each ``<sheet uuid>`` is the UUID of the ``(sheet ...)`` block
in its parent (not the UUID inside the child file). A writer that uses the
edited file's own UUID puts child-sheet symbols on a path that does not exist in
the hierarchy.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from ..utils.sexpr import _extract_block
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


def project_instance_paths(root_file: Path) -> set[str] | None:
    """Enumerate actual root-to-sheet UUID paths, including reused-sheet instances.

    Restrict traversal to the project root directory; a sheet filename must not
    make BOM inspection read unrelated files outside the active project.
    """
    root = root_file.resolve()
    root_text = _read(root)
    root_uuid = schematic_uuid(root_text) if root_text is not None else ""
    if not root_uuid:
        return None
    valid = {f"/{root_uuid}"}

    def visit(file: Path, text: str, prefix: str, seen: frozenset[Path]) -> None:
        for sheet in parse_sheet_blocks(text):
            if not sheet.filename or not sheet.uuid:
                continue
            child = (file.parent / sheet.filename).resolve()
            if not child.is_relative_to(root.parent) or child in seen:
                continue
            child_text = _read(child)
            if child_text is None:
                continue
            child_path = f"{prefix}/{sheet.uuid}"
            valid.add(child_path)
            visit(child, child_text, child_path, seen | {child})

    visit(root, root_text, f"/{root_uuid}", frozenset({root}))
    return valid


def _replace_reference_text(text: str, old: str, new: str) -> str:
    """Change only matching instance-reference nodes in a scoped text span."""
    pattern = re.compile(r'(\(reference\s+)"' + re.escape(old) + r'"(\))')
    return pattern.sub(lambda m: f'{m.group(1)}"{new}"{m.group(2)}', text)


def rewrite_symbol_instance_reference(
    symbol_block: str, old: str, new: str, project_name: str = ""
) -> str:
    """Keep KiCad's symbol instance references aligned with the display property.

    For copied sheets, never touch the instance data belonging to a foreign
    project. Legacy KiCad instance blocks without a project wrapper retain
    their original path semantics.
    """
    start = symbol_block.find("(instances")
    if start < 0 or old == new:
        return symbol_block
    instances, size = _extract_block(symbol_block, start)
    if not instances or size <= 0:
        return symbol_block
    if "(project " not in instances or not project_name:
        changed = _replace_reference_text(instances, old, new)
    else:
        changed = instances
        edits: list[tuple[int, int, str]] = []
        cursor = 0
        while (at := instances.find("(project ", cursor)) >= 0:
            project, consumed = _extract_block(instances, at)
            cursor = at + max(consumed, 1)
            name = re.match(r'\(project\s+"([^"]+)"', project)
            if name is not None and name.group(1) == project_name:
                edits.append((at, cursor, _replace_reference_text(project, old, new)))
        for begin, end, replacement in reversed(edits):
            changed = changed[:begin] + replacement + changed[end:]
    return symbol_block[:start] + changed + symbol_block[start + size :]


def rewrite_placed_symbol_references(
    schematic_text: str, updates: list[tuple[str, str]], project_name: str = ""
) -> str:
    """Apply an annotation map to each placed symbol without cascading renames.

    Symbol block isolation avoids confusing library definitions with placed
    symbols and makes sequential moves such as R1->R2, R2->R3 independent.
    """
    queues: dict[str, deque[str]] = defaultdict(deque)
    for old, new in updates:
        queues[old].append(new)
    replacements: list[tuple[int, int, str]] = []
    cursor = 0
    while (at := schematic_text.find("(symbol", cursor)) >= 0:
        block, size = _extract_block(schematic_text, at)
        cursor = at + max(size, 1)
        if not block or not re.search(r'\(lib_id\s+"', block):
            continue
        match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        if match is None or not queues[match.group(1)]:
            continue
        old = match.group(1)
        new = queues[old].popleft()
        property_changed = block[: match.start(1)] + new + block[match.end(1) :]
        rewritten = rewrite_symbol_instance_reference(property_changed, old, new, project_name)
        replacements.append((at, at + size, rewritten))
    if not replacements:
        # Compatibility for older injected test emitters without symbol blocks.
        updated = schematic_text
        for old, new in updates:
            updated = updated.replace(
                f'(property "Reference" "{old}"', f'(property "Reference" "{new}"', 1
            )
        return updated
    result = schematic_text
    for begin, end, replacement in reversed(replacements):
        result = result[:begin] + replacement + result[end:]
    return result
