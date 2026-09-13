"""Reference generation helpers for schematic writers."""

from __future__ import annotations


def power_reference_from_uuid(uuid_value: str) -> str:
    """Return a validator-safe KiCad power-symbol reference from a UUID.

    KiCad power references use the ``#PWR`` prefix followed by decimal digits.
    Preserve the existing 16-bit UUID-prefix entropy while rendering it in base 10
    so every emitted reference satisfies that contract.
    """
    return f"#PWR{int(uuid_value[:4], 16)}"
