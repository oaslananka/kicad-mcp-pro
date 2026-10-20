"""Pydantic models for export operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
