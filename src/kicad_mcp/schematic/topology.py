"""Pure result construction for schematic hierarchy and connectivity inspection."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .sheet_pins import edge_for_rotation, parse_sheet_blocks


class SheetManagerLike(Protocol):
    """Sheet-manager surface consumed by topology inspection."""

    def get_sheet_hierarchy(self) -> Mapping[str, Any]: ...

    def get_sheet_by_name(self, sheet_name: str) -> Mapping[str, Any] | None: ...


class LoadedSchematicLike(Protocol):
    """Loaded schematic surface consumed by topology inspection."""

    @property
    def sheets(self) -> SheetManagerLike: ...


class Warn(Protocol):
    """Structured warning callback supplied by the composition root."""

    def __call__(self, event: str, **context: object) -> None: ...


type LoadSchematic = Callable[[Path], LoadedSchematicLike]
type WithDiagnostics = Callable[[str, Path], str]
type BuildConnectivityGroups = Callable[[Path], list[dict[str, Any]]]
type IterChildSheetPaths = Callable[[Path], list[tuple[str, Path]]]
type ParseSchematic = Callable[[Path], Mapping[str, Any]]
type ReadText = Callable[[Path], str]


@dataclass(frozen=True)
class SchematicTopologyService:
    """Format hierarchy and connectivity results from injected dependencies."""

    load_schematic: LoadSchematic
    with_diagnostics: WithDiagnostics
    build_connectivity_groups: BuildConnectivityGroups
    iter_child_sheet_paths: IterChildSheetPaths
    parse_schematic: ParseSchematic
    warn: Warn
    read_text: ReadText

    def list_sheets(self, schematic_file: Path) -> str:
        """List direct child sheets from the active top-level schematic."""
        try:
            schematic = self.load_schematic(schematic_file)
            hierarchy = schematic.sheets.get_sheet_hierarchy()
        except Exception as exc:
            self.warn(
                "schematic_list_sheets_failed",
                schematic_file=str(schematic_file),
                error=str(exc),
            )
            return self.with_diagnostics(
                f"Could not inspect sheet hierarchy: {exc}",
                schematic_file,
            )

        children = hierarchy.get("root", {}).get("children", [])
        if not children:
            return self.with_diagnostics(
                "The active schematic has no child sheets.",
                schematic_file,
            )

        lines = [f"Child sheets ({len(children)} total):"]
        for child in children:
            position = child.get("position")
            size = child.get("size")
            lines.append(
                f"- {child.get('name')} -> {child.get('filename')} "
                f"@ ({float(position.x):.2f}, {float(position.y):.2f}) "
                f"size=({float(size.x):.2f}, {float(size.y):.2f})"
            )
        return "\n".join(lines)

    def sheet_info(self, schematic_file: Path, sheet_name: str) -> str:
        """Return metadata for one direct child sheet."""
        try:
            schematic = self.load_schematic(schematic_file)
            info = schematic.sheets.get_sheet_by_name(sheet_name)
        except Exception as exc:
            self.warn(
                "schematic_get_sheet_info_failed",
                schematic_file=str(schematic_file),
                sheet_name=sheet_name,
                error=str(exc),
            )
            return f"Could not inspect sheet '{sheet_name}': {exc}"

        if info is None:
            return f"Sheet '{sheet_name}' was not found."

        pins = info.get("pins", [])
        position = info.get("position", {})
        size = info.get("size", {})
        lines = [f"Sheet '{sheet_name}'"]
        lines.append(f"- File: {info.get('filename')}")
        lines.append(
            "- Position: "
            f"({float(position.get('x', 0.0)):.2f}, {float(position.get('y', 0.0)):.2f}) mm"
        )
        lines.append(
            "- Size: "
            f"({float(size.get('width', 0.0)):.2f}, {float(size.get('height', 0.0)):.2f}) mm"
        )
        lines.append(f"- Page: {info.get('page_number', '?')}")
        lines.append(f"- Pins: {len(pins)}")
        return "\n".join(lines)

    def connectivity_graph(self, schematic_file: Path) -> str:
        """Summarize normalized connectivity groups."""
        groups = self.build_connectivity_groups(schematic_file)
        if not groups:
            return self.with_diagnostics(
                "The active schematic has no connectivity to summarize.",
                schematic_file,
            )

        lines = [f"Connectivity groups ({len(groups)} total):"]
        for index, group in enumerate(groups, start=1):
            if group["names"]:
                names = ", ".join(group["names"])
            elif group.get("no_connect"):
                names = "~no-connect"
            else:
                names = "~unnamed"
            pins = (
                ", ".join(f"{item['reference']}:{item['pin']}" for item in group["pins"]) or "none"
            )
            lines.append(f"- Group {index}: {names} | pins={pins} | points={len(group['points'])}")
        return "\n".join(lines)

    def trace_net(self, schematic_file: Path, net_name: str) -> str:
        """Trace a named net through the active schematic and child sheets."""
        local_matches = [
            group
            for group in self.build_connectivity_groups(schematic_file)
            if net_name in group["names"]
        ]

        child_matches: list[str] = []
        for display_name, child_path in self.iter_child_sheet_paths(schematic_file):
            if not child_path.exists():
                continue
            child_data = self.parse_schematic(child_path)
            matched_labels = [
                label for label in child_data["labels"] if str(label["name"]) == net_name
            ]
            matched_power = [
                symbol for symbol in child_data["power_symbols"] if str(symbol["value"]) == net_name
            ]
            if matched_labels or matched_power:
                child_matches.append(
                    f"- {display_name}: labels={len(matched_labels)} "
                    f"power_symbols={len(matched_power)}"
                )

        if not local_matches and not child_matches:
            return f"Net '{net_name}' was not found in the active schematic or child sheets."

        lines = [f"Trace for net '{net_name}':"]
        for index, group in enumerate(local_matches, start=1):
            pins = (
                ", ".join(f"{item['reference']}:{item['pin']}" for item in group["pins"]) or "none"
            )
            lines.append(f"- Top level match {index}: pins={pins} points={len(group['points'])}")
        if child_matches:
            lines.append("Child sheet matches:")
            lines.extend(child_matches)
        return "\n".join(lines)

    def list_sheet_pins(self, schematic_file: Path, sheet_name: str) -> str:
        """List the hierarchical sheet pins of one child sheet symbol."""
        try:
            text = self.read_text(schematic_file)
        except OSError as exc:
            self.warn(
                "schematic_list_sheet_pins_failed",
                schematic_file=str(schematic_file),
                sheet_name=sheet_name,
                error=str(exc),
            )
            return f"Could not read '{schematic_file.name}': {exc}"

        block = next(
            (candidate for candidate in parse_sheet_blocks(text) if candidate.name == sheet_name),
            None,
        )
        if block is None:
            return f"Sheet '{sheet_name}' was not found."
        if not block.pins:
            return (
                f"Sheet '{sheet_name}' has no sheet pins. "
                "Run sch_import_sheet_pins to derive them from its hierarchical labels."
            )

        lines = [f"Sheet '{sheet_name}' has {len(block.pins)} pins:"]
        for pin in block.pins:
            edge = edge_for_rotation(pin.rotation)
            kind = f"{pin.pin_type}, {edge}" if edge else pin.pin_type
            lines.append(f"- {pin.name} ({kind}) @ ({pin.x_mm}, {pin.y_mm}) mm")
        lines.append(
            f"Sheet symbol at ({block.origin[0]}, {block.origin[1]}) mm, "
            f"{block.size[0]} x {block.size[1]} mm."
        )
        return "\n".join(lines)
