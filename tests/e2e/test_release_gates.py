from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kicad_mcp.discovery import CliCapabilities
from kicad_mcp.server import build_server
from kicad_mcp.tools.validation import GateOutcome
from tests.conftest import call_tool_text

BENCHMARK_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "benchmark_projects"


def _load_benchmark(sample_project: Path, fixture_name: str) -> Path:
    fixture_dir = BENCHMARK_ROOT / fixture_name
    if not fixture_dir.is_dir():
        raise FileNotFoundError(f"Missing benchmark fixture: {fixture_name}")

    for entry in sample_project.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    for source in fixture_dir.rglob("*"):
        relative = source.relative_to(fixture_dir)
        target = sample_project / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return sample_project


def _pass_gate(name: str, summary: str) -> GateOutcome:
    return GateOutcome(name=name, status="PASS", summary=summary, details=[summary])


def _pass_outcomes() -> list[GateOutcome]:
    return [
        _pass_gate("Schematic", "ERC is clean."),
        _pass_gate("Schematic connectivity", "Connectivity is structurally sound."),
        _pass_gate("PCB", "PCB passes DRC."),
        _pass_gate("Placement", "Placement is sane."),
        _pass_gate("PCB transfer", "Named pad nets transferred cleanly."),
        _pass_gate("Manufacturing", "DFM checks passed."),
        _pass_gate("Footprint parity", "Schematic and PCB references align."),
    ]


def _set_non_target_gates_to_pass(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target: str,
) -> None:
    target_map = {
        "schematic_connectivity": "_evaluate_schematic_connectivity_gate",
        "placement": "_evaluate_pcb_placement_gate",
        "transfer": "_evaluate_pcb_transfer_gate",
        "manufacturing": "_evaluate_manufacturing_gate",
    }
    for attribute, outcome in (
        ("_evaluate_schematic_gate", _pass_gate("Schematic", "ERC is clean.")),
        (
            "_evaluate_schematic_connectivity_gate",
            _pass_gate("Schematic connectivity", "Connectivity is structurally sound."),
        ),
        ("_evaluate_pcb_gate", _pass_gate("PCB", "PCB passes DRC.")),
        ("_evaluate_pcb_placement_gate", _pass_gate("Placement", "Placement is sane.")),
        (
            "_evaluate_pcb_transfer_gate",
            _pass_gate("PCB transfer", "Named pad nets transferred cleanly."),
        ),
        (
            "_evaluate_manufacturing_gate",
            _pass_gate("Manufacturing", "DFM checks passed."),
        ),
        (
            "_footprint_parity_outcome",
            _pass_gate("Footprint parity", "Schematic and PCB references align."),
        ),
    ):
        if attribute == target_map.get(target):
            continue
        monkeypatch.setattr(
            f"kicad_mcp.tools.validation.{attribute}",
            (lambda gate_outcome: (lambda **_kwargs: gate_outcome))(outcome)
            if attribute == "_evaluate_manufacturing_gate"
            else (lambda gate_outcome: (lambda: gate_outcome))(outcome),
        )


def _fake_export_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.export.get_cli_capabilities",
        lambda _cli: CliCapabilities(version="10.0.0", supports_ipc2581=True),
    )

    def fake_run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        first = variants[0]
        output_index = first.index("--output") + 1
        output_path = Path(first[output_index])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.suffix:
            if output_path.suffix == ".csv":
                output_path.write_text("ref,value\nR1,10k\n", encoding="utf-8")
            else:
                output_path.write_text("generated\n", encoding="utf-8")
        else:
            output_path.mkdir(parents=True, exist_ok=True)
            command_blob = " ".join(first)
            if "gerber" in command_blob:
                (output_path / "board_F_Cu.gbr").write_text("G04*\n", encoding="utf-8")
            if "drill" in command_blob:
                (output_path / "board.drl").write_text("M48\n", encoding="utf-8")
        return 0, "", ""

    monkeypatch.setattr("kicad_mcp.tools.export._run_cli_variants", fake_run_cli_variants)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fixture_name", "target_gate", "expected_text"),
    [
        (
            "fail_label_only_schematic",
            "schematic_connectivity",
            "Schematic connectivity quality gate: FAIL",
        ),
        (
            "fail_sismosmart_like_label_only",
            "schematic_connectivity",
            "Schematic connectivity quality gate: FAIL",
        ),
        (
            "fail_footprint_overlap_board",
            "placement",
            "Placement quality gate: FAIL",
        ),
        (
            "fail_bad_decoupling_placement",
            "placement",
            "Placement quality gate: FAIL",
        ),
        (
            "fail_sensor_cluster_spread",
            "placement",
            "Placement quality gate: FAIL",
        ),
        (
            "fail_dfm_edge_clearance",
            "manufacturing",
            "Manufacturing quality gate: FAIL",
        ),
        (
            "fail_dirty_transfer_wrong_pad_nets",
            "transfer",
            "PCB transfer quality gate: FAIL",
        ),
        (
            "fail_sismosmart_like_hierarchy",
            "schematic_connectivity",
            "Schematic connectivity quality gate: FAIL",
        ),
    ],
)
async def test_benchmark_fail_projects_block_release(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
    target_gate: str,
    expected_text: str,
) -> None:
    _load_benchmark(sample_project, fixture_name)
    _set_non_target_gates_to_pass(monkeypatch, target=target_gate)

    if target_gate == "manufacturing":
        monkeypatch.setattr(
            "kicad_mcp.tools.validation._evaluate_manufacturing_gate",
            lambda **_kwargs: GateOutcome(
                name="Manufacturing",
                status="FAIL",
                summary="Copper-to-edge clearance violates the active DFM profile.",
                details=["FAIL: Copper-to-edge clearance is below the fab minimum."],
            ),
        )
    elif target_gate == "transfer":
        monkeypatch.setattr(
            "kicad_mcp.tools.pcb._export_schematic_net_map",
            lambda: (
                {
                    ("R1", "1"): "VIN",
                    ("R1", "2"): "MID",
                    ("R2", "1"): "MID",
                    ("R2", "2"): "GND",
                },
                "",
            ),
        )

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    gate = await call_tool_text(server, "project_quality_gate", {})
    release = await call_tool_text(server, "export_manufacturing_package", {})

    assert expected_text in gate
    assert "hard-blocked" in release
    assert expected_text in release


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fixture_name",
    ["pass_minimal_mcu_board", "pass_sensor_node"],
)
async def test_benchmark_pass_projects_can_release(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
) -> None:
    _load_benchmark(sample_project, fixture_name)
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: _pass_outcomes(),
    )
    _fake_export_cli(monkeypatch)

    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    gate = await call_tool_text(server, "project_quality_gate", {})
    release = await call_tool_text(server, "export_manufacturing_package", {})

    assert "Project quality gate: PASS" in gate
    assert "hard-blocked" not in release
    assert "Gerber export completed" in release
    assert "Drill export completed" in release
    assert "BOM exported to" in release
    assert "Pick and place data exported to" in release
