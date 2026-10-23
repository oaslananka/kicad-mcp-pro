"""Headless Specctra SES -> .kicad_pcb applier (work order P4-T1)."""

from __future__ import annotations

import pytest

from kicad_mcp.utils.router_core import (
    apply_ses_to_pcb,
    parse_net_numbers,
    parse_ses,
    render_pcb_items,
)

# KiCad's Specctra convention: 1 mm = 1000 units (um), board Y is negated in the session
# (board y=5 mm -> -5000). The applier scales by 1000 and un-flips Y back to board mm.
_SES = """(session test.dsn
  (routes
    (resolution um 10)
    (network_out
      (net "GND"
        (wire (path F.Cu 250 2500 -5000 11000 -5000) (type protect))
        (wire (path B.Cu 250 11000 -5000 11000 -6000))
        (via "Via[0-1]_600:300_um" 11000 -5000)
      )
      (net "VCC"
        (wire (path "F.Cu" 200 20000 -20000 25000 -20000))
      )
    )
  )
)"""

_PCB = '(kicad_pcb\n\t(version 20250216)\n\t(net 0 "")\n\t(net 1 "GND")\n\t(net 2 "VCC")\n)\n'


def test_parse_ses_scales_and_unflips_coordinates() -> None:
    route = parse_ses(_SES)
    assert route.units_per_mm == 1000.0  # (resolution um 10) -> coords are micrometres
    assert len(route.segments) == 3
    assert len(route.vias) == 1

    gnd_f = next(s for s in route.segments if s.net_name == "GND" and s.layer == "F.Cu")
    # 2500 units / 1000 = 2.5 mm; session Y is negated, so -5000 -> +5.0 mm board Y.
    assert gnd_f.start == (2.5, 5.0)
    assert gnd_f.end == (11.0, 5.0)
    assert gnd_f.width_mm == 0.25  # 250 units / 1000

    via = route.vias[0]
    assert via.at == (11.0, 5.0)
    # Padstack Via[0-1]_600:300_um -> 0.6 mm size, 0.3 mm drill.
    assert via.size_mm == 0.6
    assert via.drill_mm == 0.3
    assert via.layers == ("F.Cu", "B.Cu")


def test_parse_net_numbers_reads_the_pcb_net_table() -> None:
    assert parse_net_numbers(_PCB) == {"": 0, "GND": 1, "VCC": 2}


def test_apply_ses_is_deterministic_and_round_trip_safe() -> None:
    out_a, route = apply_ses_to_pcb(_PCB, _SES)
    out_b, _ = apply_ses_to_pcb(_PCB, _SES)

    # Byte-identical on re-apply (deterministic UUIDs, sorted, fixed formatting).
    assert out_a == out_b

    # The original document is preserved verbatim; routing is appended inside the block.
    assert "(version 20250216)" in out_a
    assert '(net 1 "GND")' in out_a
    assert out_a.rstrip().endswith(")")

    # Net names are mapped to numbers; GND -> 1, VCC -> 2.
    assert '(layer "F.Cu") (net 1)' in out_a  # GND segment
    assert '(layer "F.Cu") (net 2)' in out_a  # VCC segment
    assert '(via (at 11 5) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1)' in out_a
    # Three segments + one via were added.
    assert out_a.count("(segment ") == 3
    assert out_a.count("(via ") == 1


def test_apply_ses_is_idempotent_on_re_application() -> None:
    # Applying the SES to an already-routed board replaces (not duplicates) our items.
    once, _ = apply_ses_to_pcb(_PCB, _SES)
    twice, _ = apply_ses_to_pcb(once, _SES)
    assert once == twice
    assert twice.count("(segment ") == 3
    assert twice.count("(via ") == 1


def test_missing_ses_net_refuses_entire_import_instead_of_partial_routing() -> None:
    # The SES contains both GND and VCC. Previously the importer silently
    # wrote GND tracks while dropping every VCC track and reporting success.
    pcb_gnd_only = '(kicad_pcb\n\t(version 20250216)\n\t(net 1 "GND")\n)\n'
    with pytest.raises(ValueError, match="missing from the PCB net table: 'VCC'"):
        apply_ses_to_pcb(pcb_gnd_only, _SES)


def test_missing_via_only_net_refuses_import_without_inventing_copper() -> None:
    via_only = (
        "(session t.dsn (routes (resolution um 10) (network_out "
        '(net "GHOST" (via "Via[0-1]_600:300_um" 11000 -5000)))))'
    )
    with pytest.raises(ValueError, match="GHOST"):
        apply_ses_to_pcb(_PCB, via_only)


def test_unnamed_net_zero_refuses_import_even_if_table_declares_net_zero() -> None:
    unassigned = (
        "(session t.dsn (routes (resolution um 10) (network_out "
        '(net "" (wire (path F.Cu 250 2500 -5000 11000 -5000))))))'
    )
    with pytest.raises(ValueError, match="missing from the PCB net table"):
        apply_ses_to_pcb(_PCB, unassigned)


def test_render_helper_cannot_silently_drop_unknown_net() -> None:
    route = parse_ses(_SES)
    with pytest.raises(ValueError, match="missing from the PCB net table: 'VCC'"):
        render_pcb_items(route, {"GND": 1})


def test_modern_kicad_named_only_nets_fail_closed_before_numeric_write() -> None:
    modern = (
        "(kicad_pcb (version 20250216)"
        '(footprint "Example" (pad "1" smd rect (at 0 0) (size 1 1) '
        '(layers "F.Cu") (net "GND"))))'
    )
    with pytest.raises(ValueError, match="named-only net encoding"):
        apply_ses_to_pcb(modern, _SES)


def test_empty_route_leaves_the_board_unchanged() -> None:
    empty_ses = "(session x.dsn (routes (resolution um 10) (network_out)))"
    out, route = apply_ses_to_pcb(_PCB, empty_ses)
    assert out == _PCB
    assert route.segments == []


def test_render_pcb_items_orders_segments_before_vias_deterministically() -> None:
    route = parse_ses(_SES)
    rendered = render_pcb_items(route, {"GND": 1, "VCC": 2})
    assert rendered.index("(segment ") < rendered.index("(via ")
    # Stable order: same input -> same string.
    assert rendered == render_pcb_items(parse_ses(_SES), {"GND": 1, "VCC": 2})
