from __future__ import annotations

from kicad_mcp.schematic.references import power_reference_from_uuid


def test_power_reference_converts_hex_prefix_to_decimal_digits() -> None:
    assert power_reference_from_uuid("abcd1234-0000-0000-0000-000000000000") == "#PWR43981"
