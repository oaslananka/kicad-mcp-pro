"""Local symbol and footprint authoring behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.sexpr import _sexpr_string


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
            content = '(kicad_symbol_lib (version 20250316) (generator "kicad-mcp-pro"))\n'
        content = _append_symbol(content, _render_symbol_block(name, pins))
        library_file.write_text(content, encoding="utf-8")
        return f"Created custom symbol '{name}' in {library_file}."
