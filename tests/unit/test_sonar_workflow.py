from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_sonar_cancels_superseded_runs_for_the_same_ref() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "sonarcloud.yml").read_text(encoding="utf-8")
    )

    assert workflow["concurrency"] == {
        "group": "sonarcloud-${{ github.ref }}",
        "cancel-in-progress": True,
    }


def test_sonar_full_suite_runtime_is_bounded_and_intentional() -> None:
    path = ROOT / ".github" / "workflows" / "sonarcloud.yml"
    raw = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    ci_workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["sonarcloud"]
    ci_coverage_job = ci_workflow["jobs"]["coverage"]

    assert job["timeout-minutes"] == ci_coverage_job["timeout-minutes"] == 45
    assert "independent full-suite coverage run" in raw
    assert "exact-SHA" in raw
