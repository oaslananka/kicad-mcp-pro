"""End-to-end offline producer evidence composition; never gives publication authority."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from scripts.check_draft_producer_job import _JOB_NAMES
from scripts.check_signed_draft_producer_bundle import verify_producer_bundle
from tests.unit.test_extract_draft_producer_zip import (
    ARTIFACT_ID,
    ATTEMPT,
    RUN_ID,
    SHA,
    TAG,
    FixtureClient,
    _files,
    _zip,
)

REPO = "oaslananka/kicad-mcp-pro"
JOB_ID = 771188


class CompleteClient(FixtureClient):
    def __init__(self, role: str, zipped: bytes) -> None:
        super().__init__(role, zipped)
        workflow, name, attest, store = _JOB_NAMES[role]
        steps: list[dict[str, Any]] = [
            {"name": attest, "status": "completed", "conclusion": "success", "number": 5},
            {"name": store, "status": "completed", "conclusion": "success", "number": 6},
        ]
        if role == "python-dist":
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
                    "name": "Run actions/upload-artifact@different",
                    "status": "completed",
                    "conclusion": "success",
                    "number": 7,
                },
            )
        self.jobs: dict[str, Any] = {
            "total_count": 1,
            "jobs": [
                {
                    "id": JOB_ID,
                    "workflow_name": workflow,
                    "name": name,
                    "run_id": RUN_ID,
                    "run_attempt": ATTEMPT,
                    "head_sha": SHA,
                    "status": "completed",
                    "conclusion": "success",
                    "check_run_url": f"https://api.github.com/repos/{REPO}/check-runs/{JOB_ID}",
                    "steps": steps,
                }
            ],
        }

    def workflow_jobs(self, repo: str, run_id: int, attempt: int) -> dict[str, Any]:
        assert repo == REPO and run_id == RUN_ID and attempt == ATTEMPT
        return self.jobs


class Signature:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.tamper: str | None = None

    def verify(
        self, *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "path": path.name,
                "repo": repo,
                "sha": sha,
                "signer": signer,
                "source_ref": source_ref,
            }
        )
        uri = f"https://github.com/{REPO}/actions/runs/{RUN_ID}/attempts/{ATTEMPT}"
        certificate_uri = uri if self.tamper != "wrong_run" else uri + "-wrong"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.tamper == "wrong_digest":
            digest = "0" * 64
        if self.tamper == "no_signature":
            return []
        return [
            {
                "verificationResult": {
                    "statement": {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [{"name": path.name, "digest": {"sha256": digest}}],
                        "predicate": {"runDetails": {"metadata": {"invocationId": uri}}},
                    },
                    "signature": {"certificate": {"runInvocationURI": certificate_uri}},
                }
            }
        ]


def _case(tmp_path: Path, role: str) -> tuple[CompleteClient, Signature, dict[str, Any]]:
    zip_bytes = _zip(_files(role))
    local_zip = tmp_path / "producer.zip"
    local_zip.write_bytes(zip_bytes)
    return (
        CompleteClient(role, zip_bytes),
        Signature(),
        {
            "repo": REPO,
            "role": role,
            "tag": TAG,
            "source_commit": SHA,
            "run_id": RUN_ID,
            "run_attempt": ATTEMPT,
            "job_id": JOB_ID,
            "artifact_id": ARTIFACT_ID,
            "downloaded_zip": local_zip,
        },
    )


@pytest.mark.parametrize(
    ("role", "expected_packages"),
    [
        ("python-dist", 2),
        ("mcpb-release-evidence", 1),
        ("kicad-pcm-release-evidence", 1),
    ],
)
def test_all_packages_share_verified_run_artifact_and_job_evidence(
    tmp_path: Path, role: str, expected_packages: int
) -> None:
    client, verifier, args = _case(tmp_path, role)
    result = verify_producer_bundle(client, verifier, **args)
    assert result["producerJobMetadataVerified"] is True
    assert result["artifactArchiveDigestVerified"] is True
    assert result["zipMemberSafetyVerified"] is True
    assert result["signedRunInvocationVerified"] is True
    assert len(result["signedPackages"]) == expected_packages
    assert len(verifier.calls) == expected_packages
    assert {str(x["source_ref"]) for x in verifier.calls} == {"refs/heads/main"}
    assert result["artifactProducedByThisJobVerified"] is False
    assert result["registryReceiptVerified"] is False
    assert result["exclusiveWriterVerified"] is False
    assert result["publicationAuthorized"] is False
    assert list(tmp_path.iterdir()) == [args["downloaded_zip"]]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("bad_job", "producer job was not found"),
        ("bad_job_attempt", "producer job ID"),
        ("bad_source", "approved completed main producer"),
        ("bad_archive", "ZIP differs"),
        ("bad_zip_path", "unexpected, duplicate or missing ZIP"),
        ("bad_signature", "signed SLSA invocation"),
        ("bad_subject", "signatures do not cover"),
        ("no_signature", "no cryptographically verified"),
    ],
)
def test_any_single_inconsistent_identity_fails_closed(
    tmp_path: Path, change: str, expected: str
) -> None:
    client, verifier, args = _case(tmp_path, "mcpb-release-evidence")
    if change == "bad_job":
        args["job_id"] = JOB_ID + 1
    elif change == "bad_job_attempt":
        client.jobs["jobs"][0]["run_attempt"] = 2
    elif change == "bad_source":
        client.run["head_branch"] = "untrusted"
    elif change == "bad_archive":
        client.art["digest"] = "sha256:" + "0" * 64
    elif change == "bad_zip_path":
        damaged = _zip([("../../../escape", b"bad")])
        client.art["digest"] = "sha256:" + hashlib.sha256(damaged).hexdigest()
        client.art["size_in_bytes"] = len(damaged)
        args["downloaded_zip"].write_bytes(damaged)
    elif change == "bad_signature":
        verifier.tamper = "wrong_run"
    elif change == "bad_subject":
        verifier.tamper = "wrong_digest"
    elif change == "no_signature":
        verifier.tamper = "no_signature"
    with pytest.raises(ValueError, match=expected):
        verify_producer_bundle(client, verifier, **args)
    assert not (tmp_path / "verified").exists()


@pytest.mark.parametrize("role", ["python-release-evidence", "", "other"])
def test_evidence_only_or_unknown_roles_not_misrepresented_as_signed(
    tmp_path: Path, role: str
) -> None:
    client, verifier, args = _case(tmp_path, "mcpb-release-evidence")
    args["role"] = role
    with pytest.raises(ValueError, match="unapproved repository or signed-package role"):
        verify_producer_bundle(client, verifier, **args)
    assert verifier.calls == []


def test_wrong_repository_rejected_without_api_or_signature_calls(tmp_path: Path) -> None:
    client, verifier, args = _case(tmp_path, "mcpb-release-evidence")
    args["repo"] = "foreign/mirror"
    with pytest.raises(ValueError, match="unapproved repository"):
        verify_producer_bundle(client, verifier, **args)
    assert not verifier.calls
