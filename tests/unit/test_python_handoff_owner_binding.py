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


def _dispatch_case(case, monkeypatch):
    from scripts.check_signed_python_dispatch_binding import DispatchIdentity

    client, verifier, args = case
    child_id = 901
    child = copy.deepcopy(client.run_data)
    child.update(
        id=child_id,
        url=f"https://api.github.com/repos/{REPO}/actions/runs/{child_id}",
        path=".github/workflows/publish-python.yml",
        head_branch=TAG,
        head_sha=SHA,
        run_attempt=1,
        actor={"login": "github-actions[bot]", "id": 41898282},
        triggering_actor={"login": "github-actions[bot]", "id": 41898282},
    )
    original = client.workflow_run

    def read_run(repo: str, run_id: int) -> dict[str, Any]:
        if run_id == child_id:
            assert repo == REPO
            return copy.deepcopy(child)
        return original(repo, run_id)

    monkeypatch.setattr(client, "workflow_run", read_run)
    options = dict(args)
    options["identity"] = DispatchIdentity(
        args["identity"], options.pop("manifest_sha256"), child_id, 1
    )
    return client, verifier, options, child


@pytest.mark.parametrize("status", ["queued", "requested", "waiting", "pending", "in_progress"])
def test_prepare_dispatch_accepts_only_known_nonterminal_child(case, monkeypatch, status) -> None:
    import json

    from scripts import check_python_handoff_owner_binding as owner

    client, verifier, args, child = _dispatch_case(case, monkeypatch)
    child["status"] = status
    payload = json.loads(owner.prepare_owner_dispatch(client, verifier, **args))
    assert payload["workerRunId"] == 901
    assert payload["workerRunAttempt"] == 1
    assert payload["manifestSha256"] == hashlib.sha256(args["manifest"].read_bytes()).hexdigest()
    assert payload["workerSourceRef"] == f"refs/tags/{TAG}"
    assert payload["ownerRunId"] == RUN
    assert payload["publicationAuthorized"] is False
    assert verifier.owner_calls == 1
    assert len(verifier.producer.calls) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "completed"),
        ("status", "unknown"),
        ("conclusion", "success"),
        ("run_attempt", 2),
        ("head_branch", "main"),
        ("actor", {"login": "github-actions[bot]", "id": 1}),
        ("triggering_actor", {"login": "oaslananka", "id": 285490571}),
        ("path", ".github/workflows/other.yml"),
        ("head_sha", "c" * 40),
        ("id", 902),
    ],
)
def test_prepare_dispatch_rejects_wrong_child_before_signatures(
    case, monkeypatch, field, value
) -> None:
    from scripts import check_python_handoff_owner_binding as owner

    client, verifier, args, child = _dispatch_case(case, monkeypatch)
    child[field] = value
    with pytest.raises(ValueError):
        owner.prepare_owner_dispatch(client, verifier, **args)
    assert verifier.owner_calls == 0
    assert not verifier.producer.calls


@pytest.mark.parametrize(
    "change", ["child", "draft", "producer", "manifest", "package", "signature"]
)
def test_prepare_dispatch_rechecks_after_producer_signature(case, monkeypatch, change) -> None:
    from scripts import check_python_handoff_owner_binding as owner

    client, verifier, args, child = _dispatch_case(case, monkeypatch)
    original = verifier.producer.verify

    def sign(*, path: Path, repo: str, sha: str, signer: str, source_ref: str):
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        if change == "child":
            child.update(status="completed", conclusion="success")
        elif change == "draft":
            client.release_data["draft"] = False
        elif change == "producer":
            client.producer.run["run_attempt"] = ATTEMPT + 1
        elif change == "manifest":
            args["manifest"].write_bytes(b"changed")
        elif change == "package":
            next(args["directory"].glob("*.whl")).write_bytes(b"changed")
        return result

    if change == "signature":
        verifier.change = "owner-signature"
    monkeypatch.setattr(verifier.producer, "verify", sign)
    with pytest.raises(ValueError):
        owner.prepare_owner_dispatch(client, verifier, **args)


def test_prepare_dispatch_cli_preserves_signed_manifest_requirement(
    case, monkeypatch, capsys
) -> None:
    import json

    from scripts import check_python_handoff_owner_binding as owner

    client, verifier, args, child = _dispatch_case(case, monkeypatch)
    child["status"] = "queued"
    dispatch = args["identity"]
    identity = dispatch.handoff
    argv = [
        "--prepare-dispatch",
        str(dispatch.worker_run_id),
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
    with pytest.raises(SystemExit) as exc:
        owner.main(argv)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
    argv.extend(
        ["--manifest", str(args["manifest"]), "--manifest-sha256", dispatch.manifest_sha256]
    )
    inputs_argv = ["--prepare-inputs", *argv[2:]]
    assert owner.main(inputs_argv) == 0
    inputs = json.loads(capsys.readouterr().out)
    assert inputs["ref"] == identity.tag
    assert inputs["inputs"]["manifest_sha256"] == dispatch.manifest_sha256
    assert inputs["inputs"]["owner_run_id"] == str(identity.owner_run_id)
    assert inputs["inputs"]["producer_artifact_id"] == str(identity.producer_artifact_id)
    assert "worker_run_id" not in inputs["inputs"]
    invalid = inputs_argv[:-1] + ["0" * 64]
    with pytest.raises(SystemExit) as exc:
        owner.main(invalid)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
    assert owner.main(argv) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["workerRunId"] == 901
    assert payload["publicationAuthorized"] is False
    child.update(status="completed", conclusion="success")
    with pytest.raises(SystemExit) as exc:
        owner.main(argv)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.fixture
def worker_producer(case, monkeypatch, tmp_path) -> tuple[Any, ...]:
    from scripts.check_signed_python_dispatch_binding import dispatch_bytes
    from tests.unit.test_python_worker_request_delivery import ARTIFACT, archive_bytes

    source, verifier, options, child = _dispatch_case(case, monkeypatch)
    identity = options["identity"]
    data = archive_bytes(
        [
            ("python-worker-dispatch.json", dispatch_bytes(identity)),
            ("python-worker-manifest.json", options.pop("manifest").read_bytes()),
        ]
    )
    archive = tmp_path / "request.zip"
    archive.write_bytes(data)
    item = {
        "id": ARTIFACT,
        "name": f"python-worker-request-{identity.handoff.owner_attempt}-{identity.worker_run_id}",
        "expired": False,
        "size_in_bytes": len(data),
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{ARTIFACT}",
        "archive_download_url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{ARTIFACT}/zip",
        "workflow_run": {
            "id": identity.handoff.owner_run_id,
            "repository_id": 1255527274,
            "head_repository_id": 1255527274,
            "head_branch": "main",
            "head_sha": identity.handoff.source_commit,
        },
    }

    class Worker:
        def workflow_run(self, repo, run_id):
            return source.workflow_run(repo, run_id)

        def tag_commit(self, repo, tag):
            return source.tag_commit(repo, tag)

        def workflow_jobs(self, repo, run_id, attempt):
            return source.workflow_jobs(repo, run_id, attempt)

        def workflow_artifacts(self, repo, run_id):
            assert repo == REPO
            assert run_id == identity.handoff.owner_run_id
            return {"total_count": 1, "artifacts": [copy.deepcopy(item)]}

        def artifact(self, repo, artifact_id):
            if artifact_id == ARTIFACT:
                return copy.deepcopy(item)
            return source.artifact(repo, artifact_id)

    return (
        Worker(),
        verifier,
        options
        | {
            "artifact_id": ARTIFACT,
            "archive": archive,
            "runtime_ref": f"refs/tags/{identity.handoff.tag}",
            "runtime_sha": identity.handoff.source_commit,
            "runtime_run_id": identity.worker_run_id,
            "runtime_attempt": identity.worker_attempt,
        },
        source,
        child,
        item,
    )


def test_worker_producer_composes_all_signatures_read_only(worker_producer) -> None:
    from scripts import check_python_worker_request_delivery as worker

    client, verifier, args, _, _, _ = worker_producer
    report = worker.verify_producer_delivery(client, verifier, **args)
    for key in (
        "ownerRequestArtifactVerified",
        "signedDispatchBindingVerified",
        "signedOwnerManifestVerified",
        "packageBytesVerified",
        "producerArtifactVerified",
        "producerJobMetadataVerified",
        "producerPackageSignaturesVerified",
        "manifestProducerBytesMatch",
    ):
        assert report[key] is True
    for key in (
        "protectedTagVerified",
        "draftReleaseVerified",
        "artifactProducedByThisJobVerified",
        "registryReceiptVerified",
        "exclusiveWriterVerified",
        "publicationAuthorized",
    ):
        assert report[key] is False
    assert verifier.owner_calls == 2
    assert len(verifier.producer.calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        "owner-signature",
        "producer-signature",
        "archive",
        "job",
        "repository",
        "size",
        "local-package",
    ],
)
def test_worker_producer_rejects_bad_evidence(worker_producer, change) -> None:
    from scripts import check_python_worker_request_delivery as worker

    client, verifier, args, source, _, _ = worker_producer
    if change == "owner-signature":
        verifier.change = change
    elif change == "producer-signature":
        verifier.producer.tamper = "wrong_run"
    elif change == "archive":
        args["downloaded_zip"].write_bytes(b"wrong")
    elif change == "job":
        args["producer_job_id"] = 1
    elif change == "repository":
        source.producer.run["repository"]["id"] = 1
        source.producer.run["head_repository"]["id"] = 1
        source.producer.art["workflow_run"]["repository_id"] = 1
        source.producer.art["workflow_run"]["head_repository_id"] = 1
    elif change == "size":
        source.producer.art["size_in_bytes"] += 1
    else:
        next(args["directory"].glob("*.whl")).write_bytes(b"wrong")
    options = dict(args)
    with pytest.raises(ValueError):
        worker.verify_producer_delivery(client, verifier, **options)
    if change == "owner-signature":
        assert not verifier.producer.calls


@pytest.mark.parametrize(
    "change",
    ["child", "request", "producer-attempt", "producer-job", "producer-archive", "local-package"],
)
def test_worker_producer_rechecks_after_package_signatures(
    worker_producer, monkeypatch, change
) -> None:
    from scripts import check_python_worker_request_delivery as worker

    client, verifier, args, source, child, item = worker_producer
    original = verifier.producer.verify

    def sign(*, path: Path, repo: str, sha: str, signer: str, source_ref: str):
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        if change == "child":
            child["run_attempt"] = 2
        elif change == "request":
            item["expired"] = True
        elif change == "producer-attempt":
            source.producer.run["run_attempt"] += 1
        elif change == "producer-job":
            source.producer.jobs["jobs"][0]["conclusion"] = "failure"
        elif change == "producer-archive":
            args["downloaded_zip"].write_bytes(b"changed")
        else:
            next(args["directory"].glob("*.whl")).write_bytes(b"changed")
        return result

    monkeypatch.setattr(verifier.producer, "verify", sign)
    options = dict(args)
    with pytest.raises(ValueError):
        worker.verify_producer_delivery(client, verifier, **options)


def test_worker_producer_cli(worker_producer, monkeypatch, capsys) -> None:
    import json

    from scripts import check_python_worker_request_delivery as worker
    from scripts.python_worker_dispatch_inputs import dispatch_payload

    client, verifier, args, _, _, _ = worker_producer
    identity = args["identity"]
    event = args["archive"].with_name("event.json")
    event.write_text(json.dumps(dispatch_payload(identity.handoff, identity.manifest_sha256)))
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": args["runtime_ref"],
        "GITHUB_SHA": args["runtime_sha"],
        "GITHUB_RUN_ID": str(args["runtime_run_id"]),
        "GITHUB_RUN_ATTEMPT": str(args["runtime_attempt"]),
        "GITHUB_EVENT_PATH": str(event),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(worker, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(worker, "GitHubAttestationCLI", lambda: verifier)
    argv = [
        "verify-producer",
        "--from-event",
        "--artifact-id",
        str(args["artifact_id"]),
        "--archive",
        str(args["archive"]),
        "--directory",
        str(args["directory"]),
        "--producer-job-id",
        str(args["producer_job_id"]),
        "--producer-archive",
        str(args["downloaded_zip"]),
    ]
    assert worker.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["producerArtifactVerified"] is True
    assert report["publicationAuthorized"] is False
    wrong_mode = ["verify", *argv[1:]]
    with pytest.raises(SystemExit) as exc:
        worker.main(wrong_mode)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
    with pytest.raises(SystemExit) as exc:
        worker.main(argv[:-2])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.fixture
def fetch_case(worker_producer, tmp_path) -> tuple[Any, ...]:
    client, verifier, args, source, child, item = worker_producer
    payload = args.pop("downloaded_zip").read_bytes()
    args.pop("directory")
    args.pop("producer_job_id")
    args["output"] = tmp_path / "verified-dist"
    calls = []

    def download(repo, artifact_id, output, *, max_bytes):
        assert repo == REPO
        assert artifact_id == ARTIFACT_ID
        assert max_bytes == len(payload)
        assert verifier.owner_calls == 2
        assert not args["output"].exists()
        calls.append(artifact_id)
        output.write_bytes(payload)

    return client, verifier, args, source, child, item, calls, download


def test_fetch_producer_after_signed_request(fetch_case) -> None:
    from scripts import check_python_worker_request_delivery as worker

    client, verifier, args, _, _, _, calls, download = fetch_case
    report = worker.fetch_producer_delivery(client, verifier, downloader=download, **args)
    assert calls == [ARTIFACT_ID]
    assert report["producerArtifactVerified"] is True
    assert report["packageBytesVerified"] is True
    assert report["publicationAuthorized"] is False
    assert report["artifactProducedByThisJobVerified"] is False
    assert {p.name: p.read_bytes() for p in args["output"].iterdir()} == dict(_files("python-dist"))
    assert not list(args["output"].parent.glob(".kicad-worker-fetch-*"))


@pytest.mark.parametrize(
    "change",
    [
        "request-signature",
        "job-missing",
        "job-duplicate",
        "job-truncated",
        "expired",
        "oversize",
        "existing-output",
    ],
)
def test_fetch_rejects_before_download(fetch_case, change) -> None:
    from scripts import check_python_worker_request_delivery as worker

    client, verifier, args, source, _, _, calls, download = fetch_case
    if change == "request-signature":
        verifier.change = "owner-signature"
    elif change == "job-missing":
        source.producer.jobs["jobs"][0]["name"] = "other"
    elif change == "job-duplicate":
        source.producer.jobs["jobs"].append(copy.deepcopy(source.producer.jobs["jobs"][0]))
        source.producer.jobs["total_count"] += 1
    elif change == "job-truncated":
        source.producer.jobs["total_count"] += 1
    elif change == "expired":
        source.producer.art["expired"] = True
    elif change == "oversize":
        source.producer.art["size_in_bytes"] = 512 * 1024 * 1024 + 1
    else:
        args["output"].mkdir()
    options = dict(args)
    with pytest.raises(ValueError):
        worker.fetch_producer_delivery(client, verifier, downloader=download, **options)
    assert not calls


@pytest.mark.parametrize("change", ["short", "long", "signature", "child", "metadata", "failure"])
def test_fetch_failure_leaves_no_packages(fetch_case, change) -> None:
    from scripts import check_python_worker_request_delivery as worker

    client, verifier, args, source, child, _, _, download = fetch_case

    def changed_download(repo, artifact_id, output, *, max_bytes):
        download(repo, artifact_id, output, max_bytes=max_bytes)
        if change == "short":
            output.write_bytes(b"x")
        elif change == "long":
            output.write_bytes(output.read_bytes() + b"x")
        elif change == "signature":
            verifier.producer.tamper = "wrong_run"
        elif change == "child":
            child["run_attempt"] = 2
        elif change == "metadata":
            source.producer.art["expired"] = True
        else:
            raise OSError("download failed")

    options = dict(args)
    with pytest.raises((ValueError, OSError)):
        worker.fetch_producer_delivery(client, verifier, downloader=changed_download, **options)
    assert not args["output"].exists()
    assert not list(args["output"].parent.glob(".kicad-worker-fetch-*"))


def test_fetch_producer_cli(fetch_case, monkeypatch, capsys) -> None:
    import json

    from scripts import check_python_worker_request_delivery as worker
    from scripts.python_worker_dispatch_inputs import dispatch_payload

    client, verifier, args, _, _, _, calls, download = fetch_case
    identity = args["identity"]
    event = args["archive"].with_name("event.json")
    event.write_text(json.dumps(dispatch_payload(identity.handoff, identity.manifest_sha256)))
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": args["runtime_ref"],
        "GITHUB_SHA": args["runtime_sha"],
        "GITHUB_RUN_ID": str(args["runtime_run_id"]),
        "GITHUB_RUN_ATTEMPT": str(args["runtime_attempt"]),
        "GITHUB_EVENT_PATH": str(event),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(worker, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(worker, "GitHubAttestationCLI", lambda: verifier)
    monkeypatch.setattr(worker, "download_producer_archive", download)
    argv = [
        "fetch-producer",
        "--from-event",
        "--artifact-id",
        str(args["artifact_id"]),
        "--archive",
        str(args["archive"]),
        "--directory",
        str(args["output"]),
    ]
    invalid = argv + ["--producer-job-id", "1"]
    with pytest.raises(SystemExit) as exc:
        worker.main(invalid)
    assert exc.value.code == 2
    assert not calls
    assert capsys.readouterr().out == ""
    assert worker.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["producerArtifactVerified"] is True
    assert report["publicationAuthorized"] is False
    assert calls == [ARTIFACT_ID]


@pytest.fixture
def registry_case(worker_producer) -> tuple[Any, ...]:
    import json

    client, verifier, options, _, child, item = worker_producer
    args = dict(options)
    args.pop("producer_job_id")
    args.pop("downloaded_zip")
    assets = json.loads(manifest_bytes(args["identity"].handoff, args["directory"]))["assets"]
    version = args["identity"].handoff.tag.removeprefix("mcp-server-v")

    class Registry:
        def __init__(self) -> None:
            self.calls = []
            self.inventory_data = {
                "info": {"name": "kicad-mcp-pro", "version": version},
                "urls": [
                    {
                        "filename": a["name"],
                        "size": a["size"],
                        "digests": {"sha256": a["sha256"]},
                        "yanked": False,
                    }
                    for a in assets
                ],
            }
            self.failure = None

        def inventory(self, requested):
            assert requested == version
            self.calls.append("inventory")
            return copy.deepcopy(self.inventory_data)

        def provenance(self, requested, filename):
            assert requested == version
            self.calls.append(filename)
            return {"filename": filename}

        def verify(self, provenance, path):
            assert provenance["filename"] == path.name
            return self.failure

    return client, verifier, args, child, item, Registry()


def test_prepare_registry_receipt(registry_case) -> None:
    import json

    from scripts import check_python_registry_receipt as receipt

    client, verifier, args, _, _, registry = registry_case
    data = receipt.prepare_registry_receipt(client, verifier, registry, registry.verify, **args)
    record = json.loads(data)
    assert record["kind"] == "python-worker-registry-receipt"
    assert record["manifestSha256"] == args["identity"].manifest_sha256
    assert record["registryDigestInventoryVerified"] is True
    assert record["registryPublisherProvenanceVerified"] is True
    for key in (
        "registryReceiptVerified",
        "registryPublicationRunVerified",
        "exclusiveWriterVerified",
        "publicationAuthorized",
    ):
        assert record[key] is False
    assert registry.calls.count("inventory") == 2
    assert len(record["assets"]) == 2


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "missing",
        "duplicate",
        "digest",
        "size",
        "yanked",
        "version",
        "package",
        "signature",
        "owner-signature",
    ],
)
def test_registry_receipt_rejects_bad_evidence(registry_case, change) -> None:
    from scripts import check_python_registry_receipt as receipt

    client, verifier, args, _, _, registry = registry_case
    urls = registry.inventory_data["urls"]
    if change == "extra":
        urls.append(dict(urls[0], filename="extra.whl"))
    elif change == "missing":
        urls.pop()
    elif change == "duplicate":
        urls.append(copy.deepcopy(urls[0]))
    elif change == "digest":
        urls[0]["digests"]["sha256"] = "0" * 64
    elif change == "size":
        urls[0]["size"] += 1
    elif change == "yanked":
        urls[0]["yanked"] = True
    elif change == "version":
        registry.inventory_data["info"]["version"] = "0.0.0"
    elif change == "package":
        registry.inventory_data["info"]["name"] = "other"
    elif change == "signature":
        registry.failure = "cryptographic failure"
    else:
        verifier.change = "owner-signature"
    options = dict(args)
    with pytest.raises(ValueError):
        receipt.prepare_registry_receipt(client, verifier, registry, registry.verify, **options)
    if change == "owner-signature":
        assert not registry.calls


@pytest.mark.parametrize("change", ["package", "child", "request", "registry"])
def test_registry_receipt_rechecks_after_provenance(registry_case, change) -> None:
    from scripts import check_python_registry_receipt as receipt

    client, verifier, args, child, item, registry = registry_case

    def verify(provenance, path):
        if change == "package":
            path.write_bytes(b"changed")
        elif change == "child":
            child["run_attempt"] = 2
        elif change == "request":
            item["expired"] = True
        else:
            registry.inventory_data["urls"][0]["yanked"] = True
        return None

    options = dict(args)
    with pytest.raises(ValueError):
        receipt.prepare_registry_receipt(client, verifier, registry, verify, **options)


def test_registry_receipt_event_cli(registry_case, monkeypatch, capsys) -> None:
    import json

    from scripts import check_python_registry_receipt as receipt
    from scripts.python_worker_dispatch_inputs import dispatch_payload

    client, verifier, args, _, _, registry = registry_case
    identity = args["identity"]
    event = args["archive"].with_name("receipt-event.json")
    event.write_text(json.dumps(dispatch_payload(identity.handoff, identity.manifest_sha256)))
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": args["runtime_ref"],
        "GITHUB_SHA": args["runtime_sha"],
        "GITHUB_RUN_ID": str(args["runtime_run_id"]),
        "GITHUB_RUN_ATTEMPT": str(args["runtime_attempt"]),
        "GITHUB_EVENT_PATH": str(event),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(receipt, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(receipt, "GitHubAttestationCLI", lambda: verifier)
    monkeypatch.setattr(receipt, "PyPIReadClient", lambda: registry)
    monkeypatch.setattr(receipt, "verify_registry_provenance", registry.verify)
    argv = [
        "--from-event",
        "--artifact-id",
        str(args["artifact_id"]),
        "--archive",
        str(args["archive"]),
        "--directory",
        str(args["directory"]),
    ]
    assert receipt.main(argv) == 0
    raw = capsys.readouterr().out
    record = json.loads(raw)
    assert raw == json.dumps(record, indent=2, sort_keys=True) + "\n"
    assert record["publicationAuthorized"] is False
    registry.failure = "invalid provenance"
    with pytest.raises(SystemExit) as exc:
        receipt.main(argv)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.fixture
def signed_receipt_case(registry_case, worker_producer, monkeypatch) -> tuple[Any, ...]:
    from scripts.check_python_registry_receipt import prepare_registry_receipt

    client, verifier, args, child, item, registry = registry_case
    _, _, producer_args, source, _, _ = worker_producer
    data = prepare_registry_receipt(client, verifier, registry, registry.verify, **args)
    path = args["archive"].with_name("python-worker-registry-receipt.json")
    path.write_bytes(data)
    child.update(status="completed", conclusion="success")
    monkeypatch.setattr(source, "workflow_artifacts", client.workflow_artifacts, raising=False)
    original_artifact = source.artifact

    def artifact(repo, artifact_id):
        if artifact_id == item["id"]:
            return copy.deepcopy(item)
        return original_artifact(repo, artifact_id)

    monkeypatch.setattr(source, "artifact", artifact)
    original_verify = verifier.verify
    identity = args["identity"]

    def verify(*, path, repo, sha, signer, source_ref):
        if signer != ".github/workflows/publish-python.yml":
            return original_verify(
                path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref
            )
        assert repo == REPO
        assert sha == SHA
        assert source_ref == f"refs/tags/{TAG}"
        uri = f"https://github.com/{REPO}/actions/runs/{identity.worker_run_id}/attempts/1"
        if verifier.change == "worker-signature":
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

    monkeypatch.setattr(verifier, "verify", verify)
    registry.calls.clear()
    return (
        source,
        verifier,
        registry,
        child,
        item,
        {
            "identity": identity,
            "artifact_id": args["artifact_id"],
            "archive": args["archive"],
            "directory": args["directory"],
            "producer_job_id": producer_args["producer_job_id"],
            "downloaded_zip": producer_args["downloaded_zip"],
            "receipt": path,
            "receipt_sha256": hashlib.sha256(data).hexdigest(),
        },
    )


def test_owner_accepts_signed_registry_receipt(signed_receipt_case) -> None:
    from scripts import check_owner_python_registry_receipt as owner

    client, verifier, registry, _, _, args = signed_receipt_case
    report = owner.verify_signed_receipt(client, verifier, registry, registry.verify, **args)
    for key in (
        "registryReceiptVerified",
        "workerReceiptSignatureVerified",
        "terminalWorkerVerified",
        "producerPackageSignaturesVerified",
        "protectedTagVerified",
        "draftReleaseVerified",
    ):
        assert report[key] is True
    for key in (
        "registryPublicationRunVerified",
        "receiptArtifactVerified",
        "exclusiveWriterVerified",
        "publicationAuthorized",
    ):
        assert report[key] is False
    assert registry.calls.count("inventory") == 2


@pytest.mark.parametrize(
    "change",
    [
        "pending",
        "failed",
        "rerun",
        "wrong-source",
        "wrong-publisher",
        "pin",
        "receipt",
        "link",
        "owner-signature",
        "producer-signature",
        "request",
        "registry",
        "draft",
    ],
)
def test_owner_rejects_bad_signed_receipt(signed_receipt_case, change) -> None:
    from scripts import check_owner_python_registry_receipt as owner

    client, verifier, registry, child, item, args = signed_receipt_case
    if change == "pending":
        child.update(status="in_progress", conclusion=None)
    elif change == "failed":
        child["conclusion"] = "failure"
    elif change == "rerun":
        child["run_attempt"] = 2
    elif change == "wrong-source":
        child["head_sha"] = "b" * 40
    elif change == "wrong-publisher":
        verifier.change = "worker-signature"
    elif change == "pin":
        args["receipt_sha256"] = "0" * 64
    elif change == "receipt":
        args["receipt"].write_bytes(b"{}")
        args["receipt_sha256"] = hashlib.sha256(b"{}").hexdigest()
    elif change == "link":
        original = args["receipt"].with_name("original.json")
        args["receipt"].rename(original)
        args["receipt"].symlink_to(original)
    elif change == "owner-signature":
        verifier.change = change
    elif change == "producer-signature":
        verifier.producer.tamper = "wrong_run"
    elif change == "request":
        item["expired"] = True
    elif change == "registry":
        registry.inventory_data["urls"][0]["yanked"] = True
    else:
        client.release_data["draft"] = False
    options = dict(args)
    with pytest.raises(ValueError):
        owner.verify_signed_receipt(client, verifier, registry, registry.verify, **options)
    if change != "registry":
        assert not registry.calls


@pytest.mark.parametrize(
    "change", ["child", "owner", "receipt", "request", "producer", "package", "registry"]
)
def test_owner_rechecks_receipt_after_registry(signed_receipt_case, change) -> None:
    from scripts import check_owner_python_registry_receipt as owner

    client, verifier, registry, child, item, args = signed_receipt_case

    def verify(payload, path):
        if change == "child":
            child["run_attempt"] = 2
        elif change == "owner":
            client.release_data["draft"] = False
        elif change == "receipt":
            args["receipt"].write_bytes(b"changed")
        elif change == "request":
            item["expired"] = True
        elif change == "producer":
            args["downloaded_zip"].write_bytes(b"changed")
        elif change == "package":
            path.write_bytes(b"changed")
        else:
            registry.inventory_data["urls"][0]["yanked"] = True
        return None

    options = dict(args)
    with pytest.raises(ValueError):
        owner.verify_signed_receipt(client, verifier, registry, verify, **options)


def test_signed_receipt_owner_cli(signed_receipt_case, monkeypatch, capsys) -> None:
    import json

    from scripts import check_owner_python_registry_receipt as owner

    client, verifier, registry, _, _, args = signed_receipt_case
    identity = args["identity"]
    handoff = identity.handoff
    monkeypatch.setattr(owner, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(owner, "GitHubAttestationCLI", lambda: verifier)
    monkeypatch.setattr(owner, "PyPIReadClient", lambda: registry)
    monkeypatch.setattr(owner, "verify_registry_provenance", registry.verify)
    values = {
        "tag": handoff.tag,
        "source-commit": handoff.source_commit,
        "release-id": handoff.release_id,
        "owner-run-id": handoff.owner_run_id,
        "owner-attempt": handoff.owner_attempt,
        "producer-run-id": handoff.producer_run_id,
        "producer-attempt": handoff.producer_attempt,
        "producer-artifact-id": handoff.producer_artifact_id,
        "manifest-sha256": identity.manifest_sha256,
        "worker-run-id": identity.worker_run_id,
        "worker-attempt": identity.worker_attempt,
        **{key.replace("_", "-"): val for key, val in args.items() if key != "identity"},
    }
    argv = [item for key, val in values.items() for item in (f"--{key}", str(val))]
    assert owner.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["registryReceiptVerified"] is True
    assert report["publicationAuthorized"] is False
    registry.failure = "invalid publisher"
    with pytest.raises(SystemExit) as exc:
        owner.main(argv)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.fixture
def receipt_delivery_case(signed_receipt_case, monkeypatch) -> tuple[Any, ...]:
    from tests.unit.test_python_worker_request_delivery import archive_bytes

    client, verifier, registry, child, _, args = signed_receipt_case
    identity = args["identity"]
    receipt = args.pop("receipt")
    data = archive_bytes([(receipt.name, receipt.read_bytes())])
    archive = receipt.with_name("receipt.zip")
    archive.write_bytes(data)
    artifact_id = 99001
    item = {
        "id": artifact_id,
        "name": f"python-worker-receipt-{identity.worker_attempt}-{identity.handoff.owner_run_id}",
        "expired": False,
        "size_in_bytes": len(data),
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}",
        "archive_download_url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip",
        "workflow_run": {
            "id": identity.worker_run_id,
            "repository_id": 1255527274,
            "head_repository_id": 1255527274,
            "head_branch": identity.handoff.tag,
            "head_sha": identity.handoff.source_commit,
        },
    }
    listing = {"total_count": 1, "artifacts": [item]}
    original_listing = client.workflow_artifacts
    original_artifact = client.artifact

    def artifacts(repo, run_id):
        if run_id == identity.worker_run_id:
            assert repo == REPO
            return copy.deepcopy(listing)
        return original_listing(repo, run_id)

    def artifact(repo, selected):
        if selected == artifact_id:
            return copy.deepcopy(item)
        return original_artifact(repo, selected)

    monkeypatch.setattr(client, "workflow_artifacts", artifacts)
    monkeypatch.setattr(client, "artifact", artifact)
    args.update(receipt_artifact_id=artifact_id, receipt_archive=archive)
    return client, verifier, registry, child, item, listing, args


def test_verify_receipt_delivery(receipt_delivery_case) -> None:
    from scripts import check_owner_python_receipt_delivery as delivery

    client, verifier, registry, _, item, _, args = receipt_delivery_case
    report = delivery.verify_receipt_delivery(client, verifier, registry, registry.verify, **args)
    assert report["receiptArtifactVerified"] is True
    assert report["registryReceiptVerified"] is True
    assert report["receiptArtifactId"] == item["id"]
    assert report["receiptArchiveSha256"] == item["digest"][7:]
    assert report["artifactProducedByWorkerJobVerified"] is False
    assert report["publicationAuthorized"] is False


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "truncated",
        "expired",
        "wrong-id",
        "wrong-run",
        "wrong-ref",
        "wrong-repo",
        "oversize",
        "digest",
        "extra-member",
        "linked-zip",
        "pin",
        "signature",
    ],
)
def test_receipt_delivery_rejects_bad_evidence(receipt_delivery_case, change) -> None:
    from scripts import check_owner_python_receipt_delivery as delivery
    from tests.unit.test_python_worker_request_delivery import archive_bytes

    client, verifier, registry, _, item, listing, args = receipt_delivery_case
    if change == "missing":
        listing.update(total_count=0, artifacts=[])
    elif change == "duplicate":
        listing.update(total_count=2, artifacts=[item, copy.deepcopy(item)])
    elif change == "truncated":
        listing["total_count"] = 2
    elif change == "expired":
        item["expired"] = True
    elif change == "wrong-id":
        args["receipt_artifact_id"] += 1
    elif change == "wrong-run":
        item["workflow_run"]["id"] += 1
    elif change == "wrong-ref":
        item["workflow_run"]["head_branch"] = "main"
    elif change == "wrong-repo":
        item["workflow_run"]["repository_id"] = 1
    elif change == "oversize":
        item["size_in_bytes"] = 65537
    elif change == "digest":
        item["digest"] = "sha256:" + "0" * 64
    elif change == "extra-member":
        data = archive_bytes([("python-worker-registry-receipt.json", b"{}"), ("extra", b"x")])
        args["receipt_archive"].write_bytes(data)
        item.update(size_in_bytes=len(data), digest="sha256:" + hashlib.sha256(data).hexdigest())
    elif change == "linked-zip":
        path = args["receipt_archive"]
        original = path.with_name("original.zip")
        path.rename(original)
        path.symlink_to(original)
    elif change == "pin":
        args["receipt_sha256"] = "0" * 64
    else:
        verifier.change = "worker-signature"
    options = dict(args)
    with pytest.raises(ValueError):
        delivery.verify_receipt_delivery(client, verifier, registry, registry.verify, **options)
    assert not registry.calls


@pytest.mark.parametrize("change", ["metadata", "archive", "child"])
def test_receipt_delivery_rechecks_after_registry(receipt_delivery_case, change) -> None:
    from scripts import check_owner_python_receipt_delivery as delivery

    client, verifier, registry, child, item, _, args = receipt_delivery_case

    def verify(payload, path):
        if change == "metadata":
            item["expired"] = True
        elif change == "archive":
            args["receipt_archive"].write_bytes(b"changed")
        else:
            child["run_attempt"] = 2
        return None

    options = dict(args)
    with pytest.raises(ValueError):
        delivery.verify_receipt_delivery(client, verifier, registry, verify, **options)


@pytest.mark.parametrize("change", [None, "short", "long", "metadata", "io"])
def test_fetch_receipt_delivery(receipt_delivery_case, change) -> None:
    from scripts import check_owner_python_receipt_delivery as delivery

    client, verifier, registry, _, item, _, args = receipt_delivery_case
    archive = args.pop("receipt_archive")
    artifact_id = args.pop("receipt_artifact_id")
    data = archive.read_bytes()
    staged = []

    def download(repo, selected, output, *, max_bytes):
        assert repo == REPO
        assert selected == artifact_id
        assert max_bytes == len(data)
        staged.append(output)
        if change == "io":
            raise OSError("download failed")
        if change == "metadata":
            item["expired"] = True
        payload = data[:-1] if change == "short" else data
        if change == "long":
            payload += b"x"
        output.write_bytes(payload)

    if change is None:
        report = delivery.fetch_receipt_delivery(
            client, verifier, registry, registry.verify, downloader=download, **args
        )
        assert report["receiptArtifactVerified"] is True
        assert report["publicationAuthorized"] is False
    else:
        options = dict(args)
        with pytest.raises((ValueError, OSError)):
            delivery.fetch_receipt_delivery(
                client, verifier, registry, registry.verify, downloader=download, **options
            )
        assert not registry.calls
    assert len(staged) == 1
    assert not staged[0].parent.exists()


def test_receipt_delivery_cli(receipt_delivery_case, monkeypatch, capsys) -> None:
    import json

    from scripts import check_owner_python_receipt_delivery as delivery

    client, verifier, registry, _, _, _, args = receipt_delivery_case
    identity = args["identity"]
    handoff = identity.handoff
    monkeypatch.setattr(delivery, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(delivery, "GitHubAttestationCLI", lambda: verifier)
    monkeypatch.setattr(delivery, "PyPIReadClient", lambda: registry)
    monkeypatch.setattr(delivery, "verify_registry_provenance", registry.verify)
    values = {
        "tag": handoff.tag,
        "source-commit": handoff.source_commit,
        "release-id": handoff.release_id,
        "owner-run-id": handoff.owner_run_id,
        "owner-attempt": handoff.owner_attempt,
        "producer-run-id": handoff.producer_run_id,
        "producer-attempt": handoff.producer_attempt,
        "producer-artifact-id": handoff.producer_artifact_id,
        "manifest-sha256": identity.manifest_sha256,
        "worker-run-id": identity.worker_run_id,
        "worker-attempt": identity.worker_attempt,
        **{key.replace("_", "-"): val for key, val in args.items() if key != "identity"},
    }
    argv = [entry for key, val in values.items() for entry in (f"--{key}", str(val))]
    assert delivery.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["receiptArtifactVerified"] is True
    bad = argv + ["--fetch"]
    with pytest.raises(SystemExit) as exc:
        delivery.main(bad)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


def test_prepare_independent_receipt_pin(signed_receipt_case) -> None:
    from scripts import check_owner_python_registry_receipt as owner

    client, verifier, registry, _, _, args = signed_receipt_case
    expected = args.pop("receipt_sha256")
    receipt = args.pop("receipt")
    receipt.unlink()
    assert owner.prepare_receipt_pin(client, verifier, **args) == expected
    assert not registry.calls


@pytest.mark.parametrize(
    "change", ["pending", "request", "manifest", "owner", "producer", "signature"]
)
def test_prepare_receipt_pin_rejects_unverified_inputs(signed_receipt_case, change) -> None:
    from scripts import check_owner_python_registry_receipt as owner

    client, verifier, registry, child, item, args = signed_receipt_case
    args.pop("receipt")
    args.pop("receipt_sha256")
    if change == "pending":
        child.update(status="queued", conclusion=None)
    elif change == "request":
        item["expired"] = True
    elif change == "manifest":
        args["identity"] = replace(args["identity"], manifest_sha256="0" * 64)
    elif change == "owner":
        client.release_data["draft"] = False
    elif change == "producer":
        args["downloaded_zip"].write_bytes(b"changed")
    else:
        verifier.change = "owner-signature"
    options = dict(args)
    with pytest.raises(ValueError):
        owner.prepare_receipt_pin(client, verifier, **options)
    assert not registry.calls


@pytest.mark.parametrize("status", ["queued", "requested", "waiting", "pending", "in_progress"])
def test_wait_terminal_worker_recovers(signed_receipt_case, monkeypatch, status) -> None:
    from scripts import check_owner_python_receipt_delivery as delivery

    client, _, _, child, _, args = signed_receipt_case
    child.update(status=status, conclusion=None)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        child.update(status="completed", conclusion="success")

    monkeypatch.setattr(delivery.time, "sleep", sleep)
    delivery.wait_terminal_worker(client, args["identity"])
    assert sleeps == [5]


@pytest.mark.parametrize("change", ["failure", "cancelled", "unknown", "rerun", "owner", "timeout"])
def test_wait_terminal_worker_fails_closed(signed_receipt_case, monkeypatch, change) -> None:
    from scripts import check_owner_python_receipt_delivery as delivery

    client, _, _, child, _, args = signed_receipt_case
    if change in ("failure", "cancelled"):
        child["conclusion"] = change
    elif change == "unknown":
        child.update(status="unknown", conclusion=None)
    elif change == "rerun":
        child["run_attempt"] = 2
    elif change == "owner":
        client.release_data["draft"] = False
    else:
        child.update(status="queued", conclusion=None)
    sleeps = []
    monkeypatch.setattr(delivery.time, "sleep", sleeps.append)
    identity = args["identity"]
    with pytest.raises(ValueError):
        delivery.wait_terminal_worker(client, identity)
    assert len(sleeps) == (59 if change == "timeout" else 0)


def test_reconcile_receipt_without_worker_supplied_pin(receipt_delivery_case, monkeypatch) -> None:
    from scripts import check_owner_python_receipt_delivery as delivery

    client, verifier, registry, child, item, _, args = receipt_delivery_case
    expected = args.pop("receipt_sha256")
    data = args.pop("receipt_archive").read_bytes()
    args.pop("receipt_artifact_id")
    child.update(status="queued", conclusion=None)

    def sleep(seconds):
        assert seconds == 5
        child.update(status="completed", conclusion="success")

    def download(repo, selected, output, *, max_bytes):
        assert repo == REPO
        assert selected == item["id"]
        assert max_bytes == len(data)
        output.write_bytes(data)

    monkeypatch.setattr(delivery.time, "sleep", sleep)
    report = delivery.reconcile_receipt(
        client, verifier, registry, registry.verify, downloader=download, **args
    )
    assert report["receiptSha256"] == expected
    assert report["receiptArtifactVerified"] is True
    assert report["publicationAuthorized"] is False


def test_receipt_pin_rechecks_request_after_signatures(signed_receipt_case, monkeypatch) -> None:
    from scripts import check_owner_python_registry_receipt as owner

    client, verifier, registry, _, item, args = signed_receipt_case
    args.pop("receipt")
    args.pop("receipt_sha256")
    original = verifier.verify

    def verify(*, path: Path, repo: str, sha: str, signer: str, source_ref: str):
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        item["expired"] = True
        return result

    monkeypatch.setattr(verifier, "verify", verify)
    options = dict(args)
    with pytest.raises(ValueError):
        owner.prepare_receipt_pin(client, verifier, **options)
    assert not registry.calls


def test_reconcile_receipt_cli(receipt_delivery_case, monkeypatch, capsys) -> None:
    import json

    from scripts import check_owner_python_receipt_delivery as delivery

    client, verifier, registry, _, item, _, args = receipt_delivery_case
    identity = args["identity"]
    handoff = identity.handoff
    pin = args.pop("receipt_sha256")
    data = args.pop("receipt_archive").read_bytes()
    args.pop("receipt_artifact_id")
    monkeypatch.setattr(delivery, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(delivery, "GitHubAttestationCLI", lambda: verifier)
    monkeypatch.setattr(delivery, "PyPIReadClient", lambda: registry)
    monkeypatch.setattr(delivery, "verify_registry_provenance", registry.verify)

    def download(repo, selected, output, *, max_bytes):
        assert repo == REPO
        assert selected == item["id"]
        assert max_bytes == len(data)
        output.write_bytes(data)

    monkeypatch.setattr(delivery, "download_producer_archive", download)
    values = {
        "tag": handoff.tag,
        "source-commit": handoff.source_commit,
        "release-id": handoff.release_id,
        "owner-run-id": handoff.owner_run_id,
        "owner-attempt": handoff.owner_attempt,
        "producer-run-id": handoff.producer_run_id,
        "producer-attempt": handoff.producer_attempt,
        "producer-artifact-id": handoff.producer_artifact_id,
        "manifest-sha256": identity.manifest_sha256,
        "worker-run-id": identity.worker_run_id,
        "worker-attempt": identity.worker_attempt,
        **{key.replace("_", "-"): val for key, val in args.items() if key != "identity"},
    }
    argv = [entry for key, val in values.items() for entry in (f"--{key}", str(val))]
    argv.append("--reconcile")
    assert delivery.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["receiptSha256"] == pin
    assert report["publicationAuthorized"] is False
    bad = argv + ["--receipt-sha256", pin]
    with pytest.raises(SystemExit) as exc:
        delivery.main(bad)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""
