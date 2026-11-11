"""Protect early Linux coverage execution and strict Sonar provenance."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_coverage_starts_with_platform_matrix_but_sonar_stays_after_coverage() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    jobs = workflow["jobs"]
    assert set(jobs["coverage"]["needs"]) == {"changes", "release-metadata"}
    assert "mcp-server" in jobs["required-pr-gate"]["needs"]
    assert "coverage" in jobs["required-pr-gate"]["needs"]
    assert "coverage" in jobs["sonarcloud"]["needs"]
    assert any(step.get("name") == "SonarCloud Scan" for step in jobs["sonarcloud"]["steps"])


def test_coverage_waits_for_exact_run_windows_artifact_before_merge() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    coverage = workflow["jobs"]["coverage"]
    assert coverage["permissions"]["actions"] == "read"
    steps = coverage["steps"]
    names = [s.get("name") for s in steps]
    wait_name = "Wait for exact-run Windows coverage evidence"
    download_name = "Download native Windows coverage for this run"
    merge_name = "Merge native Windows and Linux coverage"
    assert names.index("Run full Python suite with coverage and JUnit") < names.index(wait_name)
    assert names.index(wait_name) < names.index(download_name) < names.index(merge_name)

    wait = steps[names.index(wait_name)]
    run = wait["run"]
    assert "steps.python-tests.outcome == 'success'" in wait["if"]
    assert "github.event_name == 'pull_request'" in wait["if"]
    assert "needs.changes.outputs.python == 'true'" in wait["if"]
    assert "github.event_name == 'push'" in wait["if"]
    assert "github.event_name == 'workflow_dispatch'" in wait["if"]
    assert "needs.changes.outputs.release_metadata_only != 'true'" in wait["if"]
    assert "needs.changes.outputs.sonar_docs_only != 'true'" in wait["if"]
    run_id = "$" + "{{ github.run_id }}"
    run_attempt = "$" + "{{ github.run_attempt }}"
    expected = f"windows-python-coverage-{run_id}-{run_attempt}"
    assert wait["env"]["COVERAGE_ARTIFACT"] == expected
    assert "gh api" in run
    assert "GITHUB_RUN_ID" in run
    assert "attempt" in run
    assert "sleep 15" in run
    assert "exit 1" in run
    assert "GITHUB_TOKEN" not in run
    assert "GH_TOKEN" in wait["env"]
    assert steps[names.index(merge_name)]["run"].count("merge_platform_coverage.py merge") == 1

    sonar = workflow["jobs"]["sonarcloud"]
    sonar_steps = {s.get("name"): s for s in sonar["steps"]}
    assert (
        "needs.coverage.outputs.sonar_coverage_artifact_id != ''"
        in sonar_steps["Download same-run coverage report"]["if"]
    )
    assert (
        "ci_coverage_artifact.py verify"
        in sonar_steps["Verify exact-run and exact-SHA coverage report"]["run"]
    )
    assert "-Dsonar.qualitygate.wait=true" in sonar_steps["SonarCloud Scan"]["with"]["args"]
