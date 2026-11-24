"""Regressions for low-level schematic library and pin-stub geometry helpers."""

from __future__ import annotations

import pytest

from kicad_mcp.tools import schematic


@pytest.mark.parametrize(
    ("coords", "result"),
    [
        ((10, 12, 10, 10, 0, 4, 0.1), (0.0, 1.0)),
        ((10, 8, 10, 10, 0, 4, 0.1), (0.0, -1.0)),
        ((14, 10, 10, 10, 0, 4, 0.1), (1.0, 0.0)),
        ((8, 10, 10, 10, 0, 4, 0.1), (-1.0, 0.0)),
        ((12, 10, 10, 10, 4, 0, 0.1), (1.0, 0.0)),
        ((8, 10, 10, 10, 4, 0, 0.1), (-1.0, 0.0)),
        ((10, 13, 10, 10, 4, 0, 0.1), (0.0, 1.0)),
        ((10, 7, 10, 10, 4, 0, 0.1), (0.0, -1.0)),
        ((10, 10, 10, 10, 4, 4, 0.1), None),
        ((10, 10, 10, 10, 0, 0, 0.1), None),
    ],
)
def test_degenerate_stub_geometry(
    coords: tuple[float, ...], result: tuple[float, float] | None
) -> None:
    assert schematic._degenerate_stub_direction(*coords) == result


def test_child_units_recognize_common_pin_unit_and_numbered_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def children(_block: str) -> list[tuple[str, str]]:
        return [
            ("Demo_0_1", "shared pins"),
            ("Demo_2_1", "unit2 pins"),
            ("Demo_3_1", "unit3 pins"),
            ("Demo_1_1", "unit1 pins"),
            ("Other_4_1", "unrelated pins"),
            ("Demo_invalid_1", "invalid pins"),
        ]

    monkeypatch.setattr(schematic, "_extract_child_symbol_blocks", children)
    monkeypatch.setattr(
        schematic,
        "_extract_pin_definitions",
        lambda block: {"1": (0.0, 0.0)} if "pins" in block else {},
    )
    units, common = schematic._child_units_from_block("Demo", "parent")
    assert units == {1, 2, 3}
    assert common is True  # preserve shared unit-zero pins even when numbered units exist


def test_available_units_fallback_for_shared_pins_or_root(monkeypatch: pytest.MonkeyPatch) -> None:
    def children(_b: str) -> list[tuple[str, str]]:
        return [("Demo_0_1", "common pins")]

    monkeypatch.setattr(schematic, "_extract_child_symbol_blocks", children)
    monkeypatch.setattr(schematic, "_symbol_block_name", lambda _block: "Demo")
    monkeypatch.setattr(schematic, "_strip_child_symbol_blocks", lambda _block: "no pins")
    monkeypatch.setattr(
        schematic,
        "_extract_pin_definitions",
        lambda block: {"1": (0.0, 0.0)} if "pins" in block else {},
    )
    assert schematic._available_units_from_blocks(["root"]) == {1}
    assert schematic._available_units_from_blocks([]) == set()
    monkeypatch.setattr(
        schematic, "_extract_child_symbol_blocks", lambda _block: [("Demo_2_1", "unit2 pins")]
    )
    assert schematic._available_units_from_blocks(["root"]) == {2}


def test_respace_positions_updates_only_changed_existing_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def find_block(content: str, ref: str):
        token = f"[{ref}]"
        start = content.find(token)
        if start < 0:
            return None
        return token, start, start + len(token), {"reference": ref}

    monkeypatch.setattr(schematic, "_find_placed_symbol_block", find_block)
    monkeypatch.setattr(
        schematic, "_shift_at_in_block", lambda block, dx, dy: f"{block}({dx:.1f},{dy:.1f})"
    )
    moved: list[str] = []
    result = schematic._respace_symbol_positions(
        "[R1] [R2]",
        {"R1": (1.0, 2.0), "R2": (4.0, 5.0), "R3": (0.0, 0.0)},
        {"R1": (3.0, 6.0), "R2": (4.0, 5.0), "R3": (1.0, 1.0)},
        moved,
    )
    assert result == "[R1](2.0,4.0) [R2]"
    assert moved == ["R1"]


def test_set_native_dnp_flag_preserves_insertion_order_and_errors() -> None:
    with_dnp = "(symbol\n\t\t(dnp no)\n\t\t(on_board yes)\n\t)"
    assert "(dnp yes)" in schematic._set_native_dnp_flag(with_dnp, "yes", "R1")
    assert "(dnp no)" not in schematic._set_native_dnp_flag(with_dnp, "yes", "R1")
    without_dnp = "(symbol\n\t\t(on_board yes)\n\t)"
    assert "(on_board yes)\n\t\t(dnp yes)" in schematic._set_native_dnp_flag(
        without_dnp, "yes", "R1"
    )
    before_instances = "(symbol\n\t\t(instances\n\t))"
    assert "(dnp yes)" in schematic._set_native_dnp_flag(before_instances, "yes", "R1")
    with pytest.raises(ValueError, match="Could not update native DNP"):
        schematic._set_native_dnp_flag("(symbol)", "yes", "R1")


def test_autoplace_visible_fields_preserves_missing_and_unchanged_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.utils.geometry import Box

    assert schematic._autoplace_visible_fields_for_ref("none", "R1", {}, {}) == ("none", False)
    content = """
(kicad_sch
  (symbol (lib_id "Device:R") (at 50 50 0)
    (property "Reference" "R1" (at 52.27 49.111 0)
      (effects (font (size 1.27 1.27)) (justify left)))
    (property "Value" "10K" (at 52.27 50.889 0)
      (effects (font (size 1.27 1.27)) (justify left)))))
"""
    body = Box(49, 47.5, 51, 52.5)
    pins = [(50.0, 46.2), (50.0, 53.8)]
    monkeypatch.setattr(schematic, "_symbol_body_and_pins", lambda _: (body, pins))
    assert schematic._autoplace_visible_fields_for_ref(
        content, "R1", {"R1": body}, {"R1": (body, pins)}
    ) == (content, False)
