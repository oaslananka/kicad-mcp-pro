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


def test_sonar_docs_only_path_gate_keeps_required_check_reporting() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "sonarcloud.yml").read_text(encoding="utf-8")
    )
    classify = workflow["jobs"]["classify"]
    assert "release-classifier.outputs.docs_only" in classify["outputs"]["docs_only"]
    step = next(s for s in classify["steps"] if s.get("id") == "release-classifier")
    script = step["run"]
    assert "git diff --no-renames --name-only -z" in script
    assert "scripts/check_sonar_docs_only.py" in script
    mode = next(s for s in classify["steps"] if s.get("id") == "sonar-mode")
    assert mode["env"]["DOCS_ONLY"] == "${{ steps.release-classifier.outputs.docs_only }}"
    assert "docs-only change set outside Sonar analysis scope" in mode["run"]
    job = workflow["jobs"]["sonarcloud"]
    assert "always()" in job["if"]
    assert "needs.classify.result == 'success'" in job["if"]
    assert any(step.get("name") == "Record intentional Sonar no-op" for step in job["steps"])
    assert any(step.get("name") == "Run tests with coverage" for step in job["steps"])
