from __future__ import annotations

import re
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


def _commit_hash(text: str) -> str:
    match = re.search(r"- Commit: ([0-9a-f]{40})", text)
    if match is None:
        raise AssertionError(f"Unable to extract commit hash from: {text}")
    return match.group(1)


@pytest.mark.anyio
async def test_vcs_checkpoint_diff_and_restore_roundtrip(sample_project: Path) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    init_text = await call_tool_text(
        server,
        "vcs_init_git",
        {"project_dir": str(sample_project)},
    )
    initial_schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    checkpoint_text = await call_tool_text(
        server,
        "vcs_commit_checkpoint",
        {"message": "Initial checkpoint", "auto_drc": False},
    )
    checkpoint_hash = _commit_hash(checkpoint_text)

    (sample_project / "demo.kicad_sch").write_text(
        initial_schematic + "\n; modified by test\n",
        encoding="utf-8",
    )

    diff_text = await call_tool_text(
        server,
        "vcs_diff_with_checkpoint",
        {"commit_hash": checkpoint_hash},
    )
    checkpoints_text = await call_tool_text(server, "vcs_list_checkpoints", {})
    restore_text = await call_tool_text(
        server,
        "vcs_restore_checkpoint",
        {"commit_hash": checkpoint_hash},
    )
    restored_schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    assert "Git repository ready." in init_text
    assert (sample_project / ".git").exists()
    assert "Checkpoint committed." in checkpoint_text
    assert "Diff versus checkpoint" in diff_text
    assert "demo.kicad_sch" in diff_text
    assert "Checkpoints (1 total):" in checkpoints_text
    assert "Initial checkpoint" in checkpoints_text
    assert "Checkpoint restored." in restore_text
    assert "backed up" in restore_text
    assert restored_schematic == initial_schematic
