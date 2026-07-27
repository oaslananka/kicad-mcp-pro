"""Thin FastMCP adapters for file-backed PCB inspection tools."""

from __future__ import annotations

# pyright: reportUnusedFunction=false
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class FileInspectionService(Protocol):
    """Minimal service contract required by the adapter."""

    def footprint_layers_for(self, reference: str) -> str: ...

    def visual_qa(self) -> str: ...


@dataclass(frozen=True)
class PcbFileInspectionDependencies:
    """PCB file-inspection dependencies injected by the composition root."""

    service: FileInspectionService


def register(mcp: FastMCP, dependencies: PcbFileInspectionDependencies) -> None:
    """Register file-backed PCB inspection tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def pcb_get_footprint_layers(reference: str) -> str:
        """List every layer referenced by a footprint block, including inner layers."""
        return service.footprint_layers_for(reference)

    @mcp.tool()
    @headless_compatible
    def pcb_visual_qa() -> str:
        """Headless PCB readability QA: off-board parts, silk and body overlap.

        A fast, file-backed first pass that runs without a live KiCad: it flags
        footprints whose body leaves the board outline, reference designators that
        collide on the silkscreen, and overlapping footprint bodies — directly
        from the ``.kicad_pcb`` geometry. It complements (does not replace) the
        authoritative DRC run, which remains the sign-off check for courtyard and
        silk clipping. Returns JSON with an overall PASS/INFO/WARN status and
        per-finding refs/positions.
        """
        return service.visual_qa()
