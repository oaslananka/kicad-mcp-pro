from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kicad_mcp.models.schematic import (
    AddLabelInput,
    AddSymbolInput,
    AddWireInput,
    PowerSymbolInput,
)
from kicad_mcp.schematic.circuit_compilation import (
    PreparedCircuitInputs,
    SchematicCircuitCompilationService,
)


class CompilationHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.schematic = tmp_path / "demo.kicad_sch"
        self.schematic.write_text('(kicad_sch\n\t(paper "A4")\n)\n', encoding="utf-8")
        self.start_paper = "A4"
        self.paper_declaration = '(paper "A4")'
        self.prepared = PreparedCircuitInputs(
            symbols=[],
            powers=[],
            labels=[],
            wires=[],
            nets=[],
            generated_wires=[],
            unresolved_nets=[],
            resolution_stats={
                "resolved_endpoints": 0,
                "unresolved_endpoints": 0,
                "pin_alias_resolutions": 0,
                "symbol_center_resolutions": 0,
            },
            chosen_paper="A4",
        )
        self.snapshot_result: tuple[int, int, Path | None] = (0, 0, None)
        self.snapshot_calls: list[Path] = []
        self.prepare_calls: list[dict[str, Any]] = []
        self.report_calls: list[dict[str, Any]] = []
        self.library_calls: list[tuple[str, str]] = []
        self.warn_calls: list[dict[str, Any]] = []
        self.transaction_calls: list[tuple[Path, bool, str]] = []
        self.events: list[str] = []

    def service(self) -> SchematicCircuitCompilationService:
        return SchematicCircuitCompilationService(
            active_schematic_file=lambda: self.schematic,
            project_name=lambda: "demo-project",
            snapshot_before_replace=self.snapshot_before_replace,
            read_sheet_paper=lambda path: self.start_paper,
            read_sheet_paper_declaration=lambda path: self.paper_declaration,
            prepare_inputs=self.prepare_inputs,
            render_report=self.render_report,
            paper_sizes={"A4": object(), "A3": object()},
            new_uuid=lambda: "root-uuid",
            load_lib_symbol=self.load_lib_symbol,
            snap_point=lambda x, y, enabled: (x, y),
            place_symbol_block=self.place_symbol_block,
            wire_block=lambda x1, y1, x2, y2: f"WIRE:{x1},{y1}->{x2},{y2}",
            snap_line=lambda x1, y1, x2, y2, enabled: (x1, y1, x2, y2),
            label_block=self.label_block,
            normalize_connectivity=self.normalize_connectivity,
            validate_schematic_text=self.validate_schematic_text,
            transactional_write=self.transactional_write,
            reload_schematic=self.reload_schematic,
            warn_unresolved=self.warn_unresolved,
        )

    def snapshot_before_replace(self, path: Path) -> tuple[int, int, Path | None]:
        self.snapshot_calls.append(path)
        return self.snapshot_result

    def prepare_inputs(
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
    ) -> PreparedCircuitInputs:
        self.prepare_calls.append(
            {
                "symbols": symbols,
                "wires": wires,
                "labels": labels,
                "power_symbols": power_symbols,
                "nets": nets,
                "snap_to_grid": snap_to_grid,
                "auto_layout": auto_layout,
                "unsafe_routed_wires": unsafe_routed_wires,
                "paper": paper,
            }
        )
        return self.prepared

    def render_report(
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
    ) -> str:
        self.report_calls.append(
            {
                "symbols": symbols,
                "powers": powers,
                "labels": labels,
                "explicit_wires": explicit_wires,
                "nets": nets,
                "generated_wires": generated_wires,
                "unresolved_nets": unresolved_nets,
                "resolution_stats": resolution_stats,
                "auto_layout": auto_layout,
                "terminalized": terminalized,
            }
        )
        return "analysis"

    def load_lib_symbol(self, library: str, symbol_name: str) -> str | None:
        self.library_calls.append((library, symbol_name))
        return f'(symbol "{library}:{symbol_name}")'

    def place_symbol_block(
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
    ) -> str:
        values = {
            "lib_id": lib_id,
            "x": x,
            "y": y,
            "reference": reference,
            "value": value,
            "footprint": footprint,
            "rotation": rotation,
            "unit": unit,
            "project_name": project_name,
            "root_uuid": root_uuid,
        }
        return "SYMBOL:" + ",".join(f"{key}={value}" for key, value in sorted(values.items()))

    def label_block(
        self,
        name: str,
        x: float,
        y: float,
        rotation: int,
        *,
        global_label: bool,
        shape: str | None,
        kind: str | None = None,
    ) -> str:
        return f"LABEL:{name},{x},{y},{rotation},{global_label},{shape},{kind}"

    def normalize_connectivity(self, content: str) -> str:
        self.events.append("normalize")
        return content + ";normalized"

    def validate_schematic_text(self, content: str) -> None:
        self.events.append("validate")
        assert content.endswith(";normalized")

    def transactional_write(self, content: str, path: Path, allow_node_loss: bool) -> None:
        self.events.append("write")
        self.transaction_calls.append((path, allow_node_loss, content))
        path.write_text(content, encoding="utf-8")

    def reload_schematic(self) -> str:
        self.events.append("reload")
        return "reloaded"

    def warn_unresolved(self, payload: dict[str, Any]) -> None:
        self.warn_calls.append(dict(payload))


def _symbol(reference: str = "R1") -> AddSymbolInput:
    return AddSymbolInput(
        library="Device",
        symbol_name="R",
        x_mm=10.0,
        y_mm=20.0,
        reference=reference,
        value="10k",
        footprint="Resistor_SMD:R_0805",
    )


def _power(name: str = "GND") -> PowerSymbolInput:
    return PowerSymbolInput(name=name, x_mm=5.0, y_mm=6.0)


def test_analyze_delegates_preparation_and_report_arguments(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    harness.prepared = PreparedCircuitInputs(
        symbols=[_symbol()],
        powers=[_power()],
        labels=[AddLabelInput(name="NET", x_mm=1.0, y_mm=2.0)],
        wires=[
            AddWireInput(x1_mm=0.0, y1_mm=0.0, x2_mm=1.0, y2_mm=1.0),
            AddWireInput(x1_mm=1.0, y1_mm=1.0, x2_mm=2.0, y2_mm=2.0),
        ],
        nets=[{"name": "NET"}],
        generated_wires=[{"x1_mm": 1.0, "y1_mm": 1.0, "x2_mm": 2.0, "y2_mm": 2.0}],
        unresolved_nets=[],
        resolution_stats={
            "resolved_endpoints": 2,
            "unresolved_endpoints": 0,
            "pin_alias_resolutions": 1,
            "symbol_center_resolutions": 0,
        },
        chosen_paper="A4",
    )

    result = harness.service().analyze(
        symbols=[{"reference": "R1"}],
        nets=[{"name": "NET"}],
        auto_layout=True,
        unsafe_routed_wires=True,
    )

    assert result == "analysis"
    assert harness.prepare_calls == [
        {
            "symbols": [{"reference": "R1"}],
            "wires": None,
            "labels": None,
            "power_symbols": None,
            "nets": [{"name": "NET"}],
            "snap_to_grid": True,
            "auto_layout": True,
            "unsafe_routed_wires": True,
            "paper": "A4",
        }
    ]
    assert harness.report_calls[0]["explicit_wires"] == 1
    assert harness.report_calls[0]["terminalized"] is False
    assert harness.report_calls[0]["auto_layout"] is True


def test_build_raises_when_no_net_endpoint_can_be_generated(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    unresolved = {
        "name": "BROKEN",
        "endpoint_count": 2,
        "resolved_count": 0,
        "unresolved_endpoints": ["U9.1", "U10.2"],
    }
    harness.prepared = PreparedCircuitInputs(
        symbols=[],
        powers=[],
        labels=[],
        wires=[],
        nets=[{"name": "BROKEN"}],
        generated_wires=[],
        unresolved_nets=[unresolved],
        resolution_stats={
            "resolved_endpoints": 0,
            "unresolved_endpoints": 2,
            "pin_alias_resolutions": 3,
            "symbol_center_resolutions": 0,
        },
        chosen_paper="A4",
    )

    with pytest.raises(ValueError, match="could not generate any safe terminal stubs") as exc:
        harness.service().build(nets=[{"name": "BROKEN"}])

    assert "BROKEN (resolved 0/2, missing: U9.1, U10.2)" in str(exc.value)
    assert "Alias matches: 3" in str(exc.value)
    assert harness.warn_calls == [
        {
            "generated_wire_count": 0,
            "unresolved_net_count": 1,
            "unresolved_nets": [unresolved],
        }
    ]
    assert harness.transaction_calls == []


def test_build_empty_preserves_paper_and_transaction_order(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    harness.paper_declaration = '(paper "User" 298.45 217.3224)'

    result = harness.service().build()

    assert result == (
        "reloaded\n"
        "Sheet replaced: removed 0 symbol(s) and 0 label(s), "
        "wrote 0 symbol(s) and 0 label(s)."
    )
    assert harness.snapshot_calls == [harness.schematic]
    assert harness.events == ["normalize", "validate", "write", "reload"]
    path, allow_node_loss, content = harness.transaction_calls[0]
    assert path == harness.schematic
    assert allow_node_loss is True
    assert '\t(paper "User" 298.45 217.3224)' in content
    assert '\t(uuid "root-uuid")' in content
    assert '\t(generator "kicad-mcp-pro")' in content


def test_build_promotes_named_paper_when_auto_layout_grows(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    harness.prepared = PreparedCircuitInputs(
        symbols=[],
        powers=[],
        labels=[],
        wires=[],
        nets=[],
        generated_wires=[],
        unresolved_nets=[],
        resolution_stats={
            "resolved_endpoints": 0,
            "unresolved_endpoints": 0,
            "pin_alias_resolutions": 0,
            "symbol_center_resolutions": 0,
        },
        chosen_paper="A3",
    )

    result = harness.service().build(auto_layout=True)

    assert '\t(paper "A3")' in harness.transaction_calls[0][2]
    assert result == (
        "reloaded\n"
        "Sheet replaced: removed 0 symbol(s) and 0 label(s), "
        "wrote 0 symbol(s) and 0 label(s).\n"
        "Applied auto-layout to schematic symbols."
    )


def test_build_deduplicates_libraries_and_generates_all_element_types(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    harness.prepared = PreparedCircuitInputs(
        symbols=[_symbol("R1"), _symbol("R2")],
        powers=[_power("GND"), _power("GND")],
        labels=[
            AddLabelInput(
                name="NET_A",
                x_mm=3.0,
                y_mm=4.0,
                rotation=90,
                global_label=True,
                shape="input",
            )
        ],
        wires=[AddWireInput(x1_mm=1.0, y1_mm=2.0, x2_mm=3.0, y2_mm=4.0)],
        nets=[],
        generated_wires=[],
        unresolved_nets=[],
        resolution_stats={
            "resolved_endpoints": 0,
            "unresolved_endpoints": 0,
            "pin_alias_resolutions": 0,
            "symbol_center_resolutions": 0,
        },
        chosen_paper="A4",
    )

    harness.service().build(snap_to_grid=False)

    assert harness.library_calls == [("Device", "R"), ("power", "GND")]
    content = harness.transaction_calls[0][2]
    assert content.count('(symbol "Device:R")') == 1
    assert content.count('(symbol "power:GND")') == 1
    assert "reference=R1" in content and "reference=R2" in content
    assert "reference=#PWR001" in content and "reference=#PWR002" in content
    assert "WIRE:1.0,2.0->3.0,4.0" in content
    assert "LABEL:NET_A,3.0,4.0,90,True,input,None" in content
    assert "project_name=demo-project" in content


def test_build_threads_label_kind_to_label_block(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    harness.prepared = PreparedCircuitInputs(
        symbols=[],
        powers=[],
        labels=[
            AddLabelInput(
                name="BUS",
                x_mm=1.0,
                y_mm=2.0,
                kind="hierarchical_label",
                shape="input",
            )
        ],
        wires=[],
        nets=[],
        generated_wires=[],
        unresolved_nets=[],
        resolution_stats={
            "resolved_endpoints": 0,
            "unresolved_endpoints": 0,
            "pin_alias_resolutions": 0,
            "symbol_center_resolutions": 0,
        },
        chosen_paper="A4",
    )

    harness.service().build(snap_to_grid=False)

    content = harness.transaction_calls[0][2]
    assert "LABEL:BUS,1.0,2.0,0,False,input,hierarchical_label" in content


def test_build_reports_terminalized_and_partial_unresolved_notes(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    harness.prepared = PreparedCircuitInputs(
        symbols=[],
        powers=[],
        labels=[],
        wires=[AddWireInput(x1_mm=0.0, y1_mm=0.0, x2_mm=1.0, y2_mm=1.0)],
        nets=[{"name": "GOOD"}, {"name": "BROKEN"}],
        generated_wires=[{"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 1.0, "y2_mm": 1.0}],
        unresolved_nets=[
            {
                "name": "BROKEN",
                "endpoint_count": 2,
                "resolved_count": 1,
                "unresolved_endpoints": ["U9.1"],
            }
        ],
        resolution_stats={
            "resolved_endpoints": 3,
            "unresolved_endpoints": 1,
            "pin_alias_resolutions": 0,
            "symbol_center_resolutions": 0,
        },
        chosen_paper="A4",
    )

    result = harness.service().build(nets=[{"name": "GOOD"}, {"name": "BROKEN"}])

    assert "Generated 1 collision-safe terminal stub(s); nets connect by name." in result
    assert "WARNING: 1 net(s) could not be terminalized safely" in result
    assert "BROKEN" in result
    assert harness.warn_calls[0]["unresolved_net_count"] == 1


def test_build_reports_unsafe_routed_wire_note(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    harness.prepared = PreparedCircuitInputs(
        symbols=[],
        powers=[],
        labels=[],
        wires=[AddWireInput(x1_mm=0.0, y1_mm=0.0, x2_mm=1.0, y2_mm=1.0)],
        nets=[{"name": "NET"}],
        generated_wires=[{"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 1.0, "y2_mm": 1.0}],
        unresolved_nets=[],
        resolution_stats={
            "resolved_endpoints": 2,
            "unresolved_endpoints": 0,
            "pin_alias_resolutions": 0,
            "symbol_center_resolutions": 0,
        },
        chosen_paper="A4",
    )

    result = harness.service().build(
        nets=[{"name": "NET"}],
        unsafe_routed_wires=True,
    )

    assert "Generated 1 routed wire segment(s) in unsafe routed mode" in result
    assert "prefer the default terminal strategy" in result


def test_build_reports_replaced_counts_and_backup_for_nonempty_sheet(
    tmp_path: Path,
) -> None:
    harness = CompilationHarness(tmp_path)
    backup = tmp_path / "demo.kicad_sch.20260813-101112.bak"
    harness.snapshot_result = (32, 120, backup)
    harness.prepared = PreparedCircuitInputs(
        symbols=[_symbol("R1"), _symbol("R2")],
        powers=[_power("GND")],
        labels=[AddLabelInput(name="NET_A", x_mm=3.0, y_mm=4.0)],
        wires=[],
        nets=[],
        generated_wires=[],
        unresolved_nets=[],
        resolution_stats={
            "resolved_endpoints": 0,
            "unresolved_endpoints": 0,
            "pin_alias_resolutions": 0,
            "symbol_center_resolutions": 0,
        },
        chosen_paper="A4",
    )

    result = harness.service().build()

    assert harness.snapshot_calls == [harness.schematic]
    assert (
        "Sheet replaced: removed 32 symbol(s) and 120 label(s), "
        "wrote 3 symbol(s) and 1 label(s)." in result
    )
    assert f"Backup of the previous sheet: {backup}." in result


def test_build_empty_sheet_makes_no_backup_claim(tmp_path: Path) -> None:
    harness = CompilationHarness(tmp_path)
    harness.snapshot_result = (0, 0, None)

    result = harness.service().build()

    assert (
        "Sheet replaced: removed 0 symbol(s) and 0 label(s), "
        "wrote 0 symbol(s) and 0 label(s)." in result
    )
    assert "Backup" not in result
