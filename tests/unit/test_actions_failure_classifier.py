from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_artifact_quota_failure_is_not_classified_as_pytest() -> None:
    root = Path(__file__).resolve().parents[2]
    log_text = """
    Upload release distribution bundle
    ##[error]Failed to CreateArtifact: Artifact storage quota has been hit.
    Unable to upload any new artifacts. Usage is recalculated every 6-12 hours.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for scripts/classify-gh-failure.mjs tests")

    result = subprocess.run(
        [
            node,
            "scripts/classify-gh-failure.mjs",
            "--text",
            log_text,
            "--json",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )

    payload = json.loads(result.stdout)
    assert payload["classification"] == "artifact-quota-exhausted"
    assert payload["classification"] != "test-failure"
    assert payload["auto_fix_allowed"] is False
    assert payload["publish_must_stop"] is True
    assert payload["human_approval_required"] is True


def test_non_quota_create_artifact_failure_is_not_artifact_quota() -> None:
    root = Path(__file__).resolve().parents[2]
    log_text = "Failed to CreateArtifact: artifact name is not valid"
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for scripts/classify-gh-failure.mjs tests")

    result = subprocess.run(
        [
            node,
            "scripts/classify-gh-failure.mjs",
            "--text",
            log_text,
            "--json",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )

    payload = json.loads(result.stdout)
    assert payload["classification"] != "artifact-quota-exhausted"


def test_classifier_resolves_github_cli_from_fixed_system_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for scripts/classify-gh-failure.mjs tests")

    subprocess.run(
        [node, "--test", "tests/js/classify-gh-failure-security.test.mjs"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
