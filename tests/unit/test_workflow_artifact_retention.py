from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_upload_artifact_steps_declare_explicit_retention() -> None:
    violations: list[str] = []

    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (workflow.get("jobs") or {}).items():
            for index, step in enumerate(job.get("steps") or []):
                uses = step.get("uses") or ""
                if not uses.startswith("actions/upload-artifact@"):
                    continue
                retention = (step.get("with") or {}).get("retention-days")
                if retention is None:
                    violations.append(f"{path.name}:{job_name}:step-{index + 1}")

    assert violations == [], "upload-artifact steps missing retention-days: " + ", ".join(
        violations
    )
