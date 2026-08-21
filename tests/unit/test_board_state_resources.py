from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.models.pcb import StackupLayerSpec
from kicad_mcp.resources import analysis as analysis_resources
from kicad_mcp.resources import board_state
from kicad_mcp.tools.validation import GateOutcome, PlacementAnalysis


class FakeMCP:
    def __init__(self) -> None:
        self.resources: dict[str, object] = {}

    def resource(self, uri: str) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def decorator(func):
            self.resources[uri] = func
            return func

        return decorator


def test_queue_reason_and_suggested_tool_helpers() -> None:
    assert board_state._queue_reason(["FAIL: Dangling wire"], "fallback") == "Dangling wire"
    assert board_state._queue_reason(["WARN: Crowded area"], "fallback") == "Crowded area"
    assert (
        board_state._queue_reason(
            ["Placement score: 98", "  ", "Board frame: checked"],
            "fallback",
        )
        == "fallback"
    )
    assert board_state._queue_reason(["Plain detail"], "fallback") == "Plain detail"
    assert board_state._suggested_tool("Schematic") == "run_erc()"
    assert board_state._suggested_tool("Unknown gate") == "project_quality_gate()"


def test_render_fix_queue_handles_pass_and_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: [GateOutcome("Schematic", "PASS", "All clear")],
    )
    assert "No blocking issues" in board_state._render_fix_queue()

    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: [
            GateOutcome("PCB", "FAIL", "Route review", ["WARN: Clearance near J1"]),
            GateOutcome("Schematic", "BLOCKED", "ERC blocked", ["FAIL: Missing power flag"]),
        ],
    )
    rendered = board_state._render_fix_queue()
    assert "Blocking items: 2" in rendered
    assert "[critical] Schematic: Missing power flag" in rendered
    assert "[high] PCB: Clearance near J1" in rendered


def test_register_resources_exposes_success_paths(monkeypatch, tmp_path: Path) -> None:
    board = SimpleNamespace(
        get_tracks=lambda: [1, 2],
        get_footprints=lambda: [1],
        get_vias=lambda: [1, 2, 3],
        get_nets=lambda netclass_filter=None: ["GND", "3V3"],
        get_as_string=lambda: "abcdefghijklmno",
        get_zones=lambda: [SimpleNamespace(layers=[0])],
    )
    (tmp_path / "demo.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
    cfg = SimpleNamespace(
        project_root=tmp_path,
        project_dir=tmp_path,
        project_file=tmp_path / "demo.kicad_pro",
        pcb_file=tmp_path / "demo.kicad_pcb",
        sch_file=tmp_path / "demo.kicad_sch",
        output_dir=tmp_path / "out",
        max_text_response_chars=8,
    )
    analysis = PlacementAnalysis(
        footprint_count=4,
        board_width_mm=10.0,
        board_height_mm=5.0,
        board_area_mm2=50.0,
        footprint_area_mm2=12.5,
        density_pct=25.0,
        score=92,
    )

    monkeypatch.setattr(board_state, "get_board", lambda: board)
    monkeypatch.setattr(board_state, "get_config", lambda: cfg)
    monkeypatch.setattr(
        "kicad_mcp.tools.project.resolve_design_intent",
        lambda: {"kind": "demo"},
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.project._render_project_spec_resolution",
        lambda resolved: f"spec:{resolved['kind']}",
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.project.load_design_intent",
        lambda: SimpleNamespace(model_dump_json=lambda indent=2: '{"critical_nets": []}'),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: [GateOutcome("PCB", "PASS", "All clear")],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._render_project_gate_report",
        lambda outcomes: f"gate-count:{len(outcomes)}",
    )
    monkeypatch.setattr(board_state, "_render_fix_queue", lambda: "queue-body")
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_connectivity_gate",
        lambda: GateOutcome("Schematic connectivity", "PASS", "Connected"),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._format_gate",
        lambda outcome: f"{outcome.name}:{outcome.status}",
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation.render_gate_by_name",
        lambda gate_name: f"gate:{gate_name}",
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._placement_analysis",
        lambda: (analysis, None),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._format_placement_score",
        lambda payload: f"placement:{payload.score}",
    )

    mcp = FakeMCP()
    board_state.register(mcp)

    assert "Tracks: 2" in mcp.resources["kicad://board/summary"]()
    assert "Project directory:" in mcp.resources["kicad://project/info"]()
    assert '"file_count": 2' in mcp.resources["kicad://project/manifest"]()
    assert mcp.resources["kicad://project/spec"]() == "spec:demo"
    assert '"critical_nets": []' in mcp.resources["kicad://project/design_intent"]()
    assert mcp.resources["kicad://project/next_action"]() == (
        "Project next action:\n"
        "- Status: PASS\n"
        "- Suggested tool: export_manufacturing_package()\n"
        "- Reason: No blocking issues remain."
    )
    assert mcp.resources["kicad://board/netlist"]() == "abcdefgh\n... [truncated]"
    assert mcp.resources["kicad://project/quality_gate"]() == "gate-count:1"
    assert '"history"' in mcp.resources["kicad://project/gate_history"]()
    assert mcp.resources["kicad://project/fix_queue"]() == "queue-body"
    assert mcp.resources["kicad://schematic/connectivity"]() == "Schematic connectivity:PASS"
    assert '"layers"' in mcp.resources["kicad://board/layer_coverage"]()
    assert mcp.resources["kicad://gate/{gate_name}"]("PCB") == "gate:PCB"
    assert mcp.resources["kicad://board/placement_quality"]() == "placement:92"


def test_register_resources_exposes_blocked_paths(monkeypatch, tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        project_root=tmp_path,
        project_dir=tmp_path,
        project_file=tmp_path / "demo.kicad_pro",
        pcb_file=tmp_path / "demo.kicad_pcb",
        sch_file=tmp_path / "demo.kicad_sch",
        output_dir=tmp_path / "out",
        max_text_response_chars=32,
    )
    blocked = GateOutcome("Placement", "BLOCKED", "Move components", ["Too dense"])

    monkeypatch.setattr(board_state, "get_config", lambda: cfg)
    monkeypatch.setattr(
        board_state,
        "get_board",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("offline")),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.project.resolve_design_intent",
        lambda: (_ for _ in ()).throw(RuntimeError("spec failed")),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: (_ for _ in ()).throw(RuntimeError("gate failed")),
    )
    monkeypatch.setattr(
        board_state,
        "_render_fix_queue",
        lambda: (_ for _ in ()).throw(RuntimeError("queue failed")),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_connectivity_gate",
        lambda: (_ for _ in ()).throw(RuntimeError("connectivity failed")),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation.render_gate_by_name",
        lambda gate_name: (_ for _ in ()).throw(RuntimeError(f"{gate_name} failed")),
    )

    mcp = FakeMCP()
    board_state.register(mcp)

    assert "KiCad is not connected" in mcp.resources["kicad://board/summary"]()
    assert '"file_count": 0' in mcp.resources["kicad://project/manifest"]()
    assert "Project design spec: BLOCKED" in mcp.resources["kicad://project/spec"]()
    assert '"status": "blocked"' in mcp.resources["kicad://project/design_intent"]()
    assert "- Status: BLOCKED" in mcp.resources["kicad://project/next_action"]()
    assert "KiCad is not connected" in mcp.resources["kicad://board/netlist"]()
    assert "Project quality gate: BLOCKED" in mcp.resources["kicad://project/quality_gate"]()
    assert '"status": "blocked"' in mcp.resources["kicad://project/gate_history"]()
    assert (
        "Project fix queue\n- BLOCKED: queue failed" == mcp.resources["kicad://project/fix_queue"]()
    )
    assert (
        "Schematic connectivity quality gate: BLOCKED"
        in mcp.resources["kicad://schematic/connectivity"]()
    )
    assert '"status": "blocked"' in mcp.resources["kicad://board/layer_coverage"]()
    assert "Gate 'PCB': BLOCKED" in mcp.resources["kicad://gate/{gate_name}"]("PCB")

    monkeypatch.setattr(
        "kicad_mcp.tools.validation._placement_analysis",
        lambda: (None, blocked),
    )
    blocked_text = mcp.resources["kicad://board/placement_quality"]()
    assert "Placement score: BLOCKED" in blocked_text
    assert "- Move components" in blocked_text
    assert "- Too dense" in blocked_text

    monkeypatch.setattr(
        "kicad_mcp.tools.validation._placement_analysis",
        lambda: (None, None),
    )
    assert (
        mcp.resources["kicad://board/placement_quality"]()
        == "Placement score: BLOCKED\n- Placement analysis returned no data."
    )

    monkeypatch.setattr(
        "kicad_mcp.tools.validation._placement_analysis",
        lambda: (_ for _ in ()).throw(RuntimeError("placement failed")),
    )
    assert (
        "Could not evaluate this resource: placement failed"
        in mcp.resources["kicad://board/placement_quality"]()
    )


def test_analysis_resources_expose_structured_defaults_and_stackup(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.resources.analysis._current_stackup_specs",
        lambda: [
            StackupLayerSpec(
                name="F_Cu",
                type="signal",
                thickness_mm=0.035,
                material="Copper",
            ),
            StackupLayerSpec(
                name="prepreg_1",
                type="dielectric",
                thickness_mm=0.18,
                material="FR4",
                epsilon_r=4.2,
                loss_tangent=0.02,
            ),
            StackupLayerSpec(
                name="B_Cu",
                type="signal",
                thickness_mm=0.035,
                material="Copper",
            ),
        ],
    )

    mcp = FakeMCP()
    analysis_resources.register(mcp)

    materials = mcp.resources["kicad://analysis/materials"]()
    defaults = mcp.resources["kicad://analysis/defaults"]()
    stackup = mcp.resources["kicad://analysis/stackup"]()

    assert '"schema_version": "1.0"' in materials
    assert '"fr4_standard"' in materials
    assert '"schemas"' in defaults
    assert '"trace_impedance"' in defaults
    assert '"total_thickness_mm": 0.25' in stackup
    assert '"copper_layer_count": 2' in stackup
    assert '"loss_tangent": 0.02' in stackup


def test_board_summary_resource_reports_collection_access_failure(monkeypatch) -> None:
    board = SimpleNamespace(
        get_tracks=lambda: [],
        get_footprints=lambda: [],
        get_nets=lambda netclass_filter=None: [],
    )
    monkeypatch.setattr(board_state, "get_board", lambda: board)
    mcp = FakeMCP()
    board_state.register(mcp)

    result = mcp.resources["kicad://board/summary"]()

    assert "Board data is unavailable" in result
    assert "Could not read board vias via get_vias" in result
