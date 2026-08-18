"""IPC-7351B footprint generator for common SMD and through-hole packages.

Generates KiCad-format ``.kicad_mod`` S-expressions for standard packages using
IPC-7351B land-pattern formulas.  Supports density levels A (most-generous),
B (nominal, default), and C (least-land/most-compact).

Supported families
------------------
- Chip passives: 0201, 0402, 0603, 0805, 1206, 1210, 2512
- SOT-23 (3-lead), SOT-223 (3 leads + tab), SOT-89 (3 leads + tab).
- SOT-363 / SOT-26 (6-lead dual SOT)
- SC-70 / SOT-323 (3-lead small SOT)
- SOD-123 (2-pad SMD diode)
- SOD-323 (2-pad SMD diode, smaller)
- DO-214 variants: SMA / SMB / SMC (2-pad high-power diode)
- DPAK / TO-252 (3-lead + tab power package)
- D2PAK / TO-263 (3-lead + large tab power package)
- SOIC / SOP / SSOP / TSSOP (arbitrary pitch/pin-count)
- QFP / LQFP / TQFP (quad flat pack)
- QFN / DFN (quad flat no-lead with optional exposed pad)
- BGA (ball grid array, grid or depopulated)
- Through-hole pin header (1×N or 2×N, pitch 2.54 / 2.00 / 1.27 mm)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ..file_formats import GENERATED_SEXPR_DIALECT_VERSION
from .sexpr import _sexpr_string

DensityLevel = Literal["A", "B", "C"]

# IPC-7351B Table 3-1 land-pattern density offsets (mm)
# (Jt: toe, Jh: heel, Js: side)  — A=generous, B=nominal, C=compact
_IPC_OFFSETS: dict[DensityLevel, tuple[float, float, float]] = {
    "A": (0.55, 0.00, 0.05),
    "B": (0.35, 0.00, -0.05),
    "C": (0.15, 0.00, -0.10),
}

_LAYER_FAB = "F.Fab"
_LAYER_CU = "F.Cu"
_LAYER_MASK = "F.Mask"
_LAYER_PASTE = "F.Paste"
_LAYER_SILK = "F.SilkS"
_LAYER_CYARD = "F.CrtYd"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def ipc_density_tag(density: DensityLevel) -> str:
    """Return the machine-readable IPC-7351 density tag, e.g. ``IPC7351_B``."""
    return f"IPC7351_{density}"


def _fp_header(
    name: str, description: str, tags: str, density: DensityLevel | None = None
) -> list[str]:
    if density is not None:
        description = f"{description} (IPC-7351 density {density})"
        tags = f"{tags} {ipc_density_tag(density)}"
    return [
        f"(footprint {_sexpr_string(name)}",
        f"\t(version {GENERATED_SEXPR_DIALECT_VERSION})",
        '\t(generator "kicad-mcp-footprint-gen")',
        f"\t(layer {_sexpr_string(_LAYER_CU)})",
        f"\t(descr {_sexpr_string(description)})",
        f"\t(tags {_sexpr_string(tags)})",
        "\t(attr smd)",
    ]


def _fp_header_tht(name: str, description: str, tags: str) -> list[str]:
    return [
        f"(footprint {_sexpr_string(name)}",
        f"\t(version {GENERATED_SEXPR_DIALECT_VERSION})",
        '\t(generator "kicad-mcp-footprint-gen")',
        f"\t(layer {_sexpr_string(_LAYER_CU)})",
        f"\t(descr {_sexpr_string(description)})",
        f"\t(tags {_sexpr_string(tags)})",
    ]


def _pad_smd(num: int | str, x: float, y: float, w: float, h: float) -> str:
    return (
        f"\t(pad {num!r} smd rect (at {x:.4f} {y:.4f}) (size {w:.4f} {h:.4f})"
        f" (layers {_LAYER_CU} {_LAYER_MASK} {_LAYER_PASTE}))"
    )


def _pad_tht(num: int, x: float, y: float, drill: float, size: float) -> str:
    return (
        f"\t(pad {num!r} thru_hole circle (at {x:.4f} {y:.4f})"
        f" (size {size:.4f} {size:.4f}) (drill {drill:.4f})"
        f" (layers *.Cu *.Mask))"
    )


def _ref_value(ref_y: float, val_y: float, fab_y: float | None = None) -> list[str]:
    lines = [
        f'\t(fp_text reference "REF**" (at 0 {ref_y:.4f})'
        f" (layer {_LAYER_SILK}) (effects (font (size 1 1) (thickness 0.15))))",
        f'\t(fp_text value "VAL**" (at 0 {val_y:.4f})'
        f" (layer {_LAYER_FAB}) (effects (font (size 1 1) (thickness 0.15))))",
    ]
    if fab_y is not None:
        lines.append(
            f'\t(fp_text user "${{REFERENCE}}" (at 0 {fab_y:.4f})'
            f" (layer {_LAYER_FAB}) (effects (font (size 0.8 0.8) (thickness 0.12))))"
        )
    return lines


def _rect_line(
    layer: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    w: float = 0.1,
) -> list[str]:
    """Draw a rectangle on a layer as four line segments."""
    return [
        (
            f"\t(fp_line (start {x1:.4f} {y1:.4f}) (end {x2:.4f} {y1:.4f}) "
            f"(layer {layer}) (stroke (width {w})(type solid)))"
        ),
        (
            f"\t(fp_line (start {x2:.4f} {y1:.4f}) (end {x2:.4f} {y2:.4f}) "
            f"(layer {layer}) (stroke (width {w})(type solid)))"
        ),
        (
            f"\t(fp_line (start {x2:.4f} {y2:.4f}) (end {x1:.4f} {y2:.4f}) "
            f"(layer {layer}) (stroke (width {w})(type solid)))"
        ),
        (
            f"\t(fp_line (start {x1:.4f} {y2:.4f}) (end {x1:.4f} {y1:.4f}) "
            f"(layer {layer}) (stroke (width {w})(type solid)))"
        ),
    ]


def _circle_line(layer: str, cx: float, cy: float, r: float, w: float = 0.1) -> str:
    return (
        f"\t(fp_circle (center {cx:.4f} {cy:.4f}) (end {cx + r:.4f} {cy:.4f})"
        f" (layer {layer}) (stroke (width {w})(type solid)))"
    )


# ---------------------------------------------------------------------------
# Chip passives (0201 … 2512)
# ---------------------------------------------------------------------------

_CHIP_DIMS: dict[str, tuple[float, float, float, float]] = {
    # name: (body_L, body_W, land_L, land_W) mm  — IPC-7351B Table 7-7
    "0201": (0.60, 0.30, 0.35, 0.35),
    "0402": (1.00, 0.50, 0.50, 0.50),
    "0603": (1.55, 0.85, 0.70, 0.90),
    "0805": (2.00, 1.25, 0.90, 1.35),
    "1206": (3.20, 1.60, 1.30, 1.70),
    "1210": (3.20, 2.50, 1.30, 2.60),
    "2512": (6.40, 3.20, 1.80, 3.30),
}


@dataclass(frozen=True)
class ChipPadGeometry:
    """IPC-7351B nominal land geometry for a two-terminal chip package (mm)."""

    pad_w: float
    pad_h: float
    pad_offset: float  # |x| of each pad centre from the footprint origin

    @property
    def pitch(self) -> float:
        """Centre-to-centre distance between the two pads."""
        return 2.0 * self.pad_offset


def chip_pad_geometry(size_code: str, density: DensityLevel = "B") -> ChipPadGeometry:
    """Return the IPC-7351B nominal pad geometry for a chip package + density.

    Single source of truth shared by the generator and the validator so a footprint
    is checked against exactly what we would have generated.
    """
    if size_code not in _CHIP_DIMS:
        raise ValueError(f"Unknown chip size '{size_code}'. Choose from {sorted(_CHIP_DIMS)}")
    body_l, body_w, land_l, land_w = _CHIP_DIMS[size_code]
    _ = body_w
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_w = land_l + jt
    pad_h = land_w + 2 * js
    pad_offset = body_l / 2.0 + pad_w / 2.0
    return ChipPadGeometry(pad_w=pad_w, pad_h=pad_h, pad_offset=pad_offset)


def _chip_passive(size_code: str, density: DensityLevel = "B") -> str:
    """Generate a chip passive (resistor/capacitor/inductor) footprint."""
    body_l, body_w, _land_l, _land_w = _CHIP_DIMS[size_code]
    geometry = chip_pad_geometry(size_code, density)
    pad_w = geometry.pad_w
    pad_h = geometry.pad_h
    cx = geometry.pad_offset
    # Silk just outside body
    silk_x = body_l / 2.0 + 0.2
    silk_y = max(pad_h, body_w) / 2.0 + 0.2
    cyard_x = cx + pad_w / 2.0 + 0.25
    cyard_y = max(pad_h, body_w) / 2.0 + 0.25

    lines = _fp_header(
        f"C_{size_code}",
        f"Capacitor {size_code}",
        f"capacitor {size_code}",
        density,
    )
    lines += _ref_value(-(cyard_y + 0.5), cyard_y + 0.5, 0.0)
    # pads
    lines.append(_pad_smd(1, -cx, 0, pad_w, pad_h))
    lines.append(_pad_smd(2, cx, 0, pad_w, pad_h))
    # fab outline
    lines += _rect_line(_LAYER_FAB, -body_l / 2, -body_w / 2, body_l / 2, body_w / 2)
    # silk
    lines += _rect_line(_LAYER_SILK, -silk_x, -silk_y, silk_x, silk_y)
    # courtyard
    lines += _rect_line(_LAYER_CYARD, -cyard_x, -cyard_y, cyard_x, cyard_y, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SOT-23 / SOT-223 / SOT-89
# ---------------------------------------------------------------------------


def _sot23(density: DensityLevel = "B") -> str:
    """Generate SOT-23-3 (standard 3-lead SOT-23) footprint."""
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_w = 0.55 + jt
    pad_h = 0.70 + 2 * js
    # Pins 1,2 on left; pin 3 on right (centre)
    pitch = 0.95
    x_l = -1.45
    x_r = 1.45
    lines = _fp_header("SOT-23-3", "SOT-23 3-lead", "SOT-23 transistor", density)
    lines += _ref_value(-2.0, 2.0)
    lines.append(_pad_smd(1, x_l, -pitch / 2, pad_w, pad_h))
    lines.append(_pad_smd(2, x_l, pitch / 2, pad_w, pad_h))
    lines.append(_pad_smd(3, x_r, 0.0, pad_w, pad_h))
    lines += _rect_line(_LAYER_FAB, -1.3, -0.65, 1.3, 0.65)
    lines += _rect_line(_LAYER_CYARD, -1.85, -1.25, 1.85, 1.25, 0.05)
    lines.append(")")
    return "\n".join(lines)


def _sot223(density: DensityLevel = "B") -> str:
    """Generate SOT-223 with three leads plus tab pad tied to pin 2."""
    jt, _jh, js = _IPC_OFFSETS[density]
    lead_w = 0.85 + 2 * js
    lead_h = 1.50 + jt
    tab_w = 3.40 + 2 * js
    tab_h = 2.20 + jt
    pitch = 2.30
    y_lead = 3.15
    y_tab = -2.45
    lines = _fp_header(
        "SOT-223-3_TabPin2", "SOT-223 3-lead with tab", "SOT-223 regulator transistor", density
    )
    lines += _ref_value(-4.4, 4.4)
    lines.append(_pad_smd(1, -pitch, y_lead, lead_w, lead_h))
    lines.append(_pad_smd(2, 0.0, y_lead, lead_w, lead_h))
    lines.append(_pad_smd(3, pitch, y_lead, lead_w, lead_h))
    lines.append(_pad_smd(2, 0.0, y_tab, tab_w, tab_h))
    lines += _rect_line(_LAYER_FAB, -3.3, -2.25, 3.3, 2.25)
    lines.append(_circle_line(_LAYER_FAB, -2.7, 1.6, 0.18, 0.08))
    lines += _rect_line(_LAYER_CYARD, -4.05, -3.85, 4.05, 4.05, 0.05)
    lines.append(")")
    return "\n".join(lines)


def _sot89(density: DensityLevel = "B") -> str:
    """Generate SOT-89 with three leads plus tab pad tied to pin 2."""
    jt, _jh, js = _IPC_OFFSETS[density]
    lead_w = 0.55 + 2 * js
    lead_h = 1.20 + jt
    tab_w = 1.80 + 2 * js
    tab_h = 1.80 + jt
    pitch = 1.50
    y_lead = 2.00
    y_tab = -1.80
    lines = _fp_header(
        "SOT-89-3_TabPin2", "SOT-89 3-lead with tab", "SOT-89 regulator transistor", density
    )
    lines += _ref_value(-3.7, 3.7)
    lines.append(_pad_smd(1, -pitch, y_lead, lead_w, lead_h))
    lines.append(_pad_smd(2, 0.0, y_lead, lead_w, lead_h))
    lines.append(_pad_smd(3, pitch, y_lead, lead_w, lead_h))
    lines.append(_pad_smd(2, 0.0, y_tab, tab_w, tab_h))
    lines += _rect_line(_LAYER_FAB, -2.25, -1.55, 2.25, 1.55)
    lines.append(_circle_line(_LAYER_FAB, -1.75, 1.1, 0.15, 0.08))
    lines += _rect_line(_LAYER_CYARD, -2.75, -2.8, 2.75, 2.75, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SOT-363 / SOT-26 (6-lead dual SOT-23)
# ---------------------------------------------------------------------------


def _sot363(density: DensityLevel = "B") -> str:
    """Generate SOT-363 / SOT-26 (6-lead dual SOT-23) footprint.

    Three leads per side, 0.65 mm pitch, body 2.0 × 1.25 mm.
    """
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_w = 0.40 + jt
    pad_h = 0.55 + 2 * js
    pitch = 0.65
    x_l = -1.45
    x_r = 1.45
    lines = _fp_header(
        "SOT-363", "SOT-363 / SOT-26 6-lead dual SOT", "SOT-363 SOT-26 dual transistor", density
    )
    lines += _ref_value(-2.2, 2.2)
    # Left side: pins 1, 2, 3 (bottom to top)
    for i, pin in enumerate((1, 2, 3)):
        lines.append(_pad_smd(pin, x_l, pitch - i * pitch, pad_w, pad_h))
    # Right side: pins 4, 5, 6 (top to bottom)
    for i, pin in enumerate((4, 5, 6)):
        lines.append(_pad_smd(pin, x_r, -pitch + i * pitch, pad_w, pad_h))
    lines += _rect_line(_LAYER_FAB, -1.3, -0.65, 1.3, 0.65)
    lines += _rect_line(_LAYER_CYARD, -1.85, -1.30, 1.85, 1.30, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SC-70 / SOT-323 (3-lead small SOT-23 variant)
# ---------------------------------------------------------------------------


def _sc70(density: DensityLevel = "B") -> str:
    """Generate SC-70 / SOT-323 (3-lead, 0.65 mm pitch) footprint.

    Body 2.0 × 1.25 mm; pins 1 and 2 on left side, pin 3 on right.
    """
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_w = 0.40 + jt
    pad_h = 0.55 + 2 * js
    pitch = 0.65
    x_l = -1.15
    x_r = 1.15
    lines = _fp_header(
        "SC-70-3", "SC-70 / SOT-323 3-lead small SOT", "SC-70 SOT-323 transistor", density
    )
    lines += _ref_value(-1.8, 1.8)
    lines.append(_pad_smd(1, x_l, pitch / 2, pad_w, pad_h))
    lines.append(_pad_smd(2, x_l, -pitch / 2, pad_w, pad_h))
    lines.append(_pad_smd(3, x_r, 0.0, pad_w, pad_h))
    lines += _rect_line(_LAYER_FAB, -1.05, -0.65, 1.05, 0.65)
    lines += _rect_line(_LAYER_CYARD, -1.55, -1.10, 1.55, 1.10, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SOD-123 (2-pad SMD diode)
# ---------------------------------------------------------------------------

# IPC-7351 land dimensions for SOD-123 (body ≈ 4.50 × 2.68 mm)
_SOD123_BODY_L = 4.50
_SOD123_BODY_W = 2.68


def _sod123(density: DensityLevel = "B") -> str:
    """Generate SOD-123 SMD diode footprint (IPC-7351 land pattern)."""
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_w = 1.30 + jt
    pad_h = _SOD123_BODY_W + 2 * js
    cx = _SOD123_BODY_L / 2 + pad_w / 2
    cyard_x = cx + pad_w / 2 + 0.25
    cyard_y = pad_h / 2 + 0.25
    lines = _fp_header("SOD-123", "SOD-123 SMD diode", "diode SOD-123", density)
    lines += _ref_value(-(cyard_y + 0.5), cyard_y + 0.5, 0.0)
    # Pad 1 = cathode (left, marked with band), pad 2 = anode
    lines.append(_pad_smd(1, -cx, 0, pad_w, pad_h))
    lines.append(_pad_smd(2, cx, 0, pad_w, pad_h))
    # Body outline on Fab
    lines += _rect_line(
        _LAYER_FAB,
        -_SOD123_BODY_L / 2,
        -_SOD123_BODY_W / 2,
        _SOD123_BODY_L / 2,
        _SOD123_BODY_W / 2,
    )
    # Cathode bar on Fab (right side = cathode band)
    lines.append(
        f"\t(fp_line (start {-_SOD123_BODY_L / 2 + 0.6:.4f} {-_SOD123_BODY_W / 2:.4f})"
        f" (end {-_SOD123_BODY_L / 2 + 0.6:.4f} {_SOD123_BODY_W / 2:.4f})"
        f" (layer {_LAYER_FAB}) (stroke (width 0.2)(type solid)))"
    )
    # Silk
    lines += _rect_line(
        _LAYER_SILK,
        -_SOD123_BODY_L / 2 - 0.15,
        -cyard_y + 0.1,
        _SOD123_BODY_L / 2 + 0.15,
        cyard_y - 0.1,
    )
    # Courtyard
    lines += _rect_line(_LAYER_CYARD, -cyard_x, -cyard_y, cyard_x, cyard_y, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SOD-323 (2-pad SMD diode, smaller)
# ---------------------------------------------------------------------------

# Body ≈ 1.70 × 1.25 mm
_SOD323_BODY_L = 1.70
_SOD323_BODY_W = 1.25


def _sod323(density: DensityLevel = "B") -> str:
    """Generate SOD-323 SMD diode footprint (IPC-7351 land pattern)."""
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_w = 0.60 + jt
    pad_h = _SOD323_BODY_W + 2 * js
    cx = _SOD323_BODY_L / 2 + pad_w / 2
    cyard_x = cx + pad_w / 2 + 0.25
    cyard_y = pad_h / 2 + 0.25
    lines = _fp_header("SOD-323", "SOD-323 SMD diode (small)", "diode SOD-323", density)
    lines += _ref_value(-(cyard_y + 0.5), cyard_y + 0.5, 0.0)
    lines.append(_pad_smd(1, -cx, 0, pad_w, pad_h))
    lines.append(_pad_smd(2, cx, 0, pad_w, pad_h))
    lines += _rect_line(
        _LAYER_FAB,
        -_SOD323_BODY_L / 2,
        -_SOD323_BODY_W / 2,
        _SOD323_BODY_L / 2,
        _SOD323_BODY_W / 2,
    )
    lines.append(
        f"\t(fp_line (start {-_SOD323_BODY_L / 2 + 0.3:.4f} {-_SOD323_BODY_W / 2:.4f})"
        f" (end {-_SOD323_BODY_L / 2 + 0.3:.4f} {_SOD323_BODY_W / 2:.4f})"
        f" (layer {_LAYER_FAB}) (stroke (width 0.12)(type solid)))"
    )
    lines += _rect_line(_LAYER_CYARD, -cyard_x, -cyard_y, cyard_x, cyard_y, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DO-214 variants: SMA / SMB / SMC  (2-pad high-power SMD diode)
# ---------------------------------------------------------------------------

# (body_L, body_W, pad_H) for IPC-7351B density B
_DO214_DIMS: dict[str, tuple[float, float, float]] = {
    "SMA": (5.00, 3.60, 3.70),
    "SMB": (5.60, 4.32, 4.45),
    "SMC": (8.10, 6.40, 6.55),
}


def _do214(variant: str, density: DensityLevel = "B") -> str:
    """Generate DO-214 variant footprint (SMA / SMB / SMC)."""
    variant_up = variant.upper()
    if variant_up not in _DO214_DIMS:
        raise ValueError(f"DO-214 variant must be SMA, SMB, or SMC; got '{variant}'.")
    body_l, body_w, pad_h = _DO214_DIMS[variant_up]
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_w = 1.65 + jt  # land protrusion from body end
    pad_h_adj = pad_h + 2 * js
    cx = body_l / 2 + pad_w / 2
    cyard_x = cx + pad_w / 2 + 0.25
    cyard_y = pad_h_adj / 2 + 0.25
    name = f"DO-214{variant_up[-2:]}" if len(variant_up) > 3 else f"DO-214{variant_up[2:]}"
    name = f"D_{variant_up}"
    lines = _fp_header(
        name,
        f"DO-214 {variant_up} SMD diode",
        f"diode DO-214 {variant_up}",
        density,
    )
    lines += _ref_value(-(cyard_y + 0.5), cyard_y + 0.5, 0.0)
    lines.append(_pad_smd(1, -cx, 0, pad_w, pad_h_adj))  # cathode
    lines.append(_pad_smd(2, cx, 0, pad_w, pad_h_adj))  # anode
    lines += _rect_line(_LAYER_FAB, -body_l / 2, -body_w / 2, body_l / 2, body_w / 2)
    # Cathode bar
    lines.append(
        f"\t(fp_line (start {-body_l / 2 + 0.8:.4f} {-body_w / 2:.4f})"
        f" (end {-body_l / 2 + 0.8:.4f} {body_w / 2:.4f})"
        f" (layer {_LAYER_FAB}) (stroke (width 0.2)(type solid)))"
    )
    lines += _rect_line(_LAYER_CYARD, -cyard_x, -cyard_y, cyard_x, cyard_y, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DPAK / TO-252 and D2PAK / TO-263 (power packages with thermal tab)
# ---------------------------------------------------------------------------

# (body_L, body_W, lead_pitch, lead_len, tab_w, tab_h, y_leads, y_tab)
_DPAK_VARIANTS: dict[str, tuple[float, float, float, float, float, float, float, float]] = {
    "DPAK": (6.50, 6.00, 2.286, 1.50, 5.40, 3.20, 4.10, -2.40),
    "TO-252": (6.50, 6.00, 2.286, 1.50, 5.40, 3.20, 4.10, -2.40),
    "D2PAK": (10.10, 8.85, 2.286, 1.50, 8.60, 5.00, 6.35, -3.90),
    "TO-263": (10.10, 8.85, 2.286, 1.50, 8.60, 5.00, 6.35, -3.90),
}


def _dpak(variant: str, density: DensityLevel = "B") -> str:
    """Generate DPAK/TO-252 or D2PAK/TO-263 (3-lead + thermal tab) footprint."""
    variant_up = variant.upper()
    key = variant_up
    if key not in _DPAK_VARIANTS:
        raise ValueError(
            f"DPAK variant '{variant}' not recognised. Use DPAK, TO-252, D2PAK, or TO-263."
        )
    body_l, body_w, pitch, lead_len, tab_w, tab_h, y_leads, y_tab = _DPAK_VARIANTS[key]
    jt, _jh, js = _IPC_OFFSETS[density]
    lead_pad_w = 1.50 + 2 * js
    lead_pad_h = lead_len + jt
    tab_pad_w = tab_w + 2 * js
    tab_pad_h = tab_h + jt
    cyard_x = pitch + lead_pad_w / 2 + 0.25
    cyard_y_pos = y_leads + lead_pad_h / 2 + 0.25
    cyard_y_neg = abs(y_tab) + tab_pad_h / 2 + 0.25
    lines = _fp_header(
        "TO-252-3_TabPin2" if "DPAK" in key or "252" in key else "TO-263-3_TabPin2",
        f"{variant_up} 3-lead + tab power package",
        f"{variant_up} power transistor regulator",
        density,
    )
    lines += _ref_value(-(cyard_y_pos + 0.6), cyard_y_pos + 0.6)
    # Pin 1 (left), Pin 2 (centre, centre lead + tab), Pin 3 (right)
    lines.append(_pad_smd(1, -pitch, y_leads, lead_pad_w, lead_pad_h))
    lines.append(_pad_smd(2, 0.0, y_leads, lead_pad_w, lead_pad_h))
    lines.append(_pad_smd(3, pitch, y_leads, lead_pad_w, lead_pad_h))
    # Tab (exposed pad = pin 2)
    lines.append(_pad_smd(2, 0.0, y_tab, tab_pad_w, tab_pad_h))
    lines += _rect_line(_LAYER_FAB, -body_w / 2, -body_l / 2, body_w / 2, body_l / 2)
    lines += _rect_line(_LAYER_CYARD, -cyard_x, -cyard_y_neg, cyard_x, cyard_y_pos, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SOIC / SOP / SSOP / TSSOP (dual-in-line SMD)
# ---------------------------------------------------------------------------


def _soic(
    pin_count: int,
    pitch_mm: float = 1.27,
    body_w_mm: float = 3.9,
    density: DensityLevel = "B",
    family: str = "SOIC",
) -> str:
    """Generate SOIC/SOP/SSOP/TSSOP footprint."""
    if pin_count % 2 != 0 or pin_count < 4 or pin_count > 64:
        raise ValueError("pin_count must be an even number between 4 and 64.")
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_h = 1.60 + jt  # along body axis (IPC nominal lead length ~1.6mm)
    pad_w = pitch_mm * 0.7 + 2 * js
    n_per_side = pin_count // 2
    span = (n_per_side - 1) * pitch_mm
    # lead protrusion: 0.4mm past body edge
    x_centre = body_w_mm / 2 + 0.4 + pad_h / 2
    cyard_x = x_centre + pad_h / 2 + 0.25
    cyard_y = span / 2 + pad_w / 2 + 0.25
    name = f"{family}-{pin_count}_{pitch_mm:.2f}mm"
    lines = _fp_header(
        name, f"{family} {pin_count} leads {pitch_mm:.2f}mm pitch", family.lower(), density
    )
    lines += _ref_value(-(cyard_y + 0.6), cyard_y + 0.6)
    for i in range(n_per_side):
        y = -span / 2 + i * pitch_mm
        lines.append(_pad_smd(i + 1, -x_centre, y, pad_h, pad_w))
        lines.append(_pad_smd(pin_count - i, x_centre, y, pad_h, pad_w))
    # body outline
    bh = span + pitch_mm
    lines += _rect_line(_LAYER_FAB, -body_w_mm / 2, -bh / 2, body_w_mm / 2, bh / 2)
    # pin-1 marker
    lines.append(
        f"\t(fp_circle (center {-body_w_mm / 2 - 0.5:.4f} {-span / 2:.4f})"
        f" (end {-body_w_mm / 2 - 0.3:.4f} {-span / 2:.4f})"
        f" (layer {_LAYER_FAB}) (stroke (width 0.1)(type solid)))"
    )
    lines += _rect_line(_LAYER_CYARD, -cyard_x, -cyard_y, cyard_x, cyard_y, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# QFP / LQFP / TQFP (quad, 4-sided)
# ---------------------------------------------------------------------------


def _qfp(
    pin_count: int,
    pitch_mm: float = 0.5,
    body_l_mm: float = 10.0,
    body_w_mm: float | None = None,
    density: DensityLevel = "B",
    family: str = "LQFP",
) -> str:
    """Generate QFP/LQFP/TQFP footprint (square or rectangular body)."""
    if pin_count % 4 != 0 or pin_count < 32 or pin_count > 256:
        raise ValueError("pin_count must be divisible by 4, between 32 and 256.")
    body_w = body_w_mm or body_l_mm
    n_per_side = pin_count // 4
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_h = 1.50 + jt
    pad_w = pitch_mm - 0.10 + 2 * js
    span_tb = (n_per_side - 1) * pitch_mm  # top/bottom side span
    span_lr = span_tb  # square QFP
    x_centre = body_w / 2 + 0.6 + pad_h / 2
    y_centre = body_l_mm / 2 + 0.6 + pad_h / 2
    cyard = max(x_centre, y_centre) + pad_h / 2 + 0.25
    name = f"{family}-{pin_count}_{pitch_mm:.2f}mm_{body_l_mm:.0f}x{body_w:.0f}mm"
    lines = _fp_header(
        name, f"{family} {pin_count} leads {pitch_mm:.2f}mm pitch", family.lower(), density
    )
    lines += _ref_value(-(cyard + 0.6), cyard + 0.6)
    # Bottom side (pins 1…n_per_side), going right-to-left
    for i in range(n_per_side):
        x = -span_tb / 2 + i * pitch_mm
        lines.append(_pad_smd(i + 1, x, y_centre, pad_w, pad_h))
    # Right side (n_per_side+1 … 2n), top-to-bottom
    for i in range(n_per_side):
        y = -span_lr / 2 + i * pitch_mm
        lines.append(_pad_smd(n_per_side + i + 1, x_centre, y, pad_h, pad_w))
    # Top side (2n+1 … 3n), right-to-left
    for i in range(n_per_side):
        x = span_tb / 2 - i * pitch_mm
        lines.append(_pad_smd(2 * n_per_side + i + 1, x, -y_centre, pad_w, pad_h))
    # Left side (3n+1 … 4n), bottom-to-top
    for i in range(n_per_side):
        y = span_lr / 2 - i * pitch_mm
        lines.append(_pad_smd(3 * n_per_side + i + 1, -x_centre, y, pad_h, pad_w))
    # Body outline
    lines += _rect_line(_LAYER_FAB, -body_w / 2, -body_l_mm / 2, body_w / 2, body_l_mm / 2)
    # Pin-1 corner notch
    lines.append(
        f"\t(fp_arc (start {-body_w / 2:.4f} {body_l_mm / 2:.4f})"
        f" (mid {-body_w / 2 - 0.3:.4f} {body_l_mm / 2 - 0.15:.4f})"
        f" (end {-body_w / 2 + 0.3:.4f} {body_l_mm / 2:.4f})"
        f" (layer {_LAYER_FAB}) (stroke (width 0.1)(type solid)))"
    )
    lines += _rect_line(_LAYER_CYARD, -cyard, -cyard, cyard, cyard, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# QFN / DFN (no-lead packages)
# ---------------------------------------------------------------------------


def _qfn(
    pin_count: int,
    pitch_mm: float = 0.5,
    body_size_mm: float = 7.0,
    exposed_pad_mm: float | None = None,
    density: DensityLevel = "B",
) -> str:
    """Generate QFN footprint with optional exposed thermal pad."""
    if pin_count % 4 != 0 or pin_count < 8 or pin_count > 100:
        raise ValueError("pin_count must be divisible by 4, between 8 and 100.")
    jt, _jh, js = _IPC_OFFSETS[density]
    pad_h = 0.40 + jt  # QFN pad protrudes 0.4 mm from body
    pad_w = pitch_mm - 0.05 + 2 * js
    n_per_side = pin_count // 4
    span = (n_per_side - 1) * pitch_mm
    xy_centre = body_size_mm / 2 + pad_h / 2
    cyard = xy_centre + pad_h / 2 + 0.25
    ep_size = exposed_pad_mm or (body_size_mm - 1.0)
    name = f"QFN-{pin_count}_{pitch_mm:.2f}mm_{body_size_mm:.1f}x{body_size_mm:.1f}mm"
    lines = _fp_header(name, f"QFN {pin_count} leads {pitch_mm:.2f}mm pitch", "qfn", density)
    lines += _ref_value(-(cyard + 0.6), cyard + 0.6)
    # Bottom side — pins 1…n
    for i in range(n_per_side):
        x = -span / 2 + i * pitch_mm
        lines.append(_pad_smd(i + 1, x, xy_centre, pad_w, pad_h))
    # Right side
    for i in range(n_per_side):
        y = -span / 2 + i * pitch_mm
        lines.append(_pad_smd(n_per_side + i + 1, xy_centre, y, pad_h, pad_w))
    # Top side
    for i in range(n_per_side):
        x = span / 2 - i * pitch_mm
        lines.append(_pad_smd(2 * n_per_side + i + 1, x, -xy_centre, pad_w, pad_h))
    # Left side
    for i in range(n_per_side):
        y = span / 2 - i * pitch_mm
        lines.append(_pad_smd(3 * n_per_side + i + 1, -xy_centre, y, pad_h, pad_w))
    # Exposed thermal pad
    ep_num = pin_count + 1
    lines.append(
        f"\t(pad {ep_num!r} smd rect (at 0 0) (size {ep_size:.4f} {ep_size:.4f})"
        f" (layers {_LAYER_CU} {_LAYER_MASK} {_LAYER_PASTE}))"
    )
    # Body outline
    lines += _rect_line(
        _LAYER_FAB,
        -body_size_mm / 2,
        -body_size_mm / 2,
        body_size_mm / 2,
        body_size_mm / 2,
    )
    lines += _rect_line(_LAYER_CYARD, -cyard, -cyard, cyard, cyard, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# BGA
# ---------------------------------------------------------------------------


def _bga(
    rows: int,
    cols: int,
    pitch_mm: float = 0.8,
    ball_diameter_mm: float | None = None,
    density: DensityLevel = "B",
) -> str:
    """Generate BGA footprint (full-grid).

    Pad numbering: A1 = top-left, row letters A,B,C… (skip I,O,Q,S,X,Z per IPC).
    """
    _skip = frozenset("IOQSXZ")
    _letters = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in _skip]

    jt, _jh, _js = _IPC_OFFSETS[density]
    ball_d = ball_diameter_mm or (pitch_mm * 0.5 + 0.05)
    pad_d = ball_d + jt * 0.5  # IPC solder-mask-defined land
    total_w = (cols - 1) * pitch_mm
    total_h = (rows - 1) * pitch_mm
    cyard = max(total_w, total_h) / 2 + pitch_mm / 2 + 0.25
    name = f"BGA-{rows * cols}_{rows}x{cols}_{pitch_mm:.2f}mm"
    lines = _fp_header(name, f"BGA {rows}×{cols} {pitch_mm:.2f}mm pitch", "bga", density)
    lines += _ref_value(-(cyard + 0.6), cyard + 0.6)

    for r in range(rows):
        row_letter = _letters[r] if r < len(_letters) else f"R{r}"
        for c in range(cols):
            x = -total_w / 2 + c * pitch_mm
            y = -total_h / 2 + r * pitch_mm
            pad_name = f"{row_letter}{c + 1}"
            lines.append(
                f"\t(pad {_sexpr_string(pad_name)} smd circle (at {x:.4f} {y:.4f})"
                f" (size {pad_d:.4f} {pad_d:.4f})"
                f" (layers {_LAYER_CU} {_LAYER_MASK}))"
            )
    lines += _rect_line(
        _LAYER_FAB,
        -total_w / 2 - pitch_mm / 2,
        -total_h / 2 - pitch_mm / 2,
        total_w / 2 + pitch_mm / 2,
        total_h / 2 + pitch_mm / 2,
    )
    lines += _rect_line(_LAYER_CYARD, -cyard, -cyard, cyard, cyard, 0.05)
    # A1 corner dot
    lines.append(
        _circle_line(
            _LAYER_FAB,
            -total_w / 2 - pitch_mm * 0.4,
            -total_h / 2 - pitch_mm * 0.4,
            0.15,
        )
    )
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Through-hole pin header
# ---------------------------------------------------------------------------

_HEADER_PITCH = {2.54, 2.00, 1.27}


def _pin_header(
    pin_count: int,
    rows: int = 1,
    pitch_mm: float = 2.54,
) -> str:
    """Generate through-hole pin header (1×N or 2×N)."""
    if pitch_mm not in _HEADER_PITCH:
        raise ValueError(f"pitch_mm must be one of {sorted(_HEADER_PITCH)}")
    if rows not in (1, 2):
        raise ValueError("rows must be 1 or 2.")
    drill = pitch_mm * 0.4
    pad_size = drill + 0.8
    name = f"PinHeader_{rows}x{pin_count:02d}_{pitch_mm:.2f}mm"
    lines = _fp_header_tht(
        name,
        f"Pin header {rows}×{pin_count} {pitch_mm:.2f}mm",
        "pin-header connector",
    )
    lines += _ref_value(-(pin_count * pitch_mm / 2 + 0.5), pin_count * pitch_mm / 2 + 0.5)
    for i in range(pin_count):
        for r in range(rows):
            num = i * rows + r + 1
            x = r * pitch_mm - (rows - 1) * pitch_mm / 2
            y = -((pin_count - 1) * pitch_mm / 2) + i * pitch_mm
            lines.append(_pad_tht(num, x, y, drill, pad_size))
    # Silk outline
    ox = (rows - 1) * pitch_mm / 2 + pitch_mm / 2
    oy = (pin_count - 1) * pitch_mm / 2 + pitch_mm / 2
    lines += _rect_line(_LAYER_SILK, -ox, -oy, ox, oy)
    lines += _rect_line(_LAYER_CYARD, -ox - 0.25, -oy - 0.25, ox + 0.25, oy + 0.25, 0.05)
    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_footprint(
    package: str,
    *,
    pin_count: int | None = None,
    pitch_mm: float | None = None,
    body_l_mm: float | None = None,
    body_w_mm: float | None = None,
    density: DensityLevel = "B",
    rows: int = 1,
    exposed_pad_mm: float | None = None,
    ball_diameter_mm: float | None = None,
) -> str:
    """Generate a KiCad ``.kicad_mod`` S-expression for the requested package.

    Args:
        package: Package family. One of:
            ``"0201"``, ``"0402"``, ``"0603"``, ``"0805"``, ``"1206"``,
            ``"1210"``, ``"2512"`` — chip passives;
            ``"SOT-23"`` — SOT-23-3;
            ``"SOT-223"`` — SOT-223-3 with thermal tab;
            ``"SOT-89"`` — SOT-89-3 with thermal tab;
            ``"SOT-363"`` / ``"SOT-26"`` — 6-lead dual SOT;
            ``"SC-70"`` / ``"SOT-323"`` — 3-lead small SOT;
            ``"SOD-123"`` — 2-pad SMD diode;
            ``"SOD-323"`` — 2-pad small SMD diode;
            ``"SMA"`` / ``"SMB"`` / ``"SMC"`` (or ``"DO-214AB"`` / ``"DO-214AC"``
            / ``"DO-214AA"``) — DO-214 power diodes;
            ``"DPAK"`` / ``"TO-252"`` — 3-lead + tab power package;
            ``"D2PAK"`` / ``"TO-263"`` — 3-lead + large tab power package;
            ``"SOIC"``, ``"SOP"``, ``"SSOP"``, ``"TSSOP"`` — dual in-line SMD;
            ``"QFP"``, ``"LQFP"``, ``"TQFP"`` — quad flat pack;
            ``"QFN"``, ``"DFN"`` — no-lead;
            ``"BGA"`` — ball grid array;
            ``"PinHeader"`` — through-hole pin header.
        pin_count: Number of leads/balls (required for non-chip packages).
        pitch_mm: Lead pitch in mm. Defaults vary by package family.
        body_l_mm: Body length in mm (QFP/QFN; defaults apply).
        body_w_mm: Body width in mm (QFP only; defaults to ``body_l_mm``).
        density: IPC-7351B density level: ``"A"`` (generous), ``"B"`` (nominal),
            ``"C"`` (compact). Defaults to ``"B"``.
        rows: Number of rows for BGA (``rows×cols``) or PinHeader (1 or 2).
        exposed_pad_mm: Exposed pad size for QFN (defaults to ``body_size_mm - 1``).
        ball_diameter_mm: BGA ball diameter (defaults to ``pitch * 0.5 + 0.05``).

    Returns:
        A string containing the complete ``.kicad_mod`` S-expression.

    Raises:
        ValueError: For unsupported package families or out-of-range parameters.
    """
    pkg_up = package.upper()

    # Chip passives
    if pkg_up in {k.upper() for k in _CHIP_DIMS}:
        canonical = next(k for k in _CHIP_DIMS if k.upper() == pkg_up)
        return _chip_passive(canonical, density)

    if pkg_up == "SOT-23":
        return _sot23(density)

    if pkg_up in {"SOT-223", "SOT223"}:
        return _sot223(density)

    if pkg_up in {"SOT-89", "SOT89"}:
        return _sot89(density)

    if pkg_up in {"SOT-363", "SOT363", "SOT-26", "SOT26"}:
        return _sot363(density)

    if pkg_up in {"SC-70", "SC70", "SOT-323", "SOT323"}:
        return _sc70(density)

    if pkg_up in {"SOD-123", "SOD123"}:
        return _sod123(density)

    if pkg_up in {"SOD-323", "SOD323"}:
        return _sod323(density)

    if pkg_up in {
        "SMA",
        "SMB",
        "SMC",
        "DO-214AA",
        "DO214AA",
        "DO-214AB",
        "DO214AB",
        "DO-214AC",
        "DO214AC",
    }:
        # Map the long DO-214 names to the short variant
        _do214_map = {
            "SMA": "SMA",
            "SMB": "SMB",
            "SMC": "SMC",
            "DO-214AB": "SMA",
            "DO214AB": "SMA",
            "DO-214AC": "SMB",
            "DO214AC": "SMB",
            "DO-214AA": "SMC",
            "DO214AA": "SMC",
        }
        return _do214(_do214_map[pkg_up], density)

    if pkg_up in {"DPAK", "TO-252", "TO252", "D2PAK", "TO-263", "TO263"}:
        # Normalise aliases
        _dpak_map = {
            "DPAK": "DPAK",
            "TO-252": "TO-252",
            "TO252": "TO-252",
            "D2PAK": "D2PAK",
            "TO-263": "TO-263",
            "TO263": "TO-263",
        }
        return _dpak(_dpak_map[pkg_up], density)

    if pkg_up in {"SOIC", "SOP", "SSOP", "TSSOP"}:
        if pin_count is None:
            raise ValueError("pin_count is required for SOIC/SOP/SSOP/TSSOP packages.")
        return _soic(
            pin_count,
            pitch_mm=pitch_mm or (1.27 if pkg_up == "SOIC" else 0.65),
            body_w_mm=body_w_mm or (3.9 if pkg_up == "SOIC" else 4.4),
            density=density,
            family=pkg_up,
        )

    if pkg_up in {"QFP", "LQFP", "TQFP"}:
        if pin_count is None:
            raise ValueError("pin_count is required for QFP/LQFP/TQFP packages.")
        return _qfp(
            pin_count,
            pitch_mm=pitch_mm or 0.5,
            body_l_mm=body_l_mm or 10.0,
            body_w_mm=body_w_mm,
            density=density,
            family=pkg_up,
        )

    if pkg_up in {"QFN", "DFN"}:
        if pin_count is None:
            raise ValueError("pin_count is required for QFN/DFN packages.")
        return _qfn(
            pin_count,
            pitch_mm=pitch_mm or 0.5,
            body_size_mm=body_l_mm or 7.0,
            exposed_pad_mm=exposed_pad_mm,
            density=density,
        )

    if pkg_up == "BGA":
        if pin_count is None or rows is None:
            raise ValueError("pin_count (total balls) and rows are required for BGA.")
        cols = math.ceil(pin_count / rows)
        return _bga(
            rows,
            cols,
            pitch_mm=pitch_mm or 0.8,
            ball_diameter_mm=ball_diameter_mm,
            density=density,
        )

    if pkg_up == "PINHEADER":
        if pin_count is None:
            raise ValueError("pin_count is required for PinHeader.")
        return _pin_header(
            pin_count,
            rows=rows,
            pitch_mm=pitch_mm or 2.54,
        )

    raise ValueError(
        f"Unsupported package family '{package}'. "
        "Supported: chip passives (0201/0402/0603/0805/1206/1210/2512), "
        "SOT-23, SOT-223, SOT-89, SOT-363/SOT-26, SC-70/SOT-323, "
        "SOD-123, SOD-323, SMA/SMB/SMC (DO-214), DPAK/TO-252, D2PAK/TO-263, "
        "SOIC, SOP, SSOP, TSSOP, QFP, LQFP, TQFP, QFN, DFN, BGA, PinHeader."
    )
