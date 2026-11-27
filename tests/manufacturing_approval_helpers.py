"""Test-only manufacturing approval fixture; never a real production authorization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def write_manufacturing_approval(project: Path) -> str:
    evidence_dir = project / ".kicad-mcp"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "manufacturing_approval.json"
    files = sorted(
        (
            p
            for p in project.rglob("*")
            if p.is_file()
            and (
                p.suffix in {".kicad_pro", ".kicad_pcb", ".kicad_sch", ".kicad_dru"}
                or p.relative_to(project).as_posix()
                in {".kicad-mcp/project_spec.json", ".kicad-mcp/variants.json"}
            )
        ),
        key=lambda p: p.relative_to(project).as_posix(),
    )
    path.write_text(
        json.dumps(
            {
                "approved_by": "Test Reviewer",
                "approved_at_utc": "2026-07-04T00:00:00Z",
                "approval_scope": "manufacturing release package",
                "approved_project_files": [
                    {
                        "path": p.relative_to(project).as_posix(),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    }
                    for p in files
                ],
            }
        ),
        encoding="utf-8",
    )
    return ".kicad-mcp/manufacturing_approval.json"
