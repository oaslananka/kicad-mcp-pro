"""FastMCP-independent stackup synthesis service."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from ..models.pcb import SetStackupInput, StackupLayerSpec
from ..utils.impedance import (
    DIELECTRIC_LIBRARY,
    get_dielectric,
    recommend_dielectric_for_frequency,
    solve_spacing_for_differential_impedance,
    solve_width_for_impedance,
    trace_impedance,
)
from .interface_validation import validate_interfaces


def _impedance_summary_suffix(impedance: object, differential: bool) -> str:
    """Format the existing diff-pair versus single-ended interface annotation."""
    if impedance and differential:
        return f", {impedance}ohm diff"
    if impedance:
        return f", {impedance}ohm SE"
    return ""


def _stackup_layer_count(max_freq_ghz: float, has_differential: bool, has_highspeed: bool) -> int:
    """Preserve the frequency and differential routing layer thresholds."""
    if not has_highspeed and not has_differential:
        return 2
    if max_freq_ghz < 1.0:
        return 4
    if max_freq_ghz < 5.0:
        return 4 if not has_highspeed else 6
    return 8


def _candidate_stackup(
    count: int, thickness: float, material: str, er: float, loss: float
) -> SetStackupInput:
    """Construct an explicitly provisional, symmetric copper/dielectric stack."""
    if not math.isfinite(thickness) or thickness <= 0:
        raise ValueError("Board thickness must be a positive finite number.")
    copper = ["F.Cu", *(f"In{i}.Cu" for i in range(1, count - 1)), "B.Cu"]
    dielectric_budget = thickness - (0.070 + (count - 2) * 0.018)
    inner = (dielectric_budget - 0.36) / (count - 3) if count > 2 else dielectric_budget
    if inner <= 0:
        raise ValueError(
            "Board thickness is too small for the recommended copper and dielectric layers."
        )
    layers = []
    for index, name in enumerate(copper):
        outer = index in (0, count - 1)
        layers.append(StackupLayerSpec(name=name, thickness_mm=0.035 if outer else 0.018))
        if index == count - 1:
            continue
        prepreg = count > 2 and index in (0, count - 2)
        layers.append(
            StackupLayerSpec(
                name=f"dielectric {index + 1}",
                type="prepreg" if prepreg else "core",
                material=material,
                thickness_mm=0.18 if prepreg else inner,
                epsilon_r=er,
                loss_tangent=loss,
            )
        )
    return SetStackupInput(layers=layers)


@dataclass(frozen=True)
class SignalIntegrityStackupSynthesisService:
    """Synthesize stackup recommendations from interface requirements."""

    @staticmethod
    def synthesize(
        interfaces: list[dict[str, object]],
        cost_tier: str = "standard",
        board_thickness_mm: float = 1.6,
    ) -> str:
        """Synthesise a PCB stackup that meets the impedance requirements of the given interfaces.

        Analyses each InterfaceSpec dict and recommends:
        - Layer count
        - Dielectric material
        - Copper weight per layer
        - Outer dielectric thickness for target impedance
        - Net class settings (impedance, clearance, diff-pair gap)

        Args:
            interfaces: List of InterfaceSpec dicts (matching project_set_design_intent
                interface format). Each must have at least ``kind`` and optionally
                ``impedance_target_ohm``, ``differential``, ``diff_skew_max_ps``.
            cost_tier: ``"standard"`` (FR4), ``"midloss"`` (FR4 mid/low-loss),
                ``"highspeed"`` (Rogers/Megtron). Overrides material selection.
            board_thickness_mm: Target board thickness in mm (1.0, 1.6, 2.0, 3.2).

        Returns:
            Recommended stackup specification and net class table in human-readable
            markdown, ready to pass to pcb_set_stackup() and pcb_set_net_class().
        """
        specs = validate_interfaces(interfaces)
        if not specs:
            raise ValueError("At least one interface is required for stackup synthesis.")

        # Map cost tier to dielectric preference
        tier_material = {
            "standard": "fr4_standard",
            "midloss": "fr4_midloss",
            "lowloss": "fr4_lowloss",
            "highspeed": "ro4350b",
            "rf": "ro4003c",
            "ultralow": "megtron6",
        }.get(cost_tier.lower(), "fr4_standard")

        # Determine maximum frequency from interface kinds
        interface_freq_ghz: dict[str, float] = {
            "usb2": 0.48,
            "usb3": 2.5,
            "usb3_gen2": 5.0,
            "pcie_g1": 1.25,
            "pcie_g2": 2.5,
            "pcie_g3": 4.0,
            "pcie_g4": 8.0,
            "ethernet_100": 0.1,
            "ethernet_1000": 0.625,
            "ethernet_2500": 1.25,
            "ethernet_10000": 5.0,
            "hdmi_1x": 1.65,
            "hdmi_2x": 3.4,
            "displayport": 2.7,
            "mipi_csi2": 1.5,
            "mipi_dsi": 1.5,
            "ddr3": 0.8,
            "ddr4": 1.6,
            "ddr5": 3.2,
            "lpddr4": 2.1,
            "lpddr5": 3.2,
            "can": 0.004,
            "canfd": 0.008,
            "rs485": 0.01,
            "spi_hs": 0.05,
            "i2c": 0.001,
            "i3c": 0.025,
            "uart": 0.001,
            "jtag": 0.03,
            "swd": 0.05,
            "lvds": 0.625,
            "sgmii": 0.625,
        }

        max_freq_ghz = 0.0
        has_differential = False
        has_highspeed = False
        iface_summaries: list[str] = []

        for spec in specs:
            kind = spec.kind
            if kind not in interface_freq_ghz:
                raise ValueError(
                    f"Unsupported interface {kind}: supply a known protocol frequency."
                )
            freq = interface_freq_ghz[kind]
            max_freq_ghz = max(max_freq_ghz, freq)
            diff = spec.differential
            impedance = (
                f"{spec.impedance_target_ohm:g}" if spec.impedance_target_ohm is not None else None
            )
            if diff or kind in {
                "usb2",
                "usb3",
                "usb3_gen2",
                "pcie_g1",
                "pcie_g2",
                "pcie_g3",
                "pcie_g4",
                "ethernet_1000",
                "ethernet_2500",
                "ethernet_10000",
                "hdmi_1x",
                "hdmi_2x",
                "displayport",
                "lvds",
                "sgmii",
            }:
                has_differential = True
            if freq >= 1.0:
                has_highspeed = True
            imp_suffix = _impedance_summary_suffix(impedance, diff)
            iface_summaries.append(f"  {kind}: {freq:.2f} GHz{imp_suffix}")

        # Override material if frequency mandates it
        freq_material = recommend_dielectric_for_frequency(max_freq_ghz)
        # Choose the better of cost_tier and freq recommendation
        tier_er = DIELECTRIC_LIBRARY[tier_material][1]
        freq_er = DIELECTRIC_LIBRARY[freq_material][1]
        if freq_er < tier_er:
            material_key = freq_material  # frequency wins
        else:
            material_key = tier_material

        mat_name, er, loss_tan, mat_desc = get_dielectric(material_key)

        # Determine layer count
        layer_count = _stackup_layer_count(max_freq_ghz, has_differential, has_highspeed)

        # Calculate outer dielectric thickness for 50ohm microstrip (1 oz Cu)
        candidate = _candidate_stackup(layer_count, board_thickness_mm, mat_name, er, loss_tan)
        outer_h_mm = candidate.layers[1].thickness_mm
        target_ohm = 50.0
        width_50ohm = solve_width_for_impedance(target_ohm, outer_h_mm, er, copper_oz=1.0)
        actual_z, _ = trace_impedance(width_50ohm, outer_h_mm, er, copper_oz=1.0)

        # Diff pair gap for 90ohm differential (USB standard)
        gap_90ohm = solve_spacing_for_differential_impedance(
            90.0, width_50ohm * 0.8, outer_h_mm, er, copper_oz=1.0
        )

        lines = [
            "# Stackup Synthesis Report",
            "",
            "## Interface Analysis",
            *iface_summaries,
            "",
            f"Max interface frequency: {max_freq_ghz:.2f} GHz",
            f"Has differential pairs: {has_differential}",
            f"Has high-speed signals (&gt;=1 GHz): {has_highspeed}",
            "",
            "## Recommended Stackup",
            f"- Layer count: **{layer_count}**",
            f"- Dielectric: **{mat_name}** (Er={er}, tan_d={loss_tan})",
            f"- Outer dielectric thickness: ~{outer_h_mm:.2f} mm",
            f"- Board thickness: {board_thickness_mm:.1f} mm",
            "- Outer copper weight: 1 oz (0.035 mm)",
            "- Inner copper weight: 0.5 oz (recommended for dense routing)",
            "",
            "## Trace Width Targets (50ohm SE microstrip on outer layers)",
            f"- 50ohm trace width: **{width_50ohm:.3f} mm** (estimated Z={actual_z:.1f}ohm)",
            f"- 90ohm diff-pair gap: **{gap_90ohm:.3f} mm** (USB 2.0 / USB 3.x)",
            "",
            "## Net Class Configuration",
            "| Net class | Clearance (mm) | Track width (mm) | Diff gap (mm) |",
            "|-----------|---------------|-----------------|--------------|",
            "| Default   | 0.20          | 0.20            | —            |",
            f"| 50R_SE    | 0.20          | {width_50ohm:.3f}         | —            |",
            f"| 90R_DIFF  | 0.15          | {width_50ohm * 0.8:.3f}     | {gap_90ohm:.3f}      |",
            f"| 100R_DIFF | 0.15          | {width_50ohm * 0.75:.3f}    |              |",
            "",
            "## Next Steps",
            "Candidate geometry only: estimates are not verified physical impedance. "
            "Confirm the stackup and manufacturing tolerances with the fabricator before applying.",
            "Review the board and close its editor before applying this candidate; "
            "do not force reload.",
            "```json",
            json.dumps(
                {
                    "tool": "pcb_set_stackup",
                    "arguments": {**candidate.model_dump(mode="json"), "allow_open_board": False},
                },
                indent=2,
            ),
            "```",
            "Resolve interface nets and review rule definitions before any assignment:",
            "```json",
            json.dumps(
                {
                    "tool": "si_bind_interfaces_to_net_classes",
                    "arguments": {
                        "interfaces": [
                            spec.model_dump(mode="json", exclude_unset=True) for spec in specs
                        ],
                        "dry_run": True,
                    },
                },
                indent=2,
            ),
            "```",
            "After routing, use si_validate_length_matching to check the selected nets.",
            "",
            f"Material note: {mat_desc}",
        ]
        return "\n".join(lines)
