from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.validation import GateOutcome
from tests.conftest import get_prompt_text, read_resource_text


@pytest.mark.anyio
async def test_project_fix_queue_prioritizes_blocked_issues(
    sample_project: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: [
            GateOutcome(
                name="Placement",
                status="FAIL",
                summary="Placement still needs cleanup.",
                details=["FAIL: Connector 'J1' is too far from the board edge."],
            ),
            GateOutcome(
                name="Manufacturing",
                status="BLOCKED",
                summary="A DFM profile is not configured.",
                details=["Load a manufacturer profile before release."],
            ),
        ],
    )

    server = build_server("full")
    await read_resource_text(server, "kicad://project/info")

    queue = await read_resource_text(server, "kicad://project/fix_queue")

    assert "Project fix queue" in queue
    assert "1. [critical] Manufacturing: Load a manufacturer profile before release." in queue
    assert "Suggested tool: manufacturing_quality_gate()" in queue
    assert "2. [high] Placement: Connector 'J1' is too far from the board edge." in queue
    assert "Suggested tool: pcb_score_placement()" in queue


@pytest.mark.anyio
async def test_critic_fixer_prompts_expose_closed_loop_flow() -> None:
    server = build_server("full")

    review = await get_prompt_text(server, "design_review_loop", {})
    fix = await get_prompt_text(server, "fix_blocking_issues", {})
    release = await get_prompt_text(server, "manufacturing_release_checklist", {})

    assert "Inspect the current context" in review
    assert "Fix the highest-severity blocking issue first." in review
    assert "Repeat until the full project gate is `PASS`." in review
    assert "project fix queue as the source of truth" in fix.lower()
    assert "Re-run `project_quality_gate()` after the fix." in fix
    assert "manufacturing release as a gated handoff" in release.lower()
    assert "export_manufacturing_package()" in release


@pytest.mark.anyio
async def test_project_fix_queue_suggests_transfer_gate_for_transfer_failures(
    sample_project: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda **_kwargs: [
            GateOutcome(
                name="PCB transfer",
                status="FAIL",
                summary="Named nets did not transfer cleanly.",
                details=["FAIL: R2.2: PCB has 'BROKEN', expected 'GND'."],
            ),
        ],
    )

    server = build_server("full")
    await read_resource_text(server, "kicad://project/info")

    queue = await read_resource_text(server, "kicad://project/fix_queue")

    assert "PCB transfer" in queue
    assert "Suggested tool: pcb_transfer_quality_gate()" in queue
