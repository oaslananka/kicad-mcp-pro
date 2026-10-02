from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release-please.yml"
SYNC_SCRIPT = ROOT / "scripts" / "sync_release_artifacts.py"


def test_release_please_uses_canonical_release_artifact_sync() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/sync_release_artifacts.py --write" in workflow
    assert "scripts/sync_mcp_metadata.py --write" not in workflow


def test_release_artifact_sync_covers_all_version_derived_outputs() -> None:
    assert SYNC_SCRIPT.is_file()
    script = SYNC_SCRIPT.read_text(encoding="utf-8")

    assert "sync_mcp_metadata" in script
    assert "build_tool_effect_manifest" in script
