"""FastMCP adapter for footprint engineering tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class LibraryFootprintEngineeringServiceProtocol(Protocol):
    def generate_footprint_ipc7351(
        self,
        package: str,
        density: str = "B",
        pin_count: int | None = None,
        pitch_mm: float | None = None,
        body_l_mm: float | None = None,
        body_w_mm: float | None = None,
        rows: int = 1,
        exposed_pad_mm: float | None = None,
        ball_diameter_mm: float | None = None,
        output_path: str = "",
    ) -> str: ...

    def validate_footprint_ipc7351(
        self,
        footprint_path: str,
        size_code: str,
        density: str = "B",
        tolerance_mm: float = 0.12,
    ) -> str: ...

    def certify_footprint(self, footprint_path: str) -> str: ...


@dataclass(frozen=True, slots=True)
class LibraryFootprintEngineeringDependencies:
    service: LibraryFootprintEngineeringServiceProtocol


def register(mcp: FastMCP, deps: LibraryFootprintEngineeringDependencies) -> None:
    """Register footprint generation, validation, and certification tools."""

    @mcp.tool()
    @headless_compatible
    def lib_generate_footprint_ipc7351(
        package: str,
        density: str = "B",
        pin_count: int | None = None,
        pitch_mm: float | None = None,
        body_l_mm: float | None = None,
        body_w_mm: float | None = None,
        rows: int = 1,
        exposed_pad_mm: float | None = None,
        ball_diameter_mm: float | None = None,
        output_path: str = "",
    ) -> str:
        """Generate an IPC-7351B compliant KiCad footprint (.kicad_mod) and save it.

        Supported packages: 0201, 0402, 0603, 0805, 1206, 1210, 2512 (chip passives),
        SOT-23, SOT-223, SOT-89, SOT-363/SOT-26, SC-70/SOT-323, SOD-123, SOD-323,
        SMA/SMB/SMC (DO-214), DPAK/TO-252, D2PAK/TO-263,
        SOIC, SOP, SSOP, TSSOP (dual SMD), QFP, LQFP, TQFP (quad flat),
        QFN, DFN (no-lead), BGA (ball grid array), PinHeader (through-hole).

        Args:
            package: Package family name (case-insensitive).
            density: IPC-7351B density level: A (generous), B (nominal), C (compact).
            pin_count: Number of leads / balls (required for multi-lead packages).
            pitch_mm: Lead pitch in mm.
            body_l_mm: Body length in mm.
            body_w_mm: Body width in mm (QFP only; defaults to body_l_mm).
            rows: BGA rows or PinHeader row count (1 or 2).
            exposed_pad_mm: Exposed pad size for QFN in mm.
            ball_diameter_mm: BGA ball diameter in mm.
            output_path: Optional relative path inside output_dir. Defaults to
                ``footprints/<package>.kicad_mod``.

        Returns:
            Confirmation with the saved file path, or an error message.
        """
        return deps.service.generate_footprint_ipc7351(
            package,
            density,
            pin_count,
            pitch_mm,
            body_l_mm,
            body_w_mm,
            rows,
            exposed_pad_mm,
            ball_diameter_mm,
            output_path,
        )

    @mcp.tool()
    @headless_compatible
    def lib_validate_footprint_ipc7351(
        footprint_path: str,
        size_code: str,
        density: str = "B",
        tolerance_mm: float = 0.12,
    ) -> str:
        """Validate a two-terminal chip footprint against its IPC-7351B nominal (hard gate).

        Reads the .kicad_mod at ``footprint_path`` (relative to the project), parses its
        SMD pads, and compares pad width/height/pitch to the IPC-7351B nominal for the
        given chip ``size_code`` and ``density``. Gross deviation is a blocking FAIL,
        minor deviation WARNs, a match PASSes. Scope: chip passives (0201–2512) against
        the IPC-7351B *standard* nominal — not a datasheet-specific land-pattern check.
        """
        return deps.service.validate_footprint_ipc7351(
            footprint_path, size_code, density, tolerance_mm
        )

    @mcp.tool()
    @headless_compatible
    def lib_certify_footprint(footprint_path: str) -> str:
        """Certify a footprint against package, documentation, and standard checks (#201).

        Reads the .kicad_mod at ``footprint_path`` (relative to the project) and runs
        package-agnostic certification: pad count vs the package name (SOIC/QFP/QFN/
        SOT/DIP…), documentation-layer completeness (courtyard/fab/silkscreen), and the
        recorded IPC-7351 density. Returns one aggregate PASS/WARN/FAIL with per-check
        findings; a missing courtyard or too-few pads is a blocking FAIL. Headless — no
        KiCad IPC. For two-terminal chip *geometry* use lib_validate_footprint_ipc7351.
        """
        return deps.service.certify_footprint(footprint_path)
