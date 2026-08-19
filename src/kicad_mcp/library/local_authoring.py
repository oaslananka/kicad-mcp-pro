"""Local symbol and footprint authoring behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..file_formats import GENERATED_SEXPR_DIALECT_VERSION
from ..utils.sexpr import _sexpr_string
from ..utils.symbol_gen import PinSpec, generate_symbol


class UpgradeResultProtocol(Protocol):
    @property
    def upgraded(self) -> bool: ...

    @property
    def detail(self) -> str: ...


def _render_pin_blocks(pins: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    y = 0.0
    for index, pin in enumerate(pins, start=1):
        pin_number = str(pin.get("number", index))
        pin_name = str(pin.get("name", f"PIN{index}"))
        blocks.append(
            "\t\t(pin passive line\n"
            f"\t\t\t(at 0.0 {y} 180)\n"
            "\t\t\t(length 2.54)\n"
            f"\t\t\t(name {_sexpr_string(pin_name)} "
            "(effects (font (size 1.27 1.27))))\n"
            f"\t\t\t(number {_sexpr_string(pin_number)} "
            "(effects (font (size 1.27 1.27))))\n"
            "\t\t)\n"
        )
        y -= 2.54
    return "".join(blocks)


def _render_symbol_block(name: str, pins: list[dict[str, Any]]) -> str:
    return (
        f"\t(symbol {_sexpr_string(name)}\n"
        '\t\t(property "Reference" "U" (id 0) (at 0 5.08 0) '
        "(effects (font (size 1.27 1.27))))\n"
        f'\t\t(property "Value" {_sexpr_string(name)} (id 1) (at 0 -5.08 0) '
        "(effects (font (size 1.27 1.27))))\n" + _render_pin_blocks(pins) + "\t)\n"
    )


def _append_symbol(content: str, symbol_block: str) -> str:
    if content.rstrip().endswith(")"):
        return content.rstrip()[:-1] + f"\n{symbol_block})\n"
    return content + symbol_block


@dataclass(frozen=True, slots=True)
class LibraryLocalAuthoringService:
    """File-backed local library authoring independent of FastMCP."""

    footprint_file: Callable[[str, str], Path]
    update_symbol_property: Callable[[str, str, str], object]
    project_dir: Callable[[], Path | None]
    upgrade_symbol_library: Callable[[Path], UpgradeResultProtocol | None] | None = None
    resolve_within_project: Callable[[str], Path] | None = None
    default_output_dir: Callable[[], Path] | None = None

    def assign_footprint(self, reference: str, library: str, footprint: str) -> str:
        path = self.footprint_file(library, footprint)
        if not path.exists():
            return f"Footprint '{library}:{footprint}' was not found."
        assignment = f"{library}:{footprint}"
        self.update_symbol_property(reference, "Footprint", assignment)
        return f"Assigned footprint '{assignment}' to '{reference}'."

    def create_custom_symbol(self, name: str, pins: list[dict[str, Any]]) -> str:
        project_dir = self.project_dir()
        if project_dir is None:
            return "No active project is configured."

        library_file = project_dir / "custom_symbols.kicad_sym"
        if library_file.exists():
            content = library_file.read_text(encoding="utf-8", errors="ignore")
        else:
            content = (
                f"(kicad_symbol_lib (version {GENERATED_SEXPR_DIALECT_VERSION}) "
                '(generator "kicad-mcp-pro"))\n'
            )
        content = _append_symbol(content, _render_symbol_block(name, pins))
        library_file.write_text(content, encoding="utf-8")
        if self.upgrade_symbol_library is not None:
            self.upgrade_symbol_library(library_file)
        return f"Created custom symbol '{name}' in {library_file}."

    def generate_symbol_from_pintable(
        self,
        name: str,
        pins: list[dict[str, Any]],
        reference_prefix: str = "U",
        description: str = "",
        datasheet: str = "",
        footprint_hint: str = "",
        output_path: str = "",
    ) -> str:
        """Generate a KiCad symbol library from structured pin-table data."""
        pin_specs: list[PinSpec] = []
        for raw in pins:
            try:
                pin_specs.append(
                    PinSpec(
                        number=raw["number"],
                        name=raw["name"],
                        pin_type=raw.get("pin_type", "bidirectional"),
                        side=raw.get("side", "left"),
                        unit=int(raw.get("unit", 1)),
                    )
                )
            except (KeyError, ValueError) as exc:
                return f"Invalid pin specification: {exc} — raw: {raw}"

        try:
            sexpr = generate_symbol(
                name,
                pin_specs,
                reference_prefix=reference_prefix,
                description=description,
                datasheet=datasheet,
                footprint_hint=footprint_hint,
            )
        except Exception as exc:
            return f"Symbol generation failed: {exc}"

        if output_path:
            if self.resolve_within_project is None:
                return "No project path resolver is configured."
            out_file = self.resolve_within_project(output_path)
        else:
            if self.default_output_dir is not None:
                out_dir = self.default_output_dir() / "symbols"
            else:
                project_dir = self.project_dir()
                if project_dir is None:
                    return "No active project is configured."
                out_dir = project_dir / "output" / "symbols"
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_name = name.replace(" ", "_").replace("/", "_")
            out_file = out_dir / f"{safe_name}.kicad_sym"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(sexpr, encoding="utf-8")
        format_upgrade = (
            self.upgrade_symbol_library(out_file)
            if self.upgrade_symbol_library is not None
            else None
        )
        result = (
            f"Symbol saved to {out_file}\n"
            f"Name: {name}, Pins: {len(pin_specs)}, Ref prefix: {reference_prefix}"
        )
        if format_upgrade is not None and not format_upgrade.upgraded:
            result += (
                "\nFormat note: kept repository writer dialect; "
                f"KiCad migration was unavailable ({format_upgrade.detail})."
            )
        return result
