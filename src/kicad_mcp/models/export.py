"""Pydantic models for export and project operations."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SetProjectInput(BaseModel):
    """Project activation parameters."""

    project_dir: Path
    pcb_file: Path | None = None
    sch_file: Path | None = None
    output_dir: Path | None = None


class ExportGerberInput(BaseModel):
    """Gerber export options."""

    output_subdir: str = Field(default="gerber", min_length=1, max_length=120)
    layers: list[str] = Field(default_factory=list)


class ExportBOMInput(BaseModel):
    """BOM export options."""

    format: Literal["csv", "xml"] = "csv"


class ExportNetlistInput(BaseModel):
    """Netlist export options."""

    format: Literal["kicad", "spice", "cadstar", "orcadpcb2"] = "kicad"


class ExportPdfInput(BaseModel):
    """PDF export options."""

    layers: list[str] = Field(default_factory=list)


class ExportRenderInput(BaseModel):
    """3D render export options."""

    output_file: str = Field(default="render.png", min_length=1, max_length=240)
    side: Literal["top", "bottom", "front", "back", "left", "right"] = "top"
    zoom: float = Field(default=1.0, gt=0.05, le=20.0)
