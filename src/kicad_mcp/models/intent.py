"""Rich design-intent sub-models for professional PCB projects.

These models extend the base :class:`~kicad_mcp.tools.project.ProjectDesignIntent`
with structured data for power rails, high-speed interfaces, mechanical constraints,
compliance targets, cost budgets, and thermal envelopes.

All fields are optional (with sensible defaults) so that v1 intent JSON serialised
by kicad-mcp-pro ≤ 2.0.x loads cleanly via Pydantic's ``model_validate``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Power-rail budget
# ---------------------------------------------------------------------------

PowerRailDecouplingStrategy = Literal["bulk", "ferrite", "lc_filter", "none", ""]


class PowerRailSpec(BaseModel):
    """Specification for a single power rail.

    Used by placement analysis (minimum trace width) and PDN checks
    (voltage-drop budget, decoupling strategy).
    """

    name: str = Field(min_length=1, max_length=64, description="Net name, e.g. '+3V3'.")
    voltage_v: float = Field(gt=0.0, le=60.0, description="Nominal output voltage in Volts.")
    current_max_a: float = Field(gt=0.0, le=200.0, description="Peak current draw in Amperes.")
    tolerance_pct: float = Field(
        default=5.0, ge=0.0, le=20.0, description="Allowed voltage deviation in percent."
    )
    source_ref: str = Field(
        default="", max_length=50, description="Schematic reference of the source (LDO/SMPS)."
    )
    decoupling_strategy: PowerRailDecouplingStrategy = Field(
        default="", description="Preferred decoupling topology for this rail."
    )


# ---------------------------------------------------------------------------
# High-speed interface specs
# ---------------------------------------------------------------------------

InterfaceKind = Literal[
    "usb2",
    "usb3",
    "usb3_gen2",
    "pcie_g1",
    "pcie_g2",
    "pcie_g3",
    "pcie_g4",
    "ethernet_100",
    "ethernet_1000",
    "ethernet_2500",
    "ethernet_10000",
    "hdmi_1x",
    "hdmi_2x",
    "displayport",
    "mipi_csi2",
    "mipi_dsi",
    "ddr3",
    "ddr4",
    "ddr5",
    "lpddr4",
    "lpddr5",
    "can",
    "canfd",
    "rs485",
    "spi_hs",
    "i2c",
    "i3c",
    "uart",
    "jtag",
    "swd",
    "lvds",
    "sgmii",
    "custom",
]


class InterfaceSpec(BaseModel):
    """High-speed or protocol-critical interface requirements.

    Downstream tools use these values to:
    * Set net class impedance targets and clearances.
    * Validate diff-pair skew and length-matching constraints.
    * Synthesise a board stackup that supports the required impedance.
    """

    kind: InterfaceKind = Field(description="Protocol identifier.")
    refs: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Schematic/PCB component references involved in this interface.",
    )
    net_prefix: str = Field(
        default="",
        max_length=64,
        description="Optional net-name prefix used to auto-match nets (e.g. 'USB_DP').",
    )
    impedance_target_ohm: float | None = Field(
        default=None,
        gt=0.0,
        le=300.0,
        description="Single-ended or differential impedance target in Ohms.",
    )
    differential: bool = Field(
        default=False,
        description="True when impedance_target_ohm refers to a differential pair.",
    )
    diff_skew_max_ps: float | None = Field(
        default=None,
        ge=0.0,
        description="Maximum intra-pair skew in picoseconds.",
    )
    length_target_mm: float | None = Field(
        default=None,
        gt=0.0,
        description="Absolute trace length target in mm (for length matching).",
    )
    length_match_tolerance_mm: float = Field(
        default=5.0,
        ge=0.0,
        le=100.0,
        description="Allowed deviation from length_target_mm in mm.",
    )
    layer_hint: str = Field(
        default="",
        max_length=64,
        description="Preferred routing layer (e.g. 'In1.Cu').",
    )
    notes: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Mechanical constraints
# ---------------------------------------------------------------------------


class MountHoleSpec(BaseModel):
    """A mounting hole or standoff location."""

    x_mm: float
    y_mm: float
    diameter_mm: float = Field(default=3.2, gt=0.0, le=20.0)
    label: str = Field(default="", max_length=32)


class ConnectorEdgePlacement(BaseModel):
    """Constraint requiring a connector to be near a specific board edge."""

    ref: str = Field(min_length=1, max_length=50)
    edge: Literal["top", "bottom", "left", "right"] = "bottom"
    margin_mm: float = Field(
        default=2.0, ge=0.0, le=50.0, description="Max allowed distance from the edge in mm."
    )


class ConnectorMatingSpec(BaseModel):
    """Explicit footprint-local mating datum and direction for edge connectors.

    Units are mm in KiCad footprint coordinates. A design engineer must
    verify these values against a real footprint drawing/datasheet; we do
    not infer them from connector reference or center-to-edge proximity.
    """

    ref: str = Field(min_length=1, max_length=50)
    footprint_id: str = Field(min_length=3, max_length=200)
    edge: Literal["top", "bottom", "left", "right"]
    datum_x_mm: float = Field(allow_inf_nan=False)
    datum_y_mm: float = Field(allow_inf_nan=False)
    normal_local: Literal["top", "bottom", "left", "right"]
    max_datum_error_mm: float = Field(default=0.5, ge=0.0, le=10.0, allow_inf_nan=False)
    # Optional conservative 2-D tolerance budget; if either is supplied both
    # must be specified. Omission preserves historical nominal-only checks.
    # Neither these numbers nor nominal fit constitute 3-D mating approval.
    datum_component_tolerance_mm: float | None = Field(
        default=None, ge=0.0, le=10.0, allow_inf_nan=False
    )
    board_edge_tolerance_mm: float | None = Field(
        default=None, ge=0.0, le=10.0, allow_inf_nan=False
    )
    max_direction_error_deg: float = Field(default=10.0, ge=0.0, le=45.0, allow_inf_nan=False)


class MechanicalConstraint(BaseModel):
    """Board-level mechanical design constraints.

    Consumed by placement analysis to enforce connector edge positions,
    mount-hole clearances, and height envelopes.
    """

    outline_dxf_path: str = Field(
        default="",
        max_length=500,
        description="Path to a DXF file defining the board outline (relative to project root).",
    )
    board_width_mm: float | None = Field(
        default=None, gt=0.0, description="Override board width in mm."
    )
    board_height_mm: float | None = Field(
        default=None, gt=0.0, description="Override board height in mm."
    )
    mount_holes: list[MountHoleSpec] = Field(default_factory=list, max_length=20)
    connector_placement: list[ConnectorEdgePlacement] = Field(default_factory=list, max_length=50)
    connector_mating: list[ConnectorMatingSpec] = Field(
        default_factory=list,
        max_length=50,
        description="Explicit mating plane + outward normal checks; absent means not assessed.",
    )
    max_height_mm: float | None = Field(
        default=None,
        gt=0.0,
        le=200.0,
        description="Maximum component height above the primary surface in mm.",
    )
    enclosure_step_path: str = Field(
        default="",
        max_length=500,
        description="Path to an enclosure STEP model for 3-D interference checking.",
    )
    notes: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Compliance targets
# ---------------------------------------------------------------------------

ComplianceKind = Literal[
    "fcc_b",
    "fcc_a",
    "ce_red",
    "ce_emc",
    "ul",
    "ul_60950",
    "iec_62368",
    "automotive_aec_q100",
    "automotive_aec_q200",
    "medical_60601",
    "itar",
    "custom",
]


class ComplianceTarget(BaseModel):
    """Regulatory compliance requirement that should be tracked through layout and DFM."""

    kind: ComplianceKind = Field(description="Compliance standard identifier.")
    extra_standards: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Additional free-form standards or safety targets.",
    )
    notes: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Cost and NRE budget
# ---------------------------------------------------------------------------


class CostTarget(BaseModel):
    """Unit-cost and NRE budget constraints for use by DFM and part-selection tools."""

    unit_cost_usd_max: float | None = Field(
        default=None, gt=0.0, description="Maximum BOM cost per unit in USD."
    )
    volume_units: int = Field(
        default=1, ge=1, description="Production volume used for per-unit cost estimation."
    )
    nre_budget_usd: float | None = Field(
        default=None, ge=0.0, description="Maximum non-recurring engineering spend in USD."
    )
    prefer_jlcpcb_basic_parts: bool = Field(
        default=False,
        description="Prefer JLCPCB basic library parts to minimise assembly cost.",
    )


# ---------------------------------------------------------------------------
# Thermal envelope
# ---------------------------------------------------------------------------

AirflowKind = Literal["natural", "forced", "liquid", "none"]


class ThermalEnvelope(BaseModel):
    """Thermal operating environment for heat-path and via-count recommendations."""

    ambient_c: float = Field(
        default=25.0, ge=-55.0, le=125.0, description="Ambient operating temperature in °C."
    )
    max_component_c: float = Field(
        default=85.0, ge=0.0, le=200.0, description="Maximum allowed component case temp in °C."
    )
    airflow: AirflowKind = Field(default="natural")
    ambient_airflow_m_s: float | None = Field(
        default=None,
        ge=0.0,
        le=50.0,
        description="Measured or expected ambient airflow in m/s.",
    )
    thermal_resistance_target_c_per_w: float | None = Field(
        default=None, gt=0.0, description="System-level thermal resistance target (°C/W)."
    )
