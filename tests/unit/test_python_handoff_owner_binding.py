"""Exercise composed read-only owner and producer evidence using offline API fixtures."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts.check_python_handoff_owner_binding import verify_owner_binding
from scripts.check_signed_python_handoff import HandoffIdentity, manifest_bytes
from tests.unit.test_draft_release_owner import RELEASE, RUN, FakeOwnerClient
from tests.unit.test_extract_draft_producer_zip import (
    ARTIFACT_ID,
    ATTEMPT,
    RUN_ID,
    SHA,
    TAG,
    _files,
)
from tests.unit.test_signed_draft_producer_bundle import CompleteClient
from tests.unit.test_signed_draft_producer_bundle import Signature as ProducerSignature
from tests.unit.test_signed_draft_reusable_producer_bundle import _fixture

REPO = "oaslananka/kicad-mcp-pro"
IDENTITY = HandoffIdentity(TAG, SHA, RELEASE, RUN, 2, RUN_ID, ATTEMPT, ARTIFACT_ID)


class CombinedClient(FakeOwnerClient):
    def __init__(self, producer: CompleteClient) -> None:
        super().__init__()
        self.release_data["tag_name"] = TAG
        self.producer = producer
        producer.run["repository"]["id"] = 1255527274
        producer.run["head_repository"]["id"] = 1255527274
        producer.art["workflow_run"]["repository_id"] = 1255527274
        producer.art["workflow_run"]["head_repository_id"] = 1255527274
        self.owner_reads = 0
        self.change: str | None = None

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        if run_id == RUN:
            self.owner_reads += 1
            if self.change == "owner" and self.owner_reads > 1:
                self.run_data["status"] = "completed"
            return super().workflow_run(repo, run_id)
        return copy.deepcopy(self.producer.workflow_run(repo, run_id))

    def tag_commit(self, repo: str, tag: str) -> str:
        assert repo == REPO
        assert tag == TAG
        if self.change == "tag" and self.owner_reads > 1:
            return "b" * 40
        return SHA

    def workflow_jobs(self, repo: str, run_id: int, attempt: int) -> dict[str, Any]:
        return copy.deepcopy(self.producer.workflow_jobs(repo, run_id, attempt))

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]:
        return copy.deepcopy(self.producer.artifact(repo, artifact_id))


class Signature:
    def __init__(self, producer: ProducerSignature) -> None:
        self.producer = producer
        self.owner_calls = 0
        self.change: str | None = None

    def verify(
        self, *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        if signer != ".github/workflows/publish-release.yml":
            return self.producer.verify(
                path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref
            )
        self.owner_calls += 1
        assert repo == REPO
        assert sha == SHA
        assert source_ref == "refs/heads/main"
        uri = f"https://github.com/{REPO}/actions/runs/{RUN}/attempts/2"
        if self.change == "owner-signature":
            uri += "-wrong"
        return [
            {
                "verificationResult": {
                    "statement": {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [
                            {
                                "name": path.name,
                                "digest": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                            }
                        ],
                        "predicate": {"runDetails": {"metadata": {"invocationId": uri}}},
                    },
                    "signature": {"certificate": {"runInvocationURI": uri}},
                }
            }
        ]


@pytest.fixture
def case(tmp_path: Path) -> tuple[CombinedClient, Signature, dict[str, Any]]:
    producer, signature, producer_args = _fixture(tmp_path, "python-dist")
    client = CombinedClient(producer)
    dist = tmp_path / "dist"
    dist.mkdir()
    for name, data in _files("python-dist"):
        (dist / name).write_bytes(data)
    manifest = tmp_path / "python-worker-manifest.json"
    manifest.write_bytes(manifest_bytes(IDENTITY, dist))
    return (
        client,
        Signature(signature),
        {
            "identity": IDENTITY,
            "producer_job_id": producer_args["job_id"],
            "downloaded_zip": producer_args["downloaded_zip"],
            "directory": dist,
            "manifest": manifest,
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
    )


def test_composed_binding_verifies_same_bytes_without_publication_authority(case) -> None:
    client, verifier, args = case
    result = verify_owner_binding(client, verifier, **args)
    for field in (
        "activeOwnerVerified",
        "protectedTagVerified",
        "producerArtifactVerified",
        "producerJobMetadataVerified",
        "producerPackageSignaturesVerified",
        "manifestProducerBytesMatch",
        "signedOwnerManifestVerified",
    ):
        assert result[field] is True
    for field in (
        "artifactProducedByThisJobVerified",
        "workerRunVerified",
        "registryReceiptVerified",
        "exclusiveWriterVerified",
        "publicationAuthorized",
    ):
        assert result[field] is False
    assert client.owner_reads == 2
    assert verifier.owner_calls == 1
    assert len(verifier.producer.calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        "owner",
        "tag",
        "owner-signature",
        "producer-signature",
        "archive",
        "pin",
        "job",
        "repository",
        "distinct-run",
    ],
)
def test_conflicting_evidence_fails_closed(case, change: str) -> None:
    client, verifier, args = case
    if change in ("owner", "tag"):
        client.change = change
    elif change == "owner-signature":
        verifier.change = change
    elif change == "producer-signature":
        verifier.producer.tamper = "wrong_run"
    elif change == "archive":
        args["downloaded_zip"].write_bytes(b"wrong")
    elif change == "pin":
        args["manifest_sha256"] = "0" * 64
    elif change == "job":
        args["producer_job_id"] = 1
    elif change == "repository":
        client.producer.run["repository"]["id"] = 1
        client.producer.run["head_repository"]["id"] = 1
        client.producer.art["workflow_run"]["repository_id"] = 1
        client.producer.art["workflow_run"]["head_repository_id"] = 1
    else:
        args["identity"] = replace(IDENTITY, producer_run_id=RUN)
    with pytest.raises(ValueError):
        verify_owner_binding(client, verifier, **args)


def test_separately_valid_owner_manifest_cannot_substitute_producer_packages(case) -> None:
    client, verifier, args = case
    next(args["directory"].glob("*.whl")).write_bytes(b"other owner-approved package")
    manifest = args["manifest"]
    manifest.write_bytes(manifest_bytes(IDENTITY, args["directory"]))
    args["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="producer package digests"):
        verify_owner_binding(client, verifier, **args)


def test_packages_changed_after_producer_verification_fail_closed(case, monkeypatch) -> None:
    client, verifier, args = case
    original = client.workflow_run

    def read_run(repo: str, run_id: int) -> dict[str, Any]:
        result = original(repo, run_id)
        if run_id == RUN and client.owner_reads == 2:
            next(args["directory"].glob("*.whl")).write_bytes(b"changed")
        return result

    monkeypatch.setattr(client, "workflow_run", read_run)
    with pytest.raises(ValueError, match="changed"):
        verify_owner_binding(client, verifier, **args)


def test_producer_rerun_during_owner_verification_is_rejected(case, monkeypatch) -> None:
    client, verifier, args = case
    original = verifier.producer.verify

    def sign(
        *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        client.producer.run["run_attempt"] = ATTEMPT + 1
        return result

    monkeypatch.setattr(verifier.producer, "verify", sign)
    with pytest.raises(ValueError, match="approved completed main producer"):
        verify_owner_binding(client, verifier, **args)


def test_draft_published_during_package_verification_is_rejected(case, monkeypatch) -> None:
    client, verifier, args = case
    original = verifier.producer.verify

    def sign(
        *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        client.release_data["draft"] = False
        return result

    monkeypatch.setattr(verifier.producer, "verify", sign)
    with pytest.raises(ValueError, match="published"):
        verify_owner_binding(client, verifier, **args)


def _prepare_args(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key not in ("manifest", "manifest_sha256")}


def test_prepare_unsigned_manifest_from_verified_producer(case) -> None:
    from scripts import check_python_handoff_owner_binding as owner

    client, verifier, args = case
    prepared = owner.prepare_owner_manifest(client, verifier, **_prepare_args(args))
    assert prepared == args["manifest"].read_bytes()
    assert verifier.owner_calls == 0
    assert len(verifier.producer.calls) == 2
    assert client.owner_reads == 2


@pytest.mark.parametrize(
    "change",
    [
        "owner",
        "tag",
        "producer-signature",
        "archive",
        "job",
        "repository",
        "distinct-run",
        "package",
    ],
)
def test_preparation_rejects_conflicting_evidence(case, change: str) -> None:
    from scripts import check_python_handoff_owner_binding as owner

    client, verifier, args = case
    if change in ("owner", "tag"):
        client.change = change
    elif change == "producer-signature":
        verifier.producer.tamper = "wrong_run"
    elif change == "archive":
        args["downloaded_zip"].write_bytes(b"wrong")
    elif change == "job":
        args["producer_job_id"] = 1
    elif change == "repository":
        client.producer.run["repository"]["id"] = 1
        client.producer.run["head_repository"]["id"] = 1
    elif change == "distinct-run":
        args["identity"] = replace(IDENTITY, producer_run_id=RUN)
    else:
        next(args["directory"].glob("*.whl")).write_bytes(b"substitute")
    prepare_args = _prepare_args(args)
    with pytest.raises(ValueError):
        owner.prepare_owner_manifest(client, verifier, **prepare_args)
    assert verifier.owner_calls == 0


@pytest.mark.parametrize("change", ["draft", "producer-attempt", "package", "archive"])
def test_preparation_rejects_changes_after_producer_signatures(case, monkeypatch, change) -> None:
    from scripts import check_python_handoff_owner_binding as owner

    client, verifier, args = case
    original = verifier.producer.verify

    def sign(*, path: Path, repo: str, sha: str, signer: str, source_ref: str):
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        if change == "draft":
            client.release_data["draft"] = False
        elif change == "producer-attempt":
            client.producer.run["run_attempt"] = ATTEMPT + 1
        elif change == "package":
            next(args["directory"].glob("*.whl")).write_bytes(b"changed")
        else:
            args["downloaded_zip"].write_bytes(b"changed")
        return result

    monkeypatch.setattr(verifier.producer, "verify", sign)
    prepare_args = _prepare_args(args)
    with pytest.raises(ValueError):
        owner.prepare_owner_manifest(client, verifier, **prepare_args)


def test_prepare_cli_outputs_only_verified_unsigned_bytes(case, monkeypatch, capsys) -> None:
    from scripts import check_python_handoff_owner_binding as owner

    client, verifier, args = case
    identity = args["identity"]
    argv = [
        "--prepare",
        "--directory",
        str(args["directory"]),
        "--downloaded-zip",
        str(args["downloaded_zip"]),
        "--tag",
        identity.tag,
        "--source-commit",
        identity.source_commit,
        "--release-id",
        str(identity.release_id),
        "--owner-run-id",
        str(identity.owner_run_id),
        "--owner-attempt",
        str(identity.owner_attempt),
        "--producer-run-id",
        str(identity.producer_run_id),
        "--producer-attempt",
        str(identity.producer_attempt),
        "--producer-artifact-id",
        str(identity.producer_artifact_id),
        "--producer-job-id",
        str(args["producer_job_id"]),
    ]
    monkeypatch.setattr(owner, "BindingGitHubCLI", lambda: client)
    monkeypatch.setattr(owner, "GitHubAttestationCLI", lambda: verifier)
    assert owner.main(argv) == 0
    assert capsys.readouterr().out.encode() == args["manifest"].read_bytes()
    assert verifier.owner_calls == 0
    with pytest.raises(SystemExit) as exc:
        owner.main(argv + ["--manifest", str(args["manifest"])])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
