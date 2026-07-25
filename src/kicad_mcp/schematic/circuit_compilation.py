"""FastMCP-independent schematic circuit compilation services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..models.schematic import AddLabelInput, AddSymbolInput, AddWireInput, PowerSymbolInput


@dataclass(frozen=True)
class PreparedCircuitInputs:
    """Validated and generated inputs produced by the legacy compilation planner."""

    symbols: list[AddSymbolInput]
    powers: list[PowerSymbolInput]
    labels: list[AddLabelInput]
    wires: list[AddWireInput]
    nets: list[dict[str, Any]]
    generated_wires: list[dict[str, float | bool]]
    unresolved_nets: list[dict[str, Any]]
    resolution_stats: dict[str, int]
    chosen_paper: str


class PrepareInputs(Protocol):
    def __call__(
        self,
        *,
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
        unsafe_routed_wires: bool = False,
        paper: str = "A4",
    ) -> PreparedCircuitInputs: ...


class RenderReport(Protocol):
    def __call__(
        self,
        *,
        symbols: list[AddSymbolInput],
        powers: list[PowerSymbolInput],
        labels: list[AddLabelInput],
        explicit_wires: int,
        nets: list[dict[str, Any]],
        generated_wires: list[dict[str, float | bool]],
        unresolved_nets: list[dict[str, Any]],
        resolution_stats: dict[str, int],
        auto_layout: bool,
        terminalized: bool = True,
    ) -> str: ...


class PlaceSymbolBlock(Protocol):
    def __call__(
        self,
        *,
        lib_id: str,
        x: float,
        y: float,
        reference: str,
        value: str,
        footprint: str = "",
        rotation: int = 0,
        unit: int = 1,
        project_name: str,
        root_uuid: str,
    ) -> str: ...


class LabelBlock(Protocol):
    def __call__(
        self,
        name: str,
        x: float,
        y: float,
        rotation: int,
        *,
        global_label: bool,
        shape: str | None,
    ) -> str: ...


@dataclass(frozen=True)
class SchematicCircuitCompilationService:
    """Analyze net compilation and generate complete schematic documents."""

    active_schematic_file: Callable[[], Path]
    project_name: Callable[[], str]
    read_sheet_paper: Callable[[Path], str]
    read_sheet_paper_declaration: Callable[[Path], str]
    prepare_inputs: PrepareInputs
    render_report: RenderReport
    paper_sizes: Mapping[str, object]
    new_uuid: Callable[[], str]
    load_lib_symbol: Callable[[str, str], str | None]
    snap_point: Callable[[float, float, bool], tuple[float, float]]
    place_symbol_block: PlaceSymbolBlock
    wire_block: Callable[[float, float, float, float], str]
    snap_line: Callable[[float, float, float, float, bool], tuple[float, float, float, float]]
    label_block: LabelBlock
    normalize_connectivity: Callable[[str], str]
    validate_schematic_text: Callable[[str], None]
    transactional_write: Callable[[str, Path, bool], None]
    reload_schematic: Callable[[], str]
    warn_unresolved: Callable[[dict[str, Any]], None]

    def analyze(
        self,
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
        unsafe_routed_wires: bool = False,
    ) -> str:
        """Preview how structured inputs resolve to terminals or routed wires."""
        prepared = self.prepare_inputs(
            symbols=symbols,
            wires=wires,
            labels=labels,
            power_symbols=power_symbols,
            nets=nets,
            snap_to_grid=snap_to_grid,
            auto_layout=auto_layout,
            unsafe_routed_wires=unsafe_routed_wires,
        )
        return self.render_report(
            symbols=prepared.symbols,
            powers=prepared.powers,
            labels=prepared.labels,
            explicit_wires=len(prepared.wires) - len(prepared.generated_wires),
            nets=prepared.nets,
            generated_wires=prepared.generated_wires,
            unresolved_nets=prepared.unresolved_nets,
            resolution_stats=prepared.resolution_stats,
            auto_layout=auto_layout,
            terminalized=not unsafe_routed_wires,
        )

    def build(
        self,
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
        unsafe_routed_wires: bool = False,
    ) -> str:
        """Build and replace the active schematic from structured circuit inputs."""
        schematic_file = self.active_schematic_file()
        start_paper = self.read_sheet_paper(schematic_file)
        prepared = self.prepare_inputs(
            symbols=symbols,
            wires=wires,
            labels=labels,
            power_symbols=power_symbols,
            nets=nets,
            snap_to_grid=snap_to_grid,
            auto_layout=auto_layout,
            unsafe_routed_wires=unsafe_routed_wires,
            paper=start_paper,
        )
        if prepared.unresolved_nets:
            self.warn_unresolved(
                {
                    "generated_wire_count": len(prepared.generated_wires),
                    "unresolved_net_count": len(prepared.unresolved_nets),
                    "unresolved_nets": prepared.unresolved_nets[:10],
                }
            )
        if prepared.nets and not prepared.generated_wires and not prepared.wires:
            examples = "; ".join(
                (
                    f"{item['name']} "
                    f"(resolved {item['resolved_count']}/{item['endpoint_count']}, "
                    f"missing: {', '.join(item['unresolved_endpoints']) or 'all'})"
                )
                for item in prepared.unresolved_nets[:5]
            )
            raise ValueError(
                "Netlist-aware auto-layout could not generate any safe terminal stubs. "
                "The provided nets did not resolve to collision-safe pin endpoints. "
                "Use `sch_analyze_net_compilation()` to inspect unresolved nets, or "
                "provide explicit reference+pin endpoints / explicit wires. "
                f"Examples: {examples or 'no endpoints were routable'}. "
                f"Alias matches: {prepared.resolution_stats['pin_alias_resolutions']}."
            )

        paper_declaration = self.read_sheet_paper_declaration(schematic_file)
        if (
            auto_layout
            and prepared.chosen_paper != start_paper
            and prepared.chosen_paper in self.paper_sizes
        ):
            paper_declaration = f'(paper "{prepared.chosen_paper}")'
        root_uuid = self.new_uuid()
        project_name = self.project_name()
        library_definitions: set[str] = set()
        library_content: list[str] = []
        elements: list[str] = []

        for symbol in prepared.symbols:
            key = f"{symbol.library}:{symbol.symbol_name}"
            if key not in library_definitions:
                library_definition = self.load_lib_symbol(symbol.library, symbol.symbol_name)
                if library_definition is not None:
                    library_content.append(library_definition)
                library_definitions.add(key)

        for power in prepared.powers:
            key = f"power:{power.name}"
            if key not in library_definitions:
                library_definition = self.load_lib_symbol("power", power.name)
                if library_definition is not None:
                    library_content.append(library_definition)
                library_definitions.add(key)

        for symbol in prepared.symbols:
            symbol_x, symbol_y = self.snap_point(
                symbol.x_mm,
                symbol.y_mm,
                snap_to_grid and symbol.snap_to_grid,
            )
            elements.append(
                self.place_symbol_block(
                    lib_id=f"{symbol.library}:{symbol.symbol_name}",
                    x=symbol_x,
                    y=symbol_y,
                    reference=symbol.reference,
                    value=symbol.value,
                    footprint=symbol.footprint,
                    rotation=symbol.rotation,
                    unit=symbol.unit,
                    project_name=project_name,
                    root_uuid=root_uuid,
                )
            )

        for index, power in enumerate(prepared.powers, start=1):
            power_x, power_y = self.snap_point(
                power.x_mm,
                power.y_mm,
                snap_to_grid and power.snap_to_grid,
            )
            elements.append(
                self.place_symbol_block(
                    lib_id=f"power:{power.name}",
                    x=power_x,
                    y=power_y,
                    reference=f"#PWR{index:03d}",
                    value=power.name,
                    rotation=power.rotation,
                    project_name=project_name,
                    root_uuid=root_uuid,
                )
            )

        for wire in prepared.wires:
            elements.append(
                self.wire_block(
                    *self.snap_line(
                        wire.x1_mm,
                        wire.y1_mm,
                        wire.x2_mm,
                        wire.y2_mm,
                        snap_to_grid and wire.snap_to_grid,
                    )
                )
            )

        for label in prepared.labels:
            label_x, label_y = self.snap_point(
                label.x_mm,
                label.y_mm,
                snap_to_grid and label.snap_to_grid,
            )
            elements.append(
                self.label_block(
                    label.name,
                    label_x,
                    label_y,
                    label.rotation,
                    global_label=label.global_label,
                    shape=label.shape,
                )
            )

        library_section = "\t(lib_symbols\n"
        for library_definition in library_content:
            library_section += (
                "\n".join("\t" + line for line in library_definition.splitlines()) + "\n"
            )
        library_section += "\t)"
        content = (
            "(kicad_sch\n"
            "\t(version 20250316)\n"
            '\t(generator "kicad-mcp-pro")\n'
            f'\t(uuid "{root_uuid}")\n'
            f"\t{paper_declaration}\n"
            f"{library_section}\n"
            + "\n".join(elements)
            + (
                "\n\t(sheet_instances\n"
                '\t\t(path "/"\n'
                '\t\t\t(page "1")\n'
                "\t\t)\n"
                "\t)\n"
                "\t(embedded_fonts no)\n"
                ")\n"
            )
        )
        content = self.normalize_connectivity(content)
        self.validate_schematic_text(content)
        self.transactional_write(content, schematic_file, True)
        result = self.reload_schematic()
        notes: list[str] = []
        if auto_layout:
            notes.append("Applied auto-layout to schematic symbols.")
        if prepared.nets:
            if unsafe_routed_wires:
                notes.append(
                    f"Generated {len(prepared.generated_wires)} routed wire segment(s) in "
                    "unsafe routed mode — these can short by crossing geometry; "
                    "prefer the default terminal strategy."
                )
            else:
                notes.append(
                    f"Generated {len(prepared.generated_wires)} collision-safe terminal "
                    "stub(s); nets connect by name."
                )
            if prepared.unresolved_nets:
                names = ", ".join(str(item["name"]) for item in prepared.unresolved_nets[:8])
                more = " …" if len(prepared.unresolved_nets) > 8 else ""
                notes.append(
                    f"WARNING: {len(prepared.unresolved_nets)} net(s) could not be "
                    f"terminalized safely and were left unconnected: {names}{more}. "
                    "Use sch_analyze_net_compilation() for per-endpoint details."
                )
        if notes:
            return result + "\n" + "\n".join(notes)
        return result
