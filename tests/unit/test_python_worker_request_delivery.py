"""Read-only delivery of an owner-signed request through exact-run artifacts."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from scripts.check_python_worker_request_delivery import discover_request, verify_delivery
from scripts.check_signed_python_dispatch_binding import DispatchIdentity
from tests.unit.test_signed_python_dispatch_binding import (
    REPO,
    RUN,
    CombinedSignature,
    ReadClient,
)
from tests.unit.test_signed_python_dispatch_binding import (
    binding as binding,
)
from tests.unit.test_signed_python_dispatch_binding import (
    request_case as request_case,
)

ARTIFACT = 88221


class DeliveryClient(ReadClient):
    def __init__(self, source: ReadClient, identity: DispatchIdentity, archive: bytes) -> None:
        super().__init__()
        self.owner = source.owner
        self.child = source.child
        handoff = identity.handoff
        self.item: dict[str, Any] = {
            "id": ARTIFACT,
            "name": f"python-worker-request-{handoff.owner_attempt}-{RUN}",
            "expired": False,
            "size_in_bytes": len(archive),
            "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
            "url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{ARTIFACT}",
            "archive_download_url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{ARTIFACT}/zip",
            "workflow_run": {
                "id": handoff.owner_run_id,
                "repository_id": 1255527274,
                "head_repository_id": 1255527274,
                "head_branch": "main",
                "head_sha": handoff.source_commit,
            },
        }
        self.collection: dict[str, Any] = {"total_count": 1, "artifacts": [self.item]}
        self.change = False
        self.list_reads = 0

    def workflow_artifacts(self, repo: str, run_id: int) -> dict[str, Any]:
        assert repo == REPO
        assert run_id == self.owner["id"]
        self.list_reads += 1
        return copy.deepcopy(self.collection)

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]:
        assert repo == REPO
        assert artifact_id == ARTIFACT
        item = copy.deepcopy(self.item)
        if self.change:
            item["expired"] = True
        return item


def archive_bytes(files: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data)
    return output.getvalue()


@pytest.fixture
def delivery(
    request_case, tmp_path: Path
) -> tuple[DeliveryClient, CombinedSignature, dict[str, Any]]:
    source, verifier, args = request_case
    files = [(args[key].name, args[key].read_bytes()) for key in ("binding", "manifest")]
    archive = archive_bytes(files)
    path = tmp_path / "owner-request.zip"
    path.write_bytes(archive)
    client = DeliveryClient(source, args["identity"], archive)
    return (
        client,
        verifier,
        {key: value for key, value in args.items() if key not in ("binding", "manifest")}
        | {"archive": path, "artifact_id": ARTIFACT},
    )


def test_exact_delivery_and_both_signatures(delivery) -> None:
    client, verifier, args = delivery
    meta = discover_request(client, args["identity"])
    assert meta["id"] == ARTIFACT
    result = verify_delivery(client, verifier, **args)
    assert result["ownerRequestArtifactVerified"] is True
    assert result["signedDispatchBindingVerified"] is True
    assert result["signedOwnerManifestVerified"] is True
    assert result["packageBytesVerified"] is True
    assert result["publicationAuthorized"] is False
    assert result["artifactProducedByOwnerJobVerified"] is False
    assert len(verifier.dispatch.calls) == len(verifier.manifest.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "duplicate",
        "truncated",
        "expired",
        "wrong-run",
        "wrong-repo",
        "wrong-name",
        "oversize",
        "digest",
        "metadata-change",
    ],
)
def test_discovery_rejects_bad_or_ambiguous_metadata(delivery, change: str) -> None:
    client, _, args = delivery
    if change == "empty":
        client.collection = {"total_count": 0, "artifacts": []}
    elif change == "duplicate":
        client.collection = {"total_count": 2, "artifacts": [client.item, dict(client.item, id=9)]}
    elif change == "truncated":
        client.collection["total_count"] = 2
    elif change == "expired":
        client.item["expired"] = True
    elif change == "wrong-run":
        client.item["workflow_run"]["id"] = 9
    elif change == "wrong-repo":
        client.item["workflow_run"]["repository_id"] = 9
    elif change == "wrong-name":
        client.item["name"] = "wrong-attempt"
    elif change == "oversize":
        client.item["size_in_bytes"] = 65537
    elif change == "digest":
        client.item["digest"] = "not-sha256"
    else:
        client.change = True
    with pytest.raises(ValueError):
        discover_request(client, args["identity"])


@pytest.mark.parametrize(
    "change", ["archive", "id", "path", "extra", "huge", "malformed", "linked"]
)
def test_invalid_archive_never_reaches_signature_verifier(delivery, change: str) -> None:
    client, verifier, args = delivery
    path = args["archive"]
    if change == "archive":
        path.write_bytes(b"changed")
    elif change == "id":
        args["artifact_id"] = 999
    elif change == "linked":
        link = path.with_name("link.zip")
        link.symlink_to(path)
        args["archive"] = link
    else:
        with zipfile.ZipFile(path) as original:
            files = [(name, original.read(name)) for name in original.namelist()]
        if change == "path":
            files[0] = ("../" + files[0][0], files[0][1])
        elif change == "extra":
            files.append(("extra.json", b"extra"))
        elif change == "huge":
            files[0] = (files[0][0], b"x" * 16385)
        data = b"not zip" if change == "malformed" else archive_bytes(files)
        path.write_bytes(data)
        client.item["size_in_bytes"] = len(data)
        client.item["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError):
        verify_delivery(client, verifier, **args)
    assert not verifier.dispatch.calls
    assert not verifier.manifest.calls


def test_live_artifact_replacement_during_signature_verification(delivery, monkeypatch) -> None:
    client, verifier, args = delivery
    original = verifier.manifest.verify

    def sign(
        *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        client.change = True
        return result

    monkeypatch.setattr(verifier.manifest, "verify", sign)
    with pytest.raises(ValueError):
        verify_delivery(client, verifier, **args)


def test_delivery_rechecks_packages_after_final_artifact_read(delivery, monkeypatch) -> None:
    client, verifier, args = delivery
    original = client.workflow_artifacts

    def listing(repo: str, run_id: int) -> dict[str, Any]:
        result = original(repo, run_id)
        if client.list_reads == 2:
            next(args["directory"].glob("*.whl")).write_bytes(b"changed after verification")
        return result

    monkeypatch.setattr(client, "workflow_artifacts", listing)
    with pytest.raises(ValueError, match="changed"):
        verify_delivery(client, verifier, **args)


def _cli_args(args: dict[str, Any], operation: str) -> list[str]:
    handoff = args["identity"].handoff
    values = [
        operation,
        "--tag",
        handoff.tag,
        "--source-commit",
        handoff.source_commit,
        "--release-id",
        str(handoff.release_id),
        "--owner-run-id",
        str(handoff.owner_run_id),
        "--owner-attempt",
        str(handoff.owner_attempt),
        "--producer-run-id",
        str(handoff.producer_run_id),
        "--producer-attempt",
        str(handoff.producer_attempt),
        "--producer-artifact-id",
        str(handoff.producer_artifact_id),
        "--manifest-sha256",
        args["identity"].manifest_sha256,
    ]
    if operation == "verify":
        values.extend(
            [
                "--artifact-id",
                str(args["artifact_id"]),
                "--archive",
                str(args["archive"]),
                "--directory",
                str(args["directory"]),
            ]
        )
    return values


def _runtime(monkeypatch, args: dict[str, Any]) -> None:
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": args["runtime_ref"],
        "GITHUB_SHA": args["runtime_sha"],
        "GITHUB_RUN_ID": str(args["runtime_run_id"]),
        "GITHUB_RUN_ATTEMPT": str(args["runtime_attempt"]),
    }.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("operation", ["discover", "verify"])
def test_cli_uses_trusted_runtime_and_read_only_client(
    delivery, operation: str, monkeypatch, capsys
) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, verifier, args = delivery
    _runtime(monkeypatch, args)
    monkeypatch.setattr(cli, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(cli, "GitHubAttestationCLI", lambda: verifier)
    assert cli.main(_cli_args(args, operation)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ownerRequestArtifactId"] == ARTIFACT
    assert report["publicationAuthorized"] is False
    if operation == "verify":
        assert report["ownerRequestArtifactVerified"] is True


@pytest.mark.parametrize(
    "key",
    [
        "GITHUB_REPOSITORY",
        "GITHUB_EVENT_NAME",
        "GITHUB_REF",
        "GITHUB_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
    ],
)
def test_cli_denies_unexpected_runtime_before_api(delivery, key: str, monkeypatch) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    _runtime(monkeypatch, args)
    monkeypatch.setenv(key, "wrong")
    monkeypatch.setattr(cli, "DeliveryGitHubCLI", lambda: client)
    arguments = _cli_args(args, "discover")
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    assert not client.reads
    assert client.list_reads == 0


def test_wait_retries_only_absent_artifact_then_accepts(delivery, monkeypatch) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    original = client.workflow_artifacts
    pauses: list[float] = []

    def listing(repo: str, run_id: int) -> dict[str, Any]:
        if client.list_reads < 2:
            client.list_reads += 1
            return {"total_count": 0, "artifacts": []}
        return original(repo, run_id)

    monkeypatch.setattr(client, "workflow_artifacts", listing)
    monkeypatch.setattr(cli.time, "sleep", pauses.append)
    assert cli.wait_for_request(client, args["identity"])["id"] == ARTIFACT
    assert client.list_reads == 3
    assert pauses == [5, 5]


def test_wait_exhausts_fixed_poll_budget(delivery, monkeypatch) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    client.collection = {"total_count": 0, "artifacts": []}
    pauses: list[float] = []
    monkeypatch.setattr(cli.time, "sleep", pauses.append)
    monkeypatch.setattr(cli, "_MAX_POLLS", 3)
    with pytest.raises(ValueError, match="timed out"):
        cli.wait_for_request(client, args["identity"])
    assert client.list_reads == 3
    assert pauses == [5, 5]


@pytest.mark.parametrize("change", ["duplicate", "truncated", "expired", "api", "owner", "child"])
def test_wait_rejects_invalid_or_changed_evidence_without_retry(
    delivery, change, monkeypatch
) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    pauses: list[float] = []
    monkeypatch.setattr(cli.time, "sleep", pauses.append)
    if change == "duplicate":
        client.collection = {"total_count": 2, "artifacts": [client.item, dict(client.item, id=9)]}
    elif change == "truncated":
        client.collection["total_count"] = 2
    elif change == "expired":
        client.item["expired"] = True
    elif change == "api":

        def unavailable(repo: str, run_id: int) -> dict[str, Any]:
            raise ValueError("GitHub read failed")

        monkeypatch.setattr(client, "workflow_artifacts", unavailable)
    elif change == "owner":
        client.owner["status"] = "completed"
    else:
        client.child["run_attempt"] = 2
    with pytest.raises(ValueError):
        cli.wait_for_request(client, args["identity"])
    assert pauses == []


def test_wait_rechecks_identity_after_delivery_appears(delivery, monkeypatch) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    original = client.artifact

    def detail(repo: str, artifact_id: int) -> dict[str, Any]:
        result = original(repo, artifact_id)
        client.child["run_attempt"] = 2
        return result

    monkeypatch.setattr(client, "artifact", detail)
    with pytest.raises(ValueError, match="worker run"):
        cli.wait_for_request(client, args["identity"])


def test_wait_cli_does_not_claim_verified_artifact(delivery, monkeypatch, capsys) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    _runtime(monkeypatch, args)
    monkeypatch.setattr(cli, "DeliveryGitHubCLI", lambda: client)
    assert cli.main(_cli_args(args, "wait")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ownerRequestArtifactId"] == ARTIFACT
    assert result["ownerRequestArtifactVerified"] is False
    assert result["publicationAuthorized"] is False
