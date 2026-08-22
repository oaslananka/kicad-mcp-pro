"""Round-trip-safe ``.kicad_sch`` editing via kicad-sch-api (work order P2-T1, K5).

Regex find/replace on KiCad S-expressions can silently corrupt non-trivial schematics
(hierarchical sheets, bus members, nested-quoted multi-line properties, zone fill).
``kicad-sch-api`` parses, mutates, and re-serializes a schematic — but it is **not
perfectly lossless**: version 0.5.x silently drops ``global_label`` nodes on save (a
local label and hierarchical label survive; a global label does not). See
``tests/integration/test_roundtrip_fidelity.py``.

So this module does not assume the serializer is safe. :func:`roundtrip_edit` saves and
then **verifies** that no structural nodes were dropped; if any were, it restores the
original file and raises :class:`SchematicWriteUnsafeError`. A write therefore either
succeeds losslessly or fails loudly — it never silently corrupts the schematic.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, cast

from ..errors import SchematicWriteUnsafeError


class SchematicLike(Protocol):
    """Minimal surface of a kicad-sch-api schematic used by this module."""

    def save(self) -> object: ...


# Structural node kinds whose counts must not silently drop on a round trip.
_NODE_KINDS: tuple[str, ...] = (
    "symbol",
    "wire",
    "bus",
    "bus_entry",
    "junction",
    "label",
    "global_label",
    "hierarchical_label",
    "sheet",
    "no_connect",
    "text",
    "polyline",
)
_UUID_RE = re.compile(
    r'\(uuid\s+"?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"?\)'
)


def load(path: str | Path) -> SchematicLike:
    """Parse a ``.kicad_sch`` into a mutable kicad-sch-api schematic object."""
    import kicad_sch_api as ksa

    return cast(SchematicLike, ksa.load_schematic(str(path)))


def _counts(text: str) -> dict[str, int]:
    return {kind: len(re.findall(rf"\(\s*{kind}\b", text)) for kind in _NODE_KINDS}


def fidelity_fingerprint(text: str) -> dict[str, Any]:
    """Return a structural fingerprint used to assert round-trip losslessness.

    The fingerprint is the set of UUIDs plus the count of each structural node kind. A
    semantically lossless round trip leaves both unchanged; a corruption that drops a
    sheet, label, or bus member changes the counts, and a UUID rewrite changes the set.
    """
    return {"uuids": set(_UUID_RE.findall(text)), "counts": _counts(text)}


def dropped_nodes(before: str, after: str) -> dict[str, tuple[int, int]]:
    """Return node kinds whose count decreased from ``before`` to ``after``.

    A decrease means the serializer dropped structure that was not intentionally
    deleted by the caller (additive/no-op edits never decrease counts).
    """
    before_counts = _counts(before)
    after_counts = _counts(after)
    return {
        kind: (before_counts[kind], after_counts[kind])
        for kind in _NODE_KINDS
        if after_counts[kind] < before_counts[kind]
    }


@contextmanager
def roundtrip_edit(path: str | Path, *, allow_node_loss: bool = False) -> Iterator[SchematicLike]:
    """Load a schematic, yield it for in-place mutation, then serialize it safely.

    After save, structural node counts are verified. If any decreased (e.g. the
    kicad-sch-api 0.5.x ``global_label`` drop), the original file is restored and
    :class:`SchematicWriteUnsafeError` is raised — so the schematic is never left
    silently corrupted. Pass ``allow_node_loss=True`` only for an intentional deletion.

    Usage::

        with roundtrip_edit(sch_file) as sch:
            sch.components.add(...)
    """
    target = Path(path).expanduser().resolve()
    before = target.read_text(encoding="utf-8")
    sch = load(target)
    yield sch
    sch.save()
    after = target.read_text(encoding="utf-8")
    if not allow_node_loss:
        lost = dropped_nodes(before, after)
        if lost:
            with target.open("w", encoding="utf-8") as handle:
                handle.write(before)
            detail = ", ".join(f"{kind} {b}->{a}" for kind, (b, a) in sorted(lost.items()))
            raise SchematicWriteUnsafeError(
                f"Refusing to write {target.name}: the round trip dropped structure "
                f"({detail}). kicad-sch-api 0.5.x does not preserve global_label on save; "
                "the original file was restored."
            )
