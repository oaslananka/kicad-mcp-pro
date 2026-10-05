"""FastMCP-independent signal-integrity stackup generation service."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.signal_integrity import StackupInput
from ..utils.impedance import (
    differential_impedance,
    solve_spacing_for_differential_impedance,
    solve_width_for_impedance,
    trace_impedance,
)


def _stackup_templates(manufacturer: str, layer_count: int) -> list[dict[str, str | float]]:
    normalized = manufacturer.casefold()
    if normalized == "pcbway":
        templates: dict[int, list[dict[str, str | float]]] = {
            2: [
                {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 1.53},
                {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            ],
            4: [
                {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
                {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.17},
                {
                    "name": "In1.Cu",
                    "role": "ground plane",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 1.124},
                {
                    "name": "In2.Cu",
                    "role": "power / signal",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.17},
                {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            ],
            6: [
                {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
                {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.11},
                {
                    "name": "In1.Cu",
                    "role": "ground plane",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.35},
                {"name": "In2.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.018},
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.65},
                {
                    "name": "In3.Cu",
                    "role": "power plane",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.35},
                {
                    "name": "In4.Cu",
                    "role": "ground plane",
                    "material": "Copper",
                    "thickness_mm": 0.018,
                },
                {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.11},
                {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            ],
        }
        return templates[layer_count]

    templates = {
        2: [
            {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 1.53},
            {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
        ],
        4: [
            {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.18},
            {
                "name": "In1.Cu",
                "role": "solid GND plane",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 1.114},
            {
                "name": "In2.Cu",
                "role": "power / signal",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.18},
            {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
        ],
        6: [
            {"name": "F.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
            {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.11},
            {
                "name": "In1.Cu",
                "role": "solid GND plane",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.33},
            {
                "name": "In2.Cu",
                "role": "high-speed signal",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.62},
            {
                "name": "In3.Cu",
                "role": "power plane",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Core", "role": "dielectric", "material": "FR4", "thickness_mm": 0.33},
            {
                "name": "In4.Cu",
                "role": "solid GND plane",
                "material": "Copper",
                "thickness_mm": 0.018,
            },
            {"name": "Prepreg", "role": "dielectric", "material": "FR4", "thickness_mm": 0.11},
            {"name": "B.Cu", "role": "signal", "material": "Copper", "thickness_mm": 0.035},
        ],
    }
    return templates[layer_count]


@dataclass(frozen=True)
class SignalIntegrityStackupGenerationService:
    """Generate deterministic first-pass PCB stackup recommendations."""

    def generate(
        self,
        layer_count: int = 4,
        target_impedance_ohm: float = 50.0,
        manufacturer: str = "JLCPCB",
        er: float = 4.2,
        copper_oz: float = 1.0,
    ) -> str:
        payload = StackupInput(
            layer_count=layer_count,
            target_impedance_ohm=target_impedance_ohm,
            manufacturer=manufacturer,
            er=er,
            copper_oz=copper_oz,
        )
        template = _stackup_templates(payload.manufacturer, payload.layer_count)
        outer_dielectric_mm = next(
            float(layer["thickness_mm"])
            for layer in template
            if str(layer["role"]).startswith("dielectric")
        )
        width_mm = solve_width_for_impedance(
            payload.target_impedance_ohm,
            outer_dielectric_mm,
            payload.er,
            trace_type="microstrip",
            copper_oz=payload.copper_oz,
        )
        impedance_ohm, effective_er = trace_impedance(
            width_mm,
            outer_dielectric_mm,
            payload.er,
            trace_type="microstrip",
            copper_oz=payload.copper_oz,
        )
        diff_gap_mm = solve_spacing_for_differential_impedance(
            100.0,
            width_mm * 0.55,
            outer_dielectric_mm,
            payload.er,
            trace_type="microstrip",
            copper_oz=payload.copper_oz,
        )
        diff_ohm, _ = differential_impedance(
            width_mm * 0.55,
            outer_dielectric_mm,
            diff_gap_mm,
            payload.er,
            trace_type="microstrip",
            copper_oz=payload.copper_oz,
        )

        lines = [
            f"Recommended {payload.layer_count}-layer {payload.manufacturer} stackup:",
            f"- Target outer-layer impedance: {payload.target_impedance_ohm:.2f} ohm",
            f"- Solved outer microstrip width: {width_mm:.3f} mm",
            f"- Rechecked impedance: {impedance_ohm:.2f} ohm",
            f"- Effective permittivity: {effective_er:.3f}",
            (
                f"- Approximate 100 ohm differential pair starting point: "
                f"width {width_mm * 0.55:.3f} mm / gap {diff_gap_mm:.3f} mm "
                f"(estimate {diff_ohm:.2f} ohm)"
            ),
            "Layers:",
        ]
        for index, layer in enumerate(template, start=1):
            lines.append(
                f"- {index}. {layer['name']} | {layer['role']} | "
                f"{layer['material']} | {float(layer['thickness_mm']):.3f} mm"
            )
        lines.append(
            "- Review with your fabricator's published stackup table "
            "before freezing impedance rules."
        )
        return "\n".join(lines)
