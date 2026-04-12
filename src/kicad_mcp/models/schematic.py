"""Pydantic models for schematic operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

CoordMM = Annotated[
    float,
    Field(ge=-2000.0, le=2000.0, description="Coordinate in millimeters."),
]


class AddSymbolInput(BaseModel):
    """Schematic symbol placement input."""

    library: str = Field(min_length=1, max_length=120)
    symbol_name: str = Field(min_length=1, max_length=240)
    x_mm: CoordMM
    y_mm: CoordMM
    reference: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=240)
    footprint: str = Field(default="", max_length=240)
    rotation: Literal[0, 90, 180, 270] = 0


class AddWireInput(BaseModel):
    """Schematic wire parameters."""

    x1_mm: CoordMM
    y1_mm: CoordMM
    x2_mm: CoordMM
    y2_mm: CoordMM


class AddLabelInput(BaseModel):
    """Schematic label parameters."""

    name: str = Field(min_length=1, max_length=240)
    x_mm: CoordMM
    y_mm: CoordMM
    rotation: Literal[0, 90, 180, 270] = 0


class AddBusInput(BaseModel):
    """Schematic bus parameters."""

    x1_mm: CoordMM
    y1_mm: CoordMM
    x2_mm: CoordMM
    y2_mm: CoordMM


class AddBusWireEntryInput(BaseModel):
    """Bus wire entry parameters."""

    x_mm: CoordMM
    y_mm: CoordMM
    direction: Literal["up_right", "down_right", "up_left", "down_left"] = "up_right"


class AnnotateInput(BaseModel):
    """Reference annotation parameters."""

    start_number: int = Field(default=1, ge=1, le=9999)
    order: Literal["alpha", "sheet", "existing"] = "alpha"


class UpdatePropertiesInput(BaseModel):
    """Symbol property update parameters."""

    reference: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=1000)


class AddNoConnectInput(BaseModel):
    """No-connect marker parameters."""

    x_mm: CoordMM
    y_mm: CoordMM


class PowerSymbolInput(BaseModel):
    """Power symbol placement input for sch_build_circuit."""

    name: str = Field(min_length=1, max_length=120)
    x: CoordMM
    y: CoordMM
    rotation: Literal[0, 90, 180, 270] = 0
