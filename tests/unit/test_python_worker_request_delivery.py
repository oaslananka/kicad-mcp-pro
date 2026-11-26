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
    make_request_case,
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
def delivery(tmp_path: Path) -> tuple[DeliveryClient, CombinedSignature, dict[str, Any]]:
    source, verifier, args = make_request_case(tmp_path)
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
    assert len(verifier.dispatch.calls) == 1
    assert len(verifier.manifest.calls) == 1


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


def test_discovery_waits_for_owner_transition_before_reading_artifacts(
    delivery, monkeypatch
) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    client.owner["status"] = "queued"
    pauses = []

    def resume(seconds: int) -> None:
        assert client.list_reads == 0
        pauses.append(seconds)
        client.owner["status"] = "in_progress"

    monkeypatch.setattr(cli.time, "sleep", resume)
    assert discover_request(client, args["identity"])["id"] == ARTIFACT
    assert pauses == [5]


def test_delivery_rechecks_transition_after_artifact_metadata(delivery, monkeypatch) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, verifier, args = delivery
    original = client.artifact
    pauses = []

    def detail(repo: str, artifact_id: int) -> dict[str, Any]:
        result = original(repo, artifact_id)
        client.owner["status"] = "queued"
        return result

    def resume(seconds: int) -> None:
        pauses.append(seconds)
        client.owner["status"] = "in_progress"

    monkeypatch.setattr(client, "artifact", detail)
    monkeypatch.setattr(cli.time, "sleep", resume)
    result = verify_delivery(client, verifier, **args)
    assert pauses == [5, 5]
    assert result["ownerRequestArtifactVerified"] is True
    assert result["publicationAuthorized"] is False


def _preflight_args(args):
    return {key: value for key, value in args.items() if key != "directory"}


def test_request_preflight_verifies_both_signatures_without_packages(delivery) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, verifier, args = delivery
    for package in args["directory"].iterdir():
        package.unlink()
    args["directory"].rmdir()
    report = cli.verify_request_delivery(client, verifier, **_preflight_args(args))
    assert report["ownerRequestArtifactVerified"] is True
    assert report["signedDispatchBindingVerified"] is True
    assert report["signedOwnerManifestVerified"] is True
    assert report["ownerRunInvocationVerified"] is True
    assert report["packageBytesVerified"] is False
    assert report["producerArtifactVerified"] is False
    assert report["publicationAuthorized"] is False
    assert len(verifier.dispatch.calls) == len(verifier.manifest.calls) == 1


@pytest.mark.parametrize("change", ["pin", "signature", "child", "archive", "metadata"])
def test_request_preflight_rejects_invalid_or_changed_evidence(
    delivery, monkeypatch, change
) -> None:
    from dataclasses import replace

    from scripts import check_python_worker_request_delivery as cli

    client, verifier, args = delivery
    if change == "pin":
        args["identity"] = replace(args["identity"], manifest_sha256="0" * 64)
    elif change == "signature":
        verifier.manifest.output = []
    elif change == "archive":
        args["archive"].write_bytes(b"changed")
    else:
        original = verifier.manifest.verify

        def sign(*, path: Path, repo: str, sha: str, signer: str, source_ref: str):
            result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
            if change == "child":
                client.child["run_attempt"] = 2
            else:
                client.change = True
            return result

        monkeypatch.setattr(verifier.manifest, "verify", sign)
    options = _preflight_args(args)
    with pytest.raises(ValueError):
        cli.verify_request_delivery(client, verifier, **options)


def test_request_preflight_cli_uses_independent_inputs(delivery, monkeypatch, capsys) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, verifier, args = delivery
    _runtime(monkeypatch, args)
    monkeypatch.setattr(cli, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(cli, "GitHubAttestationCLI", lambda: verifier)
    argv = _cli_args(args, "verify-request") + [
        "--artifact-id",
        str(args["artifact_id"]),
        "--archive",
        str(args["archive"]),
    ]
    assert cli.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["signedOwnerManifestVerified"] is True
    assert report["packageBytesVerified"] is False
    assert report["publicationAuthorized"] is False
    argv.extend(["--directory", str(args["directory"])])
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("value", ["+901", "0901", "9_01", " 901", "９０１"])
def test_cli_denies_noncanonical_runtime_id(delivery, monkeypatch, value) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    _runtime(monkeypatch, args)
    monkeypatch.setenv("GITHUB_RUN_ID", value)
    monkeypatch.setattr(cli, "DeliveryGitHubCLI", lambda: client)
    argv = _cli_args(args, "discover")
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2
    assert not client.reads


def _event_fields(identity: DispatchIdentity) -> dict[str, str]:
    from scripts.python_worker_dispatch_inputs import dispatch_payload

    return dispatch_payload(identity.handoff, identity.manifest_sha256)["inputs"]


def test_event_cli_verifies_request_without_manual_selectors(
    delivery,
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, verifier, args = delivery
    _runtime(monkeypatch, args)
    identity = args["identity"]
    inputs = _event_fields(identity)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": inputs, "ref": identity.handoff.tag}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setattr(cli, "DeliveryGitHubCLI", lambda: client)
    monkeypatch.setattr(cli, "GitHubAttestationCLI", lambda: verifier)
    argv = [
        "verify-request",
        "--from-event",
        "--artifact-id",
        str(args["artifact_id"]),
        "--archive",
        str(args["archive"]),
    ]
    assert cli.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["signedOwnerManifestVerified"] is True
    assert report["packageBytesVerified"] is False
    assert report["publicationAuthorized"] is False


@pytest.mark.parametrize(
    "change",
    [
        "mix",
        "wrong-ref",
        "wrong-sha",
        "wrong-repo",
        "wrong-event",
        "wrong-attempt",
        "self-owner",
        "missing-event",
    ],
)
def test_event_cli_rejects_mismatch_before_api(
    delivery,
    monkeypatch,
    tmp_path,
    change,
) -> None:
    from scripts import check_python_worker_request_delivery as cli

    client, _, args = delivery
    _runtime(monkeypatch, args)
    event = tmp_path / "event.json"
    inputs = _event_fields(args["identity"])
    argv = ["discover", "--from-event"]
    if change == "mix":
        argv.extend(["--release-id", "42"])
    elif change == "self-owner":
        inputs["owner_run_id"] = str(args["runtime_run_id"])
    elif change == "missing-event":
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    else:
        key, value = {
            "wrong-ref": ("GITHUB_REF", "refs/heads/main"),
            "wrong-sha": ("GITHUB_SHA", "b" * 40),
            "wrong-repo": ("GITHUB_REPOSITORY", "other/repo"),
            "wrong-event": ("GITHUB_EVENT_NAME", "release"),
            "wrong-attempt": ("GITHUB_RUN_ATTEMPT", "2"),
        }[change]
        monkeypatch.setenv(key, value)
    if change != "missing-event":
        event.write_text(json.dumps({"inputs": inputs}))
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setattr(cli, "DeliveryGitHubCLI", lambda: client)
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2
    assert not client.reads
    assert client.list_reads == 0


@pytest.mark.parametrize(
    "payload,exit_code,expected",
    [
        (b"abc", 0, True),
        (b"ab", 0, False),
        (b"abcd", 0, False),
        (b"abc", 1, False),
    ],
)
def test_bounded_download_adapter(tmp_path, monkeypatch, payload, exit_code, expected) -> None:
    import subprocess  # nosec B404
    import sys

    from scripts import check_python_worker_request_delivery as worker

    real_popen = subprocess.Popen
    monkeypatch.setattr(worker.shutil, "which", lambda _: "gh-test")

    def launch(command, **options: object):
        assert command == [
            "gh-test",
            "api",
            "--hostname",
            "github.com",
            f"repos/{REPO}/actions/artifacts/{ARTIFACT}/zip",
        ]
        return real_popen(
            [
                sys.executable,
                "-c",
                f"import sys; sys.stdout.buffer.write({payload!r}); sys.exit({exit_code})",
            ],
            **options,
        )

    monkeypatch.setattr(worker.subprocess, "Popen", launch)
    path = tmp_path / "producer.zip"
    if expected:
        worker.download_producer_archive(REPO, ARTIFACT, path, max_bytes=3)
        assert path.read_bytes() == payload
    else:
        with pytest.raises(ValueError):
            worker.download_producer_archive(REPO, ARTIFACT, path, max_bytes=3)
        assert path.stat().st_size <= 3


def test_download_adapter_rejects_existing_file(tmp_path, monkeypatch) -> None:
    from scripts import check_python_worker_request_delivery as worker

    path = tmp_path / "producer.zip"
    path.write_bytes(b"preserve")
    monkeypatch.setattr(worker.shutil, "which", lambda _: "gh-test")
    with pytest.raises(FileExistsError):
        worker.download_producer_archive(REPO, ARTIFACT, path, max_bytes=3)
    assert path.read_bytes() == b"preserve"


def test_download_adapter_kills_stalled_process(tmp_path, monkeypatch) -> None:
    import subprocess  # nosec B404
    import sys

    from scripts import check_python_worker_request_delivery as worker

    real_popen = subprocess.Popen
    processes = []
    monkeypatch.setattr(worker.shutil, "which", lambda _: "gh-test")
    monkeypatch.setattr(worker, "_DOWNLOAD_TIMEOUT", 0.2)

    def launch(command, **options: object):
        process = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **options)
        processes.append(process)
        return process

    monkeypatch.setattr(worker.subprocess, "Popen", launch)
    path = tmp_path / "producer.zip"
    with pytest.raises(ValueError):
        worker.download_producer_archive(REPO, ARTIFACT, path, max_bytes=3)
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert path.stat().st_size == 0
