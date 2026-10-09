"""Test-only manufacturing approval fixture; never a real production authorization."""

from __future__ import annotations

import json
from pathlib import Path


def write_manufacturing_approval(project: Path) -> str:
    evidence_dir = project / ".kicad-mcp"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "manufacturing_approval.json"
    path.write_text(
        json.dumps(
            {
                "approved_by": "Test Reviewer",
                "approved_at_utc": "2026-07-04T00:00:00Z",
                "approval_scope": "manufacturing release package",
            }
        ),
        encoding="utf-8",
    )
    return ".kicad-mcp/manufacturing_approval.json"
