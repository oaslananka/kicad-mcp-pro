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


def test_sonar_uses_exact_run_coverage_and_preserves_manual_fallback() -> None:
    manual = (ROOT / ".github" / "workflows" / "sonarcloud.yml").read_text(encoding="utf-8")
    ci_raw = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    ci = yaml.safe_load(ci_raw)
    manual_workflow = yaml.safe_load(manual)
    assert "workflow_dispatch:" in manual
    assert "  pull_request:" not in manual
    assert "    branches: [main]" not in manual
    assert manual_workflow["jobs"]["sonarcloud"]["timeout-minutes"] == 45
    assert manual_workflow["jobs"]["sonarcloud"]["name"] == "SonarCloud Manual Diagnostic"

    sonar = ci["jobs"]["sonarcloud"]
    coverage = ci["jobs"]["coverage"]
    assert sonar["name"] == "SonarCloud Scan"
    assert sonar["timeout-minutes"] == coverage["timeout-minutes"] == 45
    assert "coverage" in sonar["needs"]
    steps = {step["name"]: step for step in sonar["steps"] if "name" in step}
    assert steps["Download same-run coverage report"]["uses"].startswith(
        "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333"
    )
    assert steps["Verify exact-run and exact-SHA coverage report"]["env"] == {
        "SOURCE_SHA": "${{ github.sha }}",
        "SOURCE_RUN_ID": "${{ github.run_id }}",
        "SOURCE_ATTEMPT": "${{ github.run_attempt }}",
    }
    assert steps["Require successful upstream coverage gate"]["if"] == (
        "steps.sonar-mode.outputs.run_analysis == 'true'"
    )
    # The required scan runs precisely the same SHA-pinned upstream action as
    # the existing manual fallback, despite its YAML line-wrapped spelling.
    manual_scanner = next(
        step
        for step in manual_workflow["jobs"]["sonarcloud"]["steps"]
        if step.get("name") == "SonarCloud Scan"
    )
    assert steps["SonarCloud Scan"]["uses"] == manual_scanner["uses"]
    assert steps["SonarCloud Scan"]["uses"].startswith("SonarSource/sonarqube-scan-action@")
    assert len(steps["SonarCloud Scan"]["uses"].split("@")[-1]) == 40


def test_sonar_docs_only_path_gate_keeps_required_check_reporting() -> None:
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    changes = ci["jobs"]["changes"]
    assert "sonar-docs.outputs.docs_only" in changes["outputs"]["sonar_docs_only"]
    classify = next(s for s in changes["steps"] if s.get("id") == "sonar-docs")
    assert "git diff --no-renames --name-only -z" in classify["run"]
    assert "scripts/check_sonar_docs_only.py" in classify["run"]

    sonar = ci["jobs"]["sonarcloud"]
    assert "always()" in sonar["if"]
    steps = {step["name"]: step for step in sonar["steps"] if "name" in step}
    assert steps["Determine Sonar execution mode"]["env"]["DOCS_ONLY"] == (
        "${{ needs.changes.outputs.sonar_docs_only }}"
    )
    assert (
        "docs-only change set outside Sonar analysis scope"
        in steps["Determine Sonar execution mode"]["run"]
    )
    assert "Record intentional Sonar no-op" in steps
