"""Read-only, exact-run acceptance of a completed draft producer's signed package.

This combines *separate* job, archive, extraction and cryptographic signature
checks under one caller-supplied run identity. It does not verify an exclusive
publisher, the exact artifact-producing job, or authorize any Release writes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from scripts.assemble_mcp_server_draft_assets import _VERSION, _expected
from scripts.check_draft_producer_archive import REPOSITORY
from scripts.check_draft_producer_job import JobGitHubCLI, verify_producer_job
from scripts.check_signed_draft_asset import (
    AttestationVerifier,
    GitHubAttestationCLI,
    verify_signed_asset,
)
from scripts.extract_draft_producer_zip import verify_and_extract


class ProducerClient(Protocol):
    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]: ...

    def workflow_jobs(self, repo: str, run_id: int, attempt: int) -> dict[str, Any]: ...

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]: ...


_PACKAGE_ROLES = {
    "python-dist": ("python_dist", "python"),
    "mcpb-release-evidence": ("mcpb", "mcpb"),
    "kicad-pcm-release-evidence": ("pcm", "pcm"),
}


def verify_producer_bundle(
    client: ProducerClient,
    verifier: AttestationVerifier,
    *,
    repo: str,
    role: str,
    tag: str,
    source_commit: str,
    run_id: int,
    run_attempt: int,
    job_id: int,
    artifact_id: int,
    downloaded_zip: Path,
) -> dict[str, object]:
    """Verify every package in one approved producer ZIP without preserving files."""
    if repo != REPOSITORY or role not in _PACKAGE_ROLES:
        raise ValueError("unapproved repository or signed-package role")
    parsed = _VERSION.fullmatch(tag)
    if parsed is None:
        raise ValueError("invalid mcp-server release tag")

    group, kind = _PACKAGE_ROLES[role]
    expected_packages = sorted(
        n
        for n in _expected(parsed.group(1))[group]
        if n.endswith((".whl", ".tar.gz", ".mcpb", ".zip"))
    )
    if not expected_packages:
        raise ValueError("producer does not provide signable release packages")

    # The same caller-owned run identity is passed unchanged to each gate.
    job = verify_producer_job(
        client,
        repo=repo,
        role=role,
        run_id=run_id,
        run_attempt=run_attempt,
        job_id=job_id,
        source_commit=source_commit,
    )
    with tempfile.TemporaryDirectory(prefix="kicad-producer-bundle-1179-") as temporary:
        extracted = Path(temporary) / "verified"
        archive = verify_and_extract(
            client,
            repo=repo,
            role=role,
            tag=tag,
            run_id=run_id,
            run_attempt=run_attempt,
            artifact_id=artifact_id,
            head_sha=source_commit,
            downloaded_zip=downloaded_zip,
            output=extracted,
        )
        signatures: list[dict[str, object]] = []
        for package in expected_packages:
            signed = verify_signed_asset(
                verifier,
                package=extracted / package,
                tag=tag,
                source_commit=source_commit,
                kind=kind,
                source_ref="refs/heads/main",
                producer_run_id=run_id,
                producer_run_attempt=run_attempt,
            )
            if (
                signed.get("signedAttestationVerified") is not True
                or signed.get("producerRunInvocationVerified") is not True
                or signed.get("publicationAuthorized") is not False
            ):
                raise ValueError("signed package was not bound to exact producer invocation")
            signatures.append(
                {
                    "package": package,
                    "sha256": signed["sha256"],
                    "signerWorkflow": signed["signerWorkflow"],
                    "signedRunInvocationVerified": True,
                }
            )
    return {
        "repository": repo,
        "role": role,
        "tag": tag,
        "sourceCommit": source_commit,
        "runId": run_id,
        "runAttempt": run_attempt,
        "jobId": job_id,
        "artifactId": artifact_id,
        "archiveSha256": archive["archiveSha256"],
        "producerJobMetadataVerified": job["approvedJobCompleted"],
        "artifactArchiveDigestVerified": archive["artifactArchiveDigestVerified"],
        "zipMemberSafetyVerified": archive["zipMemberSafetyVerified"],
        "signedPackages": signatures,
        "signedRunInvocationVerified": True,
        "artifactProducedByThisJobVerified": False,
        "registryReceiptVerified": False,
        "exclusiveWriterVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--role", choices=sorted(_PACKAGE_ROLES), required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--downloaded-zip", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_producer_bundle(
            JobGitHubCLI(),
            GitHubAttestationCLI(),
            repo=args.repo,
            role=args.role,
            tag=args.tag,
            source_commit=args.source_commit,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            job_id=args.job_id,
            artifact_id=args.artifact_id,
            downloaded_zip=args.downloaded_zip,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"signed producer bundle: FAIL: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
