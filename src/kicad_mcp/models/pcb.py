"""Pydantic models for PCB operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

LayerName = Literal[
    "F_Cu",
    "B_Cu",
    "In1_Cu",
    "In2_Cu",
    "In3_Cu",
    "In4_Cu",
    "In5_Cu",
    "In6_Cu",
    "In7_Cu",
    "In8_Cu",
    "F_SilkS",
    "B_SilkS",
    "F_Mask",
    "B_Mask",
    "F_Fab",
    "B_Fab",
    "F_CrtYd",
    "B_CrtYd",
    "Edge_Cuts",
    "Dwgs_User",
    "Cmts_User",
    "Eco1_User",
    "Eco2_User",
]
CoordMM = Annotated[
    float,
    Field(ge=-2000.0, le=2000.0, description="Coordinate in millimeters."),
]
WidthMM = Annotated[
    float,
    Field(gt=0.0, le=10.0, description="Width in millimeters."),
]


class AddTrackInput(BaseModel):
    """Track insertion parameters."""

    x1_mm: CoordMM = Field(description="Start X coordinate in mm.")
    y1_mm: CoordMM = Field(description="Start Y coordinate in mm.")
    x2_mm: CoordMM = Field(description="End X coordinate in mm.")
    y2_mm: CoordMM = Field(description="End Y coordinate in mm.")
    layer: LayerName = Field(default="F_Cu", description="Target PCB layer.")
    width_mm: WidthMM = Field(default=0.25, description="Track width in mm.")
    net_name: str = Field(default="", description="Optional net name.")


class BulkTrackItem(BaseModel):
    """Single item for bulk track insertion."""

    x1: CoordMM
    y1: CoordMM
    x2: CoordMM
    y2: CoordMM
    layer: LayerName = "F_Cu"
    width: WidthMM = 0.25
    net: str = ""


class AddViaInput(BaseModel):
    """Via insertion parameters."""

    x_mm: CoordMM
    y_mm: CoordMM
    diameter_mm: WidthMM = Field(default=0.8)
    drill_mm: WidthMM = Field(default=0.4)
    net_name: str = Field(default="")
    via_type: Literal["through", "blind", "micro"] = Field(default="through")


class AddSegmentInput(BaseModel):
    """Segment graphic insertion parameters."""

    x1_mm: CoordMM
    y1_mm: CoordMM
    x2_mm: CoordMM
    y2_mm: CoordMM
    layer: LayerName = Field(default="Edge_Cuts")
    width_mm: WidthMM = Field(default=0.05)


class AddCircleInput(BaseModel):
    """Circle graphic insertion parameters."""

    cx_mm: CoordMM = Field(description="Center X in mm.")
    cy_mm: CoordMM = Field(description="Center Y in mm.")
    radius_mm: float = Field(gt=0.0, le=500.0, description="Radius in mm.")
    layer: LayerName = Field(default="Edge_Cuts")
    width_mm: WidthMM = Field(default=0.05)


class AddRectangleInput(BaseModel):
    """Rectangle graphic insertion parameters."""

    x1_mm: CoordMM
    y1_mm: CoordMM
    x2_mm: CoordMM
    y2_mm: CoordMM
    layer: LayerName = Field(default="Edge_Cuts")
    width_mm: WidthMM = Field(default=0.05)


class AddTextInput(BaseModel):
    """Board text insertion parameters."""

    text: str = Field(min_length=1, max_length=1000)
    x_mm: CoordMM
    y_mm: CoordMM
    layer: LayerName = Field(default="F_SilkS")
    size_mm: float = Field(default=1.0, gt=0.0, le=50.0)
    rotation_deg: float = Field(default=0.0, ge=-360.0, le=360.0)
    bold: bool = Field(default=False)
    italic: bool = Field(default=False)


class SetBoardOutlineInput(BaseModel):
    """Board outline parameters."""

    width_mm: float = Field(gt=0.0, le=2000.0)
    height_mm: float = Field(gt=0.0, le=2000.0)
    origin_x_mm: CoordMM = 0.0
    origin_y_mm: CoordMM = 0.0
