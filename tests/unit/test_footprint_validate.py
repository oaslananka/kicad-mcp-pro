"""IPC-7351B footprint validation (work order P4-T3)."""

from __future__ import annotations

from kicad_mcp.utils.footprint_gen import _chip_passive, generate_footprint, ipc_density_tag
from kicad_mcp.utils.footprint_validate import (
    check_footprint_documentation_layers,
    check_footprint_pad_count,
    count_numbered_pads,
    count_thru_hole_pads,
    expected_pin_count_from_package,
    parse_ipc_density,
    parse_smd_pads,
    validate_chip_footprint,
)


def _pads_text(numbers: list[str], pad_type: str = "smd") -> str:
    """Build minimal .kicad_mod pad lines for the given pad-number tokens."""
    return "\n".join(
        f'(pad "{num}" {pad_type} roundrect (at 0 0) (size 1 1) (layers "F.Cu"))' for num in numbers
    )


def test_generated_chip_footprint_validates_pass() -> None:
    # The generator and validator share the IPC nominal, so a generated footprint
    # must validate PASS against its own size/density.
    for size in ("0402", "0603", "0805", "1206"):
        text = _chip_passive(size, "B")
        pads = parse_smd_pads(text)
        assert len(pads) == 2, f"{size}: expected 2 pads, parsed {len(pads)}"
        result = validate_chip_footprint(size, pads, density="B")
        assert result.verdict == "PASS", f"{size}: {result.summary} {result.findings}"


def test_wrong_size_code_is_a_hard_fail() -> None:
    # An 0805 land pattern checked against 0402 is grossly oversized -> blocking FAIL.
    pads = parse_smd_pads(_chip_passive("0805", "B"))
    result = validate_chip_footprint("0402", pads, density="B")
    assert result.verdict == "FAIL"
    assert result.findings


def test_pad_count_other_than_two_fails() -> None:
    one_pad = (
        '(footprint "X" (pad "1" smd rect (at -0.5 0) (size 0.6 0.6) (layers F.Cu F.Mask F.Paste)))'
    )
    pads = parse_smd_pads(one_pad)
    assert len(pads) == 1
    result = validate_chip_footprint("0402", pads, density="B")
    assert result.verdict == "FAIL"
    assert "pad count" in result.findings[0]


def test_minor_deviation_warns_not_fails() -> None:
    pads = parse_smd_pads(_chip_passive("0805", "B"))
    # Nudge one pad width by ~0.15 mm: beyond the 0.12 tol but under the 0.24 fail.
    nudged = [
        type(pads[0])(num=pads[0].num, x=pads[0].x, y=pads[0].y, w=pads[0].w + 0.15, h=pads[0].h),
        pads[1],
    ]
    result = validate_chip_footprint("0805", nudged, density="B")
    assert result.verdict == "WARN"
    assert result.findings


def test_parse_smd_pads_reads_position_and_size() -> None:
    pads = parse_smd_pads(_chip_passive("0603", "B"))
    assert {pad.num for pad in pads} == {"1", "2"}
    # Pads are mirrored about the origin on the x-axis.
    assert pads[0].x == -pads[1].x
    assert pads[0].w == pads[1].w


# --- Pad-count vs package cross-check (issue #201) --------------------------


def test_expected_pin_count_from_package_reads_pin_count_families() -> None:
    assert expected_pin_count_from_package("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm") == 8
    assert expected_pin_count_from_package("Package_QFP:LQFP-48_7x7mm_P0.5mm") == 48
    assert expected_pin_count_from_package("Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm") == 32
    assert expected_pin_count_from_package("Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm") == 20
    assert expected_pin_count_from_package("Package_DIP:PDIP-16_W7.62mm") == 16


def test_expected_pin_count_handles_code_first_packages() -> None:
    # For SOT/TO the first number is a JEDEC code; the lead count follows it.
    assert expected_pin_count_from_package("Package_TO_SOT_SMD:SOT-23-5") == 5
    assert expected_pin_count_from_package("Package_TO_SOT_SMD:SOT-23-3") == 3
    assert expected_pin_count_from_package("Package_TO_SOT_THT:TO-252-3_TabPin2") == 3


def test_expected_pin_count_returns_none_when_ambiguous() -> None:
    # No explicit lead count, grid arrays, and plain chips are not certifiable here.
    for name in [
        "Package_TO_SOT_SMD:SOT-23",
        "Package_TO_SOT_SMD:SOT-223",
        "Package_BGA:BGA-256_17x17mm",
        "Resistor_SMD:R_0805_2012Metric",
        "Capacitor_SMD:C_0402_1005Metric",
    ]:
        assert expected_pin_count_from_package(name) is None, name


def test_count_numbered_pads_ignores_mechanical_and_grid_pads() -> None:
    assert count_numbered_pads(_pads_text(["1", "2", "3", "4"])) == 4
    # Distinct integers only; an exposed pad numbered "5" counts, "" / "0" do not.
    assert count_numbered_pads(_pads_text(["1", "2", "5", "", "0"])) == 3
    # np_thru_hole mounting holes are not signal pins.
    assert (
        count_numbered_pads(_pads_text(["1", "2"]) + "\n" + _pads_text([""], "np_thru_hole")) == 2
    )


def test_check_footprint_pad_count_matches_and_misses() -> None:
    soic8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    ok = check_footprint_pad_count(soic8, _pads_text(["1", "2", "3", "4", "5", "6", "7", "8"]))
    assert ok is not None
    assert ok.verdict == "PASS"

    missing = check_footprint_pad_count(soic8, _pads_text(["1", "2", "3", "4", "5", "6"]))
    assert missing is not None
    assert missing.verdict == "FAIL"
    assert missing.findings

    # QFN-32 with an exposed thermal pad (33 numbered pads) passes within tolerance.
    qfn = "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm"
    exposed = check_footprint_pad_count(qfn, _pads_text([str(n) for n in range(1, 34)]))
    assert exposed is not None
    assert exposed.verdict == "PASS"

    # Far too many pads warns.
    too_many = check_footprint_pad_count(soic8, _pads_text([str(n) for n in range(1, 13)]))
    assert too_many is not None
    assert too_many.verdict == "WARN"

    # An uncertifiable package name yields no finding.
    assert (
        check_footprint_pad_count("Resistor_SMD:R_0805_2012Metric", _pads_text(["1", "2"])) is None
    )


_FULL_FP = (
    '(fp_line (start -1 -1) (end 1 -1) (layer "F.CrtYd"))\n'
    '(fp_line (start -1 -1) (end 1 -1) (layer "F.Fab"))\n'
    '(fp_line (start -1 -1) (end 1 -1) (layer "F.SilkS"))\n'
)


def test_documentation_layers_pass_when_all_present() -> None:
    result = check_footprint_documentation_layers(_FULL_FP)
    assert result.verdict == "PASS"


def test_documentation_layers_accept_supported_geometry_primitives() -> None:
    geometry = (
        '(fp_curve (pts (xy 0 0) (xy 1 0) (xy 1 1) (xy 0 1)) (layer "F.CrtYd"))\n'
        '(fp_rect (start -1 -1) (end 1 1) (layer "F.Fab"))\n'
        '(fp_circle (center 0 0) (end 1 0) (layer "F.SilkS"))\n'
    )

    result = check_footprint_documentation_layers(geometry)

    assert result.verdict == "PASS"


def test_documentation_layers_ignore_layer_names_in_descriptive_text() -> None:
    fake = '(footprint "X" (descr "mentions F.CrtYd and F.Fab and F.SilkS in prose"))'

    result = check_footprint_documentation_layers(fake)

    assert result.verdict == "FAIL"
    assert any("courtyard" in finding for finding in result.findings)


def test_documentation_layers_ignore_non_geometry_items_on_documentation_layers() -> None:
    text_only = (
        '(fp_text reference "REF**" (at 0 0) (layer "F.SilkS"))\n'
        '(fp_text user "F.Fab" (at 0 0) (layer "F.Fab"))\n'
        '(fp_text user "F.CrtYd" (at 0 0) (layer "F.CrtYd"))\n'
    )

    result = check_footprint_documentation_layers(text_only)

    assert result.verdict == "FAIL"
    assert any("courtyard" in finding for finding in result.findings)


def test_documentation_layers_fail_without_courtyard() -> None:
    no_courtyard = (
        '(fp_line (start -1 -1) (end 1 -1) (layer "F.Fab"))\n'
        '(fp_line (start -1 -1) (end 1 -1) (layer "F.SilkS"))\n'
    )
    result = check_footprint_documentation_layers(no_courtyard)
    assert result.verdict == "FAIL"
    assert any("courtyard" in f for f in result.findings)


def test_documentation_layers_warn_when_fab_or_silk_missing() -> None:
    only_courtyard = '(fp_poly (pts (xy 0 0)) (layer "B.CrtYd"))\n'
    result = check_footprint_documentation_layers(only_courtyard)
    assert result.verdict == "WARN"
    assert any("fabrication" in f for f in result.findings)
    assert any("silkscreen" in f for f in result.findings)


# --- Generated footprints carry the IPC-7351 density used (issue #201) ------


def test_generated_chip_footprint_records_its_density() -> None:
    for density in ("A", "B", "C"):
        text = _chip_passive("0805", density)  # type: ignore[arg-type]
        assert ipc_density_tag(density) in text  # type: ignore[arg-type]
        assert parse_ipc_density(text) == density


def test_generated_qfp_footprint_records_its_density() -> None:
    text = generate_footprint("QFN", pin_count=32, pitch_mm=0.5, body_l_mm=5.0, density="A")
    assert parse_ipc_density(text) == "A"


def test_parse_ipc_density_is_none_when_absent() -> None:
    assert parse_ipc_density(_pads_text(["1", "2"])) is None


def test_count_thru_hole_pads_sees_what_parse_smd_pads_cannot() -> None:
    # parse_smd_pads() matches `smd` only, so a through-hole footprint reads as
    # zero pads. The THT counter is what lets callers tell "no pads" apart from
    # "pads this parser does not cover".
    text = _pads_text(["1", "2"], pad_type="thru_hole")
    assert parse_smd_pads(text) == []
    assert count_thru_hole_pads(text) == 2


def test_count_thru_hole_pads_ignores_smd_pads() -> None:
    assert count_thru_hole_pads(_pads_text(["1", "2"], pad_type="smd")) == 0


def test_count_thru_hole_pads_counts_np_thru_hole() -> None:
    assert count_thru_hole_pads(_pads_text(["1"], pad_type="np_thru_hole")) == 1
