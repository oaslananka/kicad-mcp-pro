"""Pydantic models for schematic operations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, Field

CoordMM = Annotated[
    float,
    Field(ge=-2000.0, le=2000.0, description="Coordinate in millimeters."),
]

LabelJustify = Literal[
    "left",
    "right",
    "top",
    "bottom",
    "left top",
    "left bottom",
    "right top",
    "right bottom",
    "none",
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
    unit: int = Field(default=1, ge=1, le=64)
    snap_to_grid: bool = True


class AddWireInput(BaseModel):
    """Schematic wire parameters."""

    x1_mm: CoordMM
    y1_mm: CoordMM
    x2_mm: CoordMM
    y2_mm: CoordMM
    snap_to_grid: bool = True


class AddLabelInput(BaseModel):
    """Schematic label parameters."""

    name: str = Field(min_length=1, max_length=240)
    x_mm: CoordMM
    y_mm: CoordMM
    rotation: Literal[0, 90, 180, 270] = 0
    snap_to_grid: bool = True
    global_label: bool = False
    shape: Literal["input", "output", "bidirectional", "tri_state", "passive"] | None = None
    justify: LabelJustify | None = None


class AddBusInput(BaseModel):
    """Schematic bus parameters."""

    x1_mm: CoordMM
    y1_mm: CoordMM
    x2_mm: CoordMM
    y2_mm: CoordMM
    snap_to_grid: bool = True


class AddBusWireEntryInput(BaseModel):
    """Bus wire entry parameters."""

    x_mm: CoordMM
    y_mm: CoordMM
    direction: Literal["up_right", "down_right", "up_left", "down_left"] = "up_right"
    snap_to_grid: bool = True


class AnnotateInput(BaseModel):
    """Reference annotation parameters."""

    start_number: int = Field(default=1, ge=1, le=9999)
    order: Literal["alpha", "sheet", "existing", "left_to_right"] = "alpha"


class UpdatePropertiesInput(BaseModel):
    """Symbol property update parameters."""

    reference: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=1000)


class DeleteSymbolInput(BaseModel):
    """Symbol removal parameters."""

    reference: str = Field(min_length=1, max_length=64)


class MoveSymbolInput(BaseModel):
    """Symbol move parameters."""

    reference: str = Field(min_length=1, max_length=64)
    x_mm: CoordMM
    y_mm: CoordMM
    snap_to_grid: bool = True


class DeleteWireInput(BaseModel):
    """Wire removal parameters."""

    wire_id: str = Field(min_length=1, max_length=120)


class AddNoConnectInput(BaseModel):
    """No-connect marker parameters."""

    x_mm: CoordMM
    y_mm: CoordMM
    snap_to_grid: bool = True


class PowerSymbolInput(BaseModel):
    """Power symbol placement input for sch_build_circuit."""

    name: str = Field(min_length=1, max_length=120)
    x_mm: CoordMM = Field(validation_alias=AliasChoices("x_mm", "x"))
    y_mm: CoordMM = Field(validation_alias=AliasChoices("y_mm", "y"))
    rotation: Literal[0, 90, 180, 270] = 0
    snap_to_grid: bool = True


class CreateSheetInput(BaseModel):
    """Create a child schematic sheet on the active top-level schematic."""

    name: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=240)
    x_mm: CoordMM
    y_mm: CoordMM
    snap_to_grid: bool = True


SheetPinType = Literal["input", "output", "bidirectional", "tri_state", "passive"]
SheetEdge = Literal["left", "right", "top", "bottom"]


class SheetPinInput(BaseModel):
    """One hierarchical sheet pin placed at an explicit edge position."""

    sheet: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    pin_type: SheetPinType = "input"
    edge: SheetEdge = "left"
    position_along_edge: CoordMM = 2.54


class ImportSheetPinsInput(BaseModel):
    """Mirror a child sheet's hierarchical labels onto its sheet symbol."""

    sheet: str | None = Field(default=None, max_length=120)
    grow_sheet: bool = True
    dry_run: bool = False


class HierarchicalLabelInput(BaseModel):
    """Hierarchical label placement parameters."""

    text: str = Field(min_length=1, max_length=240)
    x_mm: CoordMM
    y_mm: CoordMM
    shape: Literal["input", "output", "bidirectional", "tri_state", "passive"] = "input"
    rotation: Literal[0, 90, 180, 270] = 0
    snap_to_grid: bool = True
    justify: LabelJustify | None = None


class GlobalLabelInput(BaseModel):
    """Global label placement parameters."""

    text: str = Field(min_length=1, max_length=240)
    x_mm: CoordMM
    y_mm: CoordMM
    shape: Literal["input", "output", "bidirectional", "tri_state", "passive"] = "bidirectional"
    rotation: Literal[0, 90, 180, 270] = 0
    snap_to_grid: bool = True
    justify: LabelJustify | None = None


class ModifyLabelInput(BaseModel):
    """Label justification update parameters."""

    name: str = Field(min_length=1, max_length=240)
    x_mm: CoordMM
    y_mm: CoordMM
    justify: LabelJustify


class GetSheetInfoInput(BaseModel):
    """Query parameters for a specific child sheet."""

    sheet_name: str = Field(min_length=1, max_length=120)


class RouteWireBetweenPinsInput(BaseModel):
    """Pin-to-pin Manhattan routing parameters for schematics."""

    ref1: str = Field(min_length=1, max_length=64)
    pin1: str = Field(min_length=1, max_length=64)
    ref2: str = Field(min_length=1, max_length=64)
    pin2: str = Field(min_length=1, max_length=64)
    snap_to_grid: bool = True


class TraceNetInput(BaseModel):
    """Net trace request for schematic connectivity inspection."""

    net_name: str = Field(min_length=1, max_length=240)


class AutoPlaceSymbolsInput(BaseModel):
    """Auto-placement request for an explicit list of schematic references."""

    symbol_list: list[str] = Field(default_factory=list)
    strategy: Literal["cluster", "linear", "star", "grid"] = "cluster"
