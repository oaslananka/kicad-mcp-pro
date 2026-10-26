"""Read-only acceptance of the exact successful Actions producer job for #1179.

A job's success and steps are not a cryptographic proof that a particular
artifact was uploaded by that job. That requires independent signed provenance.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Any, Protocol

from scripts.check_draft_producer_archive import (
    _ARTIFACT_WORKFLOWS,
    REPOSITORY,
    GitHubArtifactClient,
    _verify_run,
)

_SHA = re.compile(r"^[0-9a-f]{40}$")
_JOB_NAMES: dict[str, tuple[str, str, str, str]] = {
    # workflow display name, expected job name, attestation step, upload step
    "python-dist": (
        "Publish Python",
        "build",
        "Attest Python distributions",
        "Run actions/upload-artifact@",
    ),
    "python-release-evidence": (
        "Publish Python",
        "build",
        "Attest Python distributions",
        "Run actions/upload-artifact@",
    ),
    "mcpb-release-evidence": (
        "Publish MCPB",
        "publish",
        "Attest MCPB bundle",
        "Store MCPB release evidence",
    ),
    "kicad-pcm-release-evidence": (
        "Publish KiCad PCM",
        "publish",
        "Attest KiCad PCM package",
        "Store KiCad PCM release evidence",
    ),
}


class JobClient(Protocol):
    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]: ...

    def workflow_jobs(self, repo: str, run_id: int, attempt: int) -> dict[str, Any]: ...


class JobGitHubCLI(GitHubArtifactClient):
    def workflow_jobs(self, repo: str, run_id: int, attempt: int) -> dict[str, Any]:
        return self._get(f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")


def _matching_approved_job(
    collection: object,
    *,
    role: str,
    repo: str,
    run_id: int,
    run_attempt: int,
    job_id: int,
    source_commit: str,
) -> list[object]:
    """Match exactly one completed job from an untruncated GitHub job listing."""
    if not isinstance(collection, dict):
        raise ValueError("invalid GitHub job collection")
    jobs = collection.get("jobs")
    count = collection.get("total_count")
    if not isinstance(jobs, list) or type(count) is not int or count != len(jobs):
        raise ValueError("incomplete GitHub workflow job listing")
    matches = [
        j for j in jobs if isinstance(j, dict) and type(j.get("id")) is int and j["id"] == job_id
    ]
    if len(matches) != 1:
        raise ValueError("requested producer job was not found uniquely")
    job = matches[0]
    workflow_name, name, _, _ = _JOB_NAMES[role]
    required = {
        "workflow_name": workflow_name,
        "name": name,
        "head_sha": source_commit,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "status": "completed",
        "conclusion": "success",
        "check_run_url": f"https://api.github.com/repos/{repo}/check-runs/{job_id}",
    }
    if any(job.get(field) != value for field, value in required.items()):
        raise ValueError("producer job ID, branch, attempt, workflow or completion mismatch")
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise ValueError("missing producer job steps")
    return steps


def _successful_step_numbers(steps: list[object], label: str, *, prefix: bool = False) -> list[int]:
    result: list[int] = []
    for item in steps:
        if not isinstance(item, dict):
            raise ValueError("invalid producer job step")
        step_name = item.get("name")
        if not isinstance(step_name, str):
            raise ValueError("invalid producer job step name")
        matched = step_name.startswith(label) if prefix else step_name == label
        if matched:
            if item.get("status") != "completed" or item.get("conclusion") != "success":
                raise ValueError(f"required producer step failed or was skipped: {label}")
            num = item.get("number")
            if type(num) is not int or num <= 0:
                raise ValueError("producer step lacks a valid number")
            result.append(num)
    return result


def _check_required_job_steps(steps: list[object], role: str) -> None:
    _, _, attest_step, store_step = _JOB_NAMES[role]
    attest = _successful_step_numbers(steps, attest_step)
    uploaded = _successful_step_numbers(steps, store_step, prefix=role.startswith("python-"))
    if len(attest) != 1 or (
        len(uploaded) < 2 if role.startswith("python-") else len(uploaded) != 1
    ):
        raise ValueError("producer job lacks approved attest/upload step evidence")
    if role.startswith("python-"):
        provenance = _successful_step_numbers(steps, "Attest Python SLSA build provenance")
        if len(provenance) != 1 or provenance[0] >= attest[0]:
            raise ValueError("Python SLSA provenance must precede SBOM attestation")
    if min(uploaded) <= attest[0]:
        raise ValueError("producer artifact upload preceded its attestation")


def verify_producer_job(
    client: JobClient,
    *,
    repo: str,
    role: str,
    run_id: int,
    run_attempt: int,
    job_id: int,
    source_commit: str,
) -> dict[str, object]:
    if (
        repo != REPOSITORY
        or role not in _ARTIFACT_WORKFLOWS
        or any(type(value) is not int or value <= 0 for value in (run_id, run_attempt, job_id))
        or _SHA.fullmatch(source_commit) is None
    ):
        raise ValueError("invalid approved producer job identity")
    run = client.workflow_run(repo, run_id)
    _verify_run(
        run, repo=repo, run_id=run_id, attempt=run_attempt, head_sha=source_commit, role=role
    )

    collection = client.workflow_jobs(repo, run_id, run_attempt)
    steps = _matching_approved_job(
        collection,
        role=role,
        repo=repo,
        run_id=run_id,
        run_attempt=run_attempt,
        job_id=job_id,
        source_commit=source_commit,
    )
    _check_required_job_steps(steps, role)

    return {
        "repo": repo,
        "role": role,
        "runId": run_id,
        "runAttempt": run_attempt,
        "jobId": job_id,
        "sourceCommit": source_commit,
        "approvedJobCompleted": True,
        "requiredAttestationStepCompleted": True,
        "requiredUploadStepCompleted": True,
        "artifactProducedByThisJobVerified": False,
        "signedAttestationVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--run-id", required=True, type=int)
    p.add_argument("--run-attempt", required=True, type=int)
    p.add_argument("--job-id", required=True, type=int)
    p.add_argument("--source-commit", required=True)
    args = p.parse_args()
    try:
        result = verify_producer_job(
            JobGitHubCLI(),
            repo=args.repo,
            role=args.role,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            job_id=args.job_id,
            source_commit=args.source_commit,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        p.exit(2, f"draft producer job preflight: FAIL: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
