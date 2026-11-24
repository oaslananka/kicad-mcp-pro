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
    assert "attempts/$GITHUB_RUN_ATTEMPT/jobs?per_page=100" in run
    assert "check_windows_coverage_producer.py" in run
    assert wait["env"]["COVERAGE_PRODUCER_HEAD"] == (
        "${{ github.event.pull_request.head.sha || github.sha }}"
    )
    assert "sleep 15" in run
    assert any(
        step.get("run") == "uv run --all-extras bash scripts/ci/test_windows_coverage_wait.sh"
        for step in workflow["jobs"]["workflow-policy"]["steps"]
    )
    assert "exit 1" in run
    assert "GITHUB_TOKEN" not in run
    assert "GH_TOKEN" in wait["env"]
    assert wait["id"] == "native-windows-coverage"
    assert "artifact_id=$matches" in run
    download = steps[names.index(download_name)]
    assert download["run"] == "bash scripts/ci/download_windows_coverage.sh"
    assert download["env"]["COVERAGE_ARTIFACT_ID"] == (
        "${{ steps.native-windows-coverage.outputs.artifact_id }}"
    )
    assert download["env"]["COVERAGE_PRODUCER_HEAD"] == wait["env"]["COVERAGE_PRODUCER_HEAD"]
    assert download["env"]["GH_TOKEN"] == wait["env"]["GH_TOKEN"]
    assert "continue-on-error" not in download
    assert download["if"] == wait["if"]
    assert any(
        step.get("run") == "uv run --all-extras bash scripts/ci/test_windows_coverage_download.sh"
        for step in workflow["jobs"]["workflow-policy"]["steps"]
    )
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


def test_sonar_failed_job_rerun_uses_coverage_producer_identity() -> None:
    """Rerunning Sonar alone must reuse the successful producer's sealed artifact."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    coverage = workflow["jobs"]["coverage"]
    sonar_steps = {step.get("name"): step for step in workflow["jobs"]["sonarcloud"]["steps"]}
    producer_attempt = "$" + "{{ github.run_attempt }}"
    assert coverage["outputs"]["sonar_coverage_attempt"] == producer_attempt

    download = sonar_steps["Download same-run coverage report"]
    assert "name" not in download["with"]
    assert download["with"]["artifact-ids"] == (
        "$" + "{{ needs.coverage.outputs.sonar_coverage_artifact_id }}"
    )
    verify = sonar_steps["Verify exact-run and exact-SHA coverage report"]
    assert verify["env"]["SOURCE_ATTEMPT"] == (
        "$" + "{{ needs.coverage.outputs.sonar_coverage_attempt }}"
    )
    assert verify["env"]["SOURCE_RUN_ID"] == "$" + "{{ github.run_id }}"
    assert verify["env"]["SOURCE_SHA"] == "$" + "{{ github.sha }}"
