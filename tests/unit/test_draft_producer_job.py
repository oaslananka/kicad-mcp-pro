"""Offline, read-only job metadata checks, never attestation/provenance claims."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from scripts.check_draft_producer_job import (
    _JOB_NAMES,
    REPOSITORY,
    verify_producer_job,
)

SHA = "a" * 40
ID = 991122
ATTEMPT = 2
JOB_ID = 778899
REPO_ID = 12345


class Fake:
    def __init__(self, role: str) -> None:
        self.role = role
        self.calls = 0
        workflow_path = {
            "python-dist": "publish-python.yml",
            "python-release-evidence": "publish-python.yml",
            "mcpb-release-evidence": "publish-mcpb.yml",
            "kicad-pcm-release-evidence": "publish-kicad-pcm.yml",
        }[role]
        workflow_name, job_name, attest, upload = _JOB_NAMES[role]
        self.run: dict[str, Any] = {
            "id": ID,
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{ID}",
            "repository": {"id": REPO_ID, "full_name": REPOSITORY},
            "head_repository": {"id": REPO_ID, "full_name": REPOSITORY},
            "path": f".github/workflows/{workflow_path}",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": SHA,
            "run_attempt": ATTEMPT,
            "status": "completed",
            "conclusion": "success",
        }
        steps = [
            {"name": attest, "status": "completed", "conclusion": "success", "number": 5},
            {"name": upload, "status": "completed", "conclusion": "success", "number": 6},
        ]
        if role.startswith("python-"):
            steps.insert(
                0,
                {
                    "name": "Attest Python SLSA build provenance",
                    "status": "completed",
                    "conclusion": "success",
                    "number": 4,
                },
            )
            steps.append(
                {
                    "name": upload + "another",
                    "status": "completed",
                    "conclusion": "success",
                    "number": 7,
                }
            )
        self.jobs: dict[str, Any] = {
            "total_count": 1,
            "jobs": [
                {
                    "id": JOB_ID,
                    "workflow_name": workflow_name,
                    "name": job_name,
                    "run_id": ID,
                    "run_attempt": ATTEMPT,
                    "head_sha": SHA,
                    "status": "completed",
                    "conclusion": "success",
                    "check_run_url": f"https://api.github.com/repos/{REPOSITORY}/check-runs/{JOB_ID}",
                    "steps": steps,
                }
            ],
        }

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        assert repo == REPOSITORY
        assert run_id == ID
        self.calls += 1
        return deepcopy(self.run)

    def workflow_jobs(self, repo: str, run_id: int, attempt: int) -> dict[str, Any]:
        assert repo == REPOSITORY
        assert run_id == ID and attempt == ATTEMPT
        self.calls += 1
        return deepcopy(self.jobs)


def _params(role: str) -> dict[str, Any]:
    return {
        "repo": REPOSITORY,
        "role": role,
        "run_id": ID,
        "run_attempt": ATTEMPT,
        "job_id": JOB_ID,
        "source_commit": SHA,
    }


@pytest.mark.parametrize("role", list(_JOB_NAMES))
def test_exact_completed_job_and_required_steps_success(role: str) -> None:
    fake = Fake(role)
    result = verify_producer_job(fake, **_params(role))
    assert result["approvedJobCompleted"] is True
    assert result["requiredAttestationStepCompleted"] is True
    assert result["requiredUploadStepCompleted"] is True
    assert result["artifactProducedByThisJobVerified"] is False
    assert result["signedAttestationVerified"] is False
    assert result["publicationAuthorized"] is False
    assert fake.calls == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "CI"),
        ("workflow_name", "Unknown workflow"),
        ("run_attempt", 1),
        ("run_id", ID + 1),
        ("id", JOB_ID + 1),
        ("status", "queued"),
        ("conclusion", "skipped"),
        ("head_sha", "b" * 40),
        ("check_run_url", "https://attacker.example/checks"),
    ],
)
def test_forged_or_wrong_job_rejected(field: str, value: str | int) -> None:
    fake = Fake("mcpb-release-evidence")
    fake.jobs["jobs"][0][field] = value
    kwargs = _params(fake.role)
    with pytest.raises(ValueError):
        verify_producer_job(fake, **kwargs)


@pytest.mark.parametrize("conclusion", ["skipped", "failure", None])
def test_skipped_or_failed_attestation_rejected(conclusion: str | None) -> None:
    fake = Fake("mcpb-release-evidence")
    fake.jobs["jobs"][0]["steps"][0]["conclusion"] = conclusion
    kwargs = _params(fake.role)
    with pytest.raises(ValueError, match="required producer step"):
        verify_producer_job(fake, **kwargs)


def test_upload_before_attestation_is_rejected() -> None:
    fake = Fake("mcpb-release-evidence")
    fake.jobs["jobs"][0]["steps"][0]["number"] = 7
    kwargs = _params(fake.role)
    with pytest.raises(ValueError, match="preceded"):
        verify_producer_job(fake, **kwargs)


@pytest.mark.parametrize("bad", ["skipped", "missing", "too_late"])
def test_python_requires_independent_slsa_attestation(bad: str) -> None:
    fake = Fake("python-release-evidence")
    steps = fake.jobs["jobs"][0]["steps"]
    if bad == "skipped":
        steps[0]["conclusion"] = "skipped"
    elif bad == "missing":
        steps.pop(0)
    else:
        steps[0]["number"] = 9
    kwargs = _params(fake.role)
    with pytest.raises(ValueError, match="SLSA|required producer step"):
        verify_producer_job(fake, **kwargs)


def test_missing_second_python_artifact_upload_is_rejected() -> None:
    fake = Fake("python-release-evidence")
    fake.jobs["jobs"][0]["steps"].pop()
    kwargs = _params(fake.role)
    with pytest.raises(ValueError, match="lacks approved"):
        verify_producer_job(fake, **kwargs)


def test_partial_pagination_is_rejected() -> None:
    fake = Fake("mcpb-release-evidence")
    fake.jobs["total_count"] = 200
    kwargs = _params(fake.role)
    with pytest.raises(ValueError, match="incomplete"):
        verify_producer_job(fake, **kwargs)


def test_duplicate_job_id_is_rejected() -> None:
    fake = Fake("mcpb-release-evidence")
    fake.jobs["jobs"].append(deepcopy(fake.jobs["jobs"][0]))
    fake.jobs["total_count"] = 2
    kwargs = _params(fake.role)
    with pytest.raises(ValueError, match="not found uniquely"):
        verify_producer_job(fake, **kwargs)


def test_run_source_branch_mismatch_rejected() -> None:
    fake = Fake("mcpb-release-evidence")
    fake.run["head_branch"] = "untrusted"
    kwargs = _params(fake.role)
    with pytest.raises(ValueError, match="approved completed main producer"):
        verify_producer_job(fake, **kwargs)


def test_unapproved_or_invalid_identity_shortcircuits() -> None:
    fake = Fake("mcpb-release-evidence")
    invalid_params = {**_params(fake.role), "job_id": True}
    with pytest.raises(ValueError, match="invalid approved"):
        verify_producer_job(fake, **invalid_params)
    assert fake.calls == 0
