"""Map live KiCad pads to their containing footprint instances."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class MappedPad:
    """One authoritative board pad enriched with its footprint reference."""

    pad: object
    pad_id: str | None
    reference: str | None


def pad_id(pad: object) -> str | None:
    """Return a stable KiCad pad identifier when the IPC object exposes one."""
    value = getattr(getattr(pad, "id", None), "value", None)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def footprint_reference(footprint: object) -> str | None:
    """Return a placed footprint reference through the supported field surface."""
    value = getattr(
        getattr(getattr(footprint, "reference_field", None), "text", None),
        "value",
        None,
    )
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def footprint_pads(footprint: object) -> list[object]:
    """Read pads from the official ``FootprintInstance.definition.pads`` relationship."""
    pads = getattr(getattr(footprint, "definition", None), "pads", None)
    if pads is None:
        return []
    try:
        return list(pads)
    except TypeError:
        return []


def map_pads_to_footprints(
    pads: Iterable[object],
    footprints: Iterable[object],
) -> list[MappedPad]:
    """Deduplicate board pads and enrich them with stable footprint references."""
    references: dict[str, str | None] = {}
    for footprint in footprints:
        reference = footprint_reference(footprint)
        for pad in footprint_pads(footprint):
            identifier = pad_id(pad)
            if identifier is None:
                continue
            if identifier not in references:
                references[identifier] = reference
            elif references[identifier] != reference:
                references[identifier] = None

    mapped: list[MappedPad] = []
    seen: set[tuple[str, str | int]] = set()
    for pad in pads:
        identifier = pad_id(pad)
        identity: tuple[str, str | int] = (
            ("id", identifier) if identifier is not None else ("object", id(pad))
        )
        if identity in seen:
            continue
        seen.add(identity)
        mapped.append(
            MappedPad(
                pad=pad,
                pad_id=identifier,
                reference=references.get(identifier) if identifier is not None else None,
            )
        )
    return mapped
