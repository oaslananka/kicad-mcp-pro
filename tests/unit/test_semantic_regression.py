"""Semantic regression tests for known defect classes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures"
FIXTURES_DIR = FIXTURES_ROOT / "benchmark_projects"
MANIFEST_PATH = FIXTURES_ROOT / "manifest.yaml"


def _manifest() -> dict[str, object]:
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


class TestBenchmarkManifest:
    """Regression manifest coverage for known benchmark fixtures."""

    def test_manifest_lists_all_current_benchmark_projects(self) -> None:
        manifest = _manifest()
        fixtures = manifest["fixtures"]

        assert isinstance(fixtures, list)
        assert len(fixtures) >= 14
        assert {entry["id"] for entry in fixtures} == {
            "pass_minimal_mcu_board",
            "pass_sensor_node",
            "fail_bad_decoupling_placement",
            "fail_dfm_edge_clearance",
            "fail_dirty_transfer_wrong_pad_nets",
            "fail_footprint_overlap_board",
            "fail_label_only_schematic",
            "fail_sensor_cluster_spread",
            "fail_sismosmart_like_hierarchy",
            "fail_sismosmart_like_label_only",
            "kicad10_custom_drc",
            "kicad10_design_blocks",
            "kicad10_timedomain",
            "kicad10_variants",
        }

    def test_manifest_fixture_directories_exist(self) -> None:
        manifest = _manifest()

        for entry in manifest["fixtures"]:
            fixture_dir = FIXTURES_ROOT / entry["dir"]
            assert fixture_dir.exists(), f"Missing fixture dir: {fixture_dir}"
            assert (fixture_dir / "demo.kicad_pro").exists()

    def test_manifest_declares_known_defect_classes(self) -> None:
        manifest = _manifest()
        defect_classes = {
            entry["defect_class"] for entry in manifest["fixtures"] if "defect_class" in entry
        }

        assert {
            "dfm_placement",
            "dfm_clearance",
            "netlist_mismatch",
            "footprint_overlap",
            "erc_label_only",
            "dfm_clustering",
            "multi_sheet_bom",
            "multi_sheet_labels",
        } <= defect_classes


class TestMultiSheetBOM:
    """Regression: BOM only counted active/root sheet, not all hierarchical sheets."""

    def test_hierarchy_fixture_has_multiple_sheets(self) -> None:
        fixture_dir = FIXTURES_DIR / "fail_sismosmart_like_hierarchy"
        sch_files = list(fixture_dir.glob("*.kicad_sch"))

        assert len(sch_files) > 1, (
            "Multi-sheet BOM regression fixture must contain multiple .kicad_sch files. "
            f"Found only: {sch_files}"
        )

    def test_label_only_fixture_exists(self) -> None:
        fixture_dir = FIXTURES_DIR / "fail_sismosmart_like_label_only"

        assert fixture_dir.exists(), f"Missing fixture dir: {fixture_dir}"
        assert (fixture_dir / "demo.kicad_sch").exists()


class TestKnownDefectFixtures:
    """Regression fixture existence for distinct semantic defect classes."""

    @pytest.mark.parametrize(
        ("fixture_name", "required_file"),
        [
            ("fail_bad_decoupling_placement", "demo.kicad_pcb"),
            ("fail_dfm_edge_clearance", "demo.kicad_pcb"),
            ("fail_dirty_transfer_wrong_pad_nets", "demo.kicad_sch"),
            ("fail_footprint_overlap_board", "demo.kicad_pcb"),
            ("fail_label_only_schematic", "demo.kicad_sch"),
            ("fail_sensor_cluster_spread", "demo.kicad_pcb"),
        ],
    )
    def test_regression_fixture_has_required_file(
        self,
        fixture_name: str,
        required_file: str,
    ) -> None:
        fixture_dir = FIXTURES_DIR / fixture_name

        assert fixture_dir.exists()
        assert (fixture_dir / required_file).exists()

    def test_dirty_transfer_fixture_has_board_and_schematic(self) -> None:
        fixture_dir = FIXTURES_DIR / "fail_dirty_transfer_wrong_pad_nets"

        assert (fixture_dir / "demo.kicad_sch").exists()
        assert (fixture_dir / "demo.kicad_pcb").exists()


class TestToolResultEnvelope:
    """Regression: tool results must support a structured output envelope."""

    def test_success_factory(self) -> None:
        from kicad_mcp.models.tool_result import ToolResult

        result = ToolResult.success("test_tool", changed=True)

        assert result.ok is True
        assert result.changed is True
        assert result.tool_name == "test_tool"

    def test_failure_factory(self) -> None:
        from kicad_mcp.models.tool_result import ToolResult

        result = ToolResult.failure("test_tool", "something went wrong")

        assert result.ok is False
        assert "something went wrong" in result.errors

    def test_dry_run_factory(self) -> None:
        from kicad_mcp.models.tool_result import ToolResult

        result = ToolResult.dry_run_result("test_tool", "would add symbol R1")

        assert result.ok is True
        assert result.dry_run is True
        assert result.changed is False
        assert "DRY-RUN" in result.state_delta.summary

    def test_to_mcp_text_is_valid_json(self) -> None:
        from kicad_mcp.models.tool_result import ToolResult

        text = ToolResult.success("test_tool").to_mcp_text()
        parsed = json.loads(text)

        assert parsed["ok"] is True
