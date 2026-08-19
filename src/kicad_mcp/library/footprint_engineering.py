"""Footprint generation, validation, and certification behavior."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..utils.footprint_gen import generate_footprint
from ..utils.footprint_validate import (
    FootprintCheck,
    check_footprint_documentation_layers,
    check_footprint_pad_count,
    parse_ipc_density,
    parse_smd_pads,
    validate_chip_footprint,
)


class UpgradeResultProtocol(Protocol):
    @property
    def upgraded(self) -> bool: ...

    @property
    def detail(self) -> str: ...


@dataclass(frozen=True, slots=True)
class LibraryFootprintEngineeringService:
    """File-backed footprint engineering independent of FastMCP."""

    resolve_within_project: Callable[[str], Path]
    default_output_dir: Callable[[], Path]
    upgrade_generated_footprint: Callable[[Path], UpgradeResultProtocol]

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
    ) -> str:
        """Generate and save an IPC-7351B footprint."""
        if density not in ("A", "B", "C"):
            return f"Invalid density '{density}'. Must be A, B, or C."

        try:
            sexpr = generate_footprint(
                package,
                pin_count=pin_count,
                pitch_mm=pitch_mm,
                body_l_mm=body_l_mm,
                body_w_mm=body_w_mm,
                density=density,  # type: ignore[arg-type]
                rows=rows,
                exposed_pad_mm=exposed_pad_mm,
                ball_diameter_mm=ball_diameter_mm,
            )
        except ValueError as exc:
            return f"Footprint generation failed: {exc}"

        if output_path:
            out_file = self.resolve_within_project(output_path)
        else:
            out_dir = self.default_output_dir() / "footprints"
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_name = package.upper().replace("/", "_").replace(" ", "_")
            if pin_count:
                safe_name += f"-{pin_count}"
            out_file = out_dir / f"{safe_name}.kicad_mod"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(sexpr, encoding="utf-8")
        format_upgrade = self.upgrade_generated_footprint(out_file)
        result = (
            f"Footprint saved to {out_file}\n"
            f"Package: {package}, Density: {density}"
            + (f", {pin_count} pins" if pin_count else "")
            + (f", {pitch_mm:.2f}mm pitch" if pitch_mm else "")
        )
        if not format_upgrade.upgraded:
            result += (
                "\nFormat note: kept repository writer dialect; "
                f"KiCad migration was unavailable ({format_upgrade.detail})."
            )
        return result

    def validate_footprint_ipc7351(
        self,
        footprint_path: str,
        size_code: str,
        density: str = "B",
        tolerance_mm: float = 0.12,
    ) -> str:
        """Validate a two-terminal chip footprint against IPC-7351B."""
        if density not in ("A", "B", "C"):
            return f"Invalid density '{density}'. Must be A, B, or C."
        try:
            path = self.resolve_within_project(footprint_path)
        except Exception as exc:  # noqa: BLE001 - surface any path-safety rejection
            return f"Invalid footprint path: {exc}"
        if not path.exists():
            return f"Footprint file not found: {path}"
        text = path.read_text(encoding="utf-8", errors="ignore")
        pads = parse_smd_pads(text)
        try:
            result = validate_chip_footprint(
                size_code,
                pads,
                density=density,  # type: ignore[arg-type]
                tol_mm=tolerance_mm,
            )
        except ValueError as exc:
            return f"Validation failed: {exc}"
        lines = [f"Footprint IPC-7351B validation: {result.verdict}", f"- {result.summary}"]
        lines.extend(f"  - {finding}" for finding in result.findings)
        return "\n".join(lines)

    def certify_footprint(self, footprint_path: str) -> str:
        """Certify package, documentation-layer, and IPC-density footprint checks."""
        try:
            path = self.resolve_within_project(footprint_path)
        except Exception as exc:  # noqa: BLE001 - surface any path-safety rejection
            return f"Invalid footprint path: {exc}"
        if not path.exists():
            return f"Footprint file not found: {path}"
        text = path.read_text(encoding="utf-8", errors="ignore")
        name_match = re.search(r'\(footprint\s+"([^"]+)"', text)
        footprint_name = name_match.group(1) if name_match else path.stem

        checks: list[tuple[str, FootprintCheck]] = []
        pad_check = check_footprint_pad_count(footprint_name, text)
        if pad_check is not None:
            checks.append(("pad-count", pad_check))
        checks.append(("documentation-layers", check_footprint_documentation_layers(text)))

        verdicts = {check.verdict for _, check in checks}
        overall = "FAIL" if "FAIL" in verdicts else "WARN" if "WARN" in verdicts else "PASS"
        density = parse_ipc_density(text)
        lines = [
            f"Footprint certification: {overall}",
            f"- Footprint: {footprint_name}",
            f"- IPC-7351 density recorded: {density}"
            if density
            else "- IPC-7351 density: not recorded",
        ]
        if pad_check is None:
            lines.append(
                "- [INFO] pad-count: package name does not encode a certifiable pin count."
            )
        for label, check in checks:
            lines.append(f"- [{check.verdict}] {label}: {check.summary}")
            lines.extend(f"    - {finding}" for finding in check.findings)
        return "\n".join(lines)
