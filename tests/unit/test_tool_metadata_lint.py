from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.metadata import infer_tool_annotations
from kicad_mcp.tools.router import TOOL_CATEGORIES
from scripts.check_tool_contracts import lint as lint_tool_contracts

TESTS_ROOT = Path(__file__).resolve().parents[1]


def test_every_declared_tool_can_be_normalized_into_annotations() -> None:
    declared_tools = {
        tool_name for category in TOOL_CATEGORIES.values() for tool_name in category["tools"]
    }
    for tool_name in declared_tools:
        annotations = infer_tool_annotations(tool_name).model_dump(exclude_none=True)
        assert isinstance(annotations, dict), f"{tool_name} could not be normalized for discovery"


@pytest.mark.anyio
async def test_every_published_tool_description_has_at_least_ten_words() -> None:
    server = build_server("agent_full")
    short_descriptions = []
    for tool in await server.list_tools():
        words = [word for word in str(tool.description or "").replace("-", " ").split() if word]
        if len(words) < 10:
            short_descriptions.append((tool.name, len(words), tool.description))

    assert short_descriptions == []


@pytest.mark.anyio
async def test_every_declared_tool_has_static_test_reference() -> None:
    declared_tools = {
        tool_name for category in TOOL_CATEGORIES.values() for tool_name in category["tools"]
    }
    test_blob = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in TESTS_ROOT.rglob("*.py")
    )
    missing = sorted(tool_name for tool_name in declared_tools if tool_name not in test_blob)

    assert missing == []


def test_direct_tool_references_for_static_coverage_lint() -> None:
    declared_tools = {
        tool_name for category in TOOL_CATEGORIES.values() for tool_name in category["tools"]
    }
    direct_references = {
        "drc_export_rules",
        "export_odb",
        "pcb_add_copper_zone",
        "pcb_bga_fanout",
        "project_infer_design_spec",
    }

    assert direct_references <= declared_tools


def test_read_only_prefix_takes_precedence_over_write_infix() -> None:
    """Read-only prefix classification must win over broad write-infix tokens.

    Regression test: mfg_check_import_support contains "_import_" but starts
    with the read-only prefix "mfg_check_". It must NOT be marked destructive.
    """
    # -- Read-only tool with misleading infix (the regression case) --
    ro_ann = infer_tool_annotations("mfg_check_import_support").model_dump(exclude_none=True)
    assert ro_ann.get("readOnlyHint") is True, (
        "mfg_check_import_support: mfg_check_ prefix must override _import_ infix"
    )
    assert ro_ann.get("destructiveHint") is None, (
        "mfg_check_import_support must NOT be destructiveHint=True"
    )

    # -- Actual import/export tools must remain destructive --
    for destructive_tool in (
        "mfg_import_allegro",
        "mfg_import_geda",
        "mfg_import_pads",
        "route_import_ses",
        "route_export_dsn",
        "pcb_export_3d_pdf",
    ):
        ann = infer_tool_annotations(destructive_tool).model_dump(exclude_none=True)
        assert ann.get("destructiveHint") is True, (
            f"{destructive_tool} must be destructiveHint=True"
        )
        assert ann.get("readOnlyHint") is None, f"{destructive_tool} must NOT be readOnlyHint=True"

    # -- Other read-only prefixes that contain write-like substrings --
    for readonly_tool in (
        "drc_list_rules",
        "kicad_help",
        "kicad_get_version",
        "lib_check_footprint",
        "mfg_check_import_support",
    ):
        ann = infer_tool_annotations(readonly_tool).model_dump(exclude_none=True)
        assert ann.get("readOnlyHint") is True, f"{readonly_tool} must be readOnlyHint=True"
        assert ann.get("destructiveHint") is None, (
            f"{readonly_tool} must NOT be destructiveHint=True"
        )


def test_sheet_wiring_mutations_are_destructive_and_idempotent() -> None:
    for tool_name in ("sch_spread_sheets", "sch_wire_sheet_pins"):
        annotations = infer_tool_annotations(tool_name).model_dump(exclude_none=True)
        assert annotations.get("destructiveHint") is True
        assert annotations.get("idempotentHint") is True


@pytest.mark.anyio
async def test_tool_contract_linter_passes() -> None:
    assert await lint_tool_contracts() == []
