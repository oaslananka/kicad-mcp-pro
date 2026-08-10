"""Thin FastMCP adapter for single-file PCB export formats."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .aliases import notify_deprecated, register_alias
from .metadata import headless_compatible


class PcbFileFormatsService(Protocol):
    """Minimal service contract required by the single-file format adapter."""

    def export(self, format_name: str, output_path: str = "") -> str: ...


@dataclass(frozen=True)
class ExportPcbFileFormatsDependencies:
    """Dependencies injected by the export composition root."""

    service: PcbFileFormatsService
    add_low_level_notice: Callable[[str], str]


def register(mcp: FastMCP, dependencies: ExportPcbFileFormatsDependencies) -> None:
    """Register single-file PCB format export tools."""
    service = dependencies.service
    add_notice = dependencies.add_low_level_notice

    @headless_compatible
    def export_3d_step() -> str:
        """Deprecated alias of ``export_step``; exports a STEP model for the active board.

        Retained for backward compatibility. Prefer ``export_step``, which accepts an
        optional output path. This alias logs a one-time deprecation warning.
        """
        notify_deprecated("export_3d_step")
        return export_step()

    @headless_compatible
    def export_step(output_path: str = "") -> str:
        """Export a STEP model for the active board."""
        return add_notice(service.export("step", output_path))

    @headless_compatible
    def export_stepz(output_path: str = "") -> str:
        """Export a STEPZ model for the active board."""
        return add_notice(service.export("stepz", output_path))

    @headless_compatible
    def export_xao(output_path: str = "") -> str:
        """Export an XAO model for the active board."""
        return add_notice(service.export("xao", output_path))

    @headless_compatible
    def export_brep(output_path: str = "") -> str:
        """Export BREP format for the active board."""
        return add_notice(service.export("brep", output_path))

    @headless_compatible
    def export_glb(output_path: str = "") -> str:
        """Export GLB format for the active board."""
        return add_notice(service.export("glb", output_path))

    @headless_compatible
    def export_gencad(output_path: str = "") -> str:
        """Export GenCAD format for the active board."""
        return add_notice(service.export("gencad", output_path))

    @headless_compatible
    def export_ipc_d356(output_path: str = "") -> str:
        """Export IPC-D-356 format for the active board."""
        return add_notice(service.export("ipc_d356", output_path))

    @headless_compatible
    def export_ply(output_path: str = "") -> str:
        """Export PLY format for the active board."""
        return add_notice(service.export("ply", output_path))

    @headless_compatible
    def export_stl(output_path: str = "") -> str:
        """Export STL format for the active board."""
        return add_notice(service.export("stl", output_path))

    @headless_compatible
    def export_u3d(output_path: str = "") -> str:
        """Export U3D format for the active board."""
        return add_notice(service.export("u3d", output_path))

    @headless_compatible
    def export_vrml(output_path: str = "") -> str:
        """Export VRML format for the active board."""
        return add_notice(service.export("vrml", output_path))

    @headless_compatible
    def export_ps(output_path: str = "") -> str:
        """Export PostScript format for the active board."""
        return add_notice(service.export("ps", output_path))

    register_alias(mcp, export_3d_step, "export_step")
    for tool in (
        export_step,
        export_stepz,
        export_xao,
        export_brep,
        export_glb,
        export_gencad,
        export_ipc_d356,
        export_ply,
        export_stl,
        export_u3d,
        export_vrml,
        export_ps,
    ):
        mcp.tool()(tool)
