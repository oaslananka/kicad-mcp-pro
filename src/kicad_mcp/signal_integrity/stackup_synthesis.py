"""FastMCP-independent stackup synthesis service."""

from __future__ import annotations

from dataclasses import dataclass

from ..utils.impedance import (
    DIELECTRIC_LIBRARY,
    get_dielectric,
    recommend_dielectric_for_frequency,
    solve_spacing_for_differential_impedance,
    solve_width_for_impedance,
    trace_impedance,
)


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

        for raw in interfaces:
            kind = str(raw.get("kind", "")).lower()
            freq = interface_freq_ghz.get(kind, 0.0)
            max_freq_ghz = max(max_freq_ghz, freq)
            diff = bool(raw.get("differential", False))
            impedance = raw.get("impedance_target_ohm")
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
            iface_summaries.append(
                f"  {kind}: {freq:.2f} GHz"
                + (
                    f", {impedance}ohm diff"
                    if impedance and diff
                    else f", {impedance}ohm SE"
                    if impedance
                    else ""
                )
            )

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
        if not has_highspeed and not has_differential:
            layer_count = 2
        elif max_freq_ghz < 1.0:
            layer_count = 4
        elif max_freq_ghz < 5.0:
            layer_count = 4 if not has_highspeed else 6
        else:
            layer_count = 8

        # Calculate outer dielectric thickness for 50ohm microstrip (1 oz Cu)
        outer_h_mm = 0.18  # starting guess
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
            f"- Outer prepreg thickness: ~{outer_h_mm:.2f} mm",
            f"- Board thickness: {board_thickness_mm:.1f} mm",
            "- Outer copper weight: 1 oz (0.035 mm)",
            "- Inner copper weight: 0.5 oz (recommended for dense routing)",
            "",
            "## Trace Width Targets (50ohm SE microstrip on outer layers)",
            f"- 50ohm trace width: **{width_50ohm:.3f} mm** (actual Z={actual_z:.1f}ohm)",
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
            "1. Call pcb_set_stackup() with layer_count and dielectric params above.",
            "2. Call pcb_set_net_class() for each high-speed net class.",
            "3. Route differential pairs with si_validate_length_matching().",
            "",
            f"Material note: {mat_desc}",
        ]
        return "\n".join(lines)
