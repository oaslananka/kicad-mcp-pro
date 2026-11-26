"""Discover and verify an exact-run owner request artifact, without publishing."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Protocol

from scripts.check_draft_producer_archive import REPOSITORY, _verify_artifact
from scripts.check_draft_release_owner import (
    _REPOSITORY_ID,
    OwnerGitHubCLI,
    _exact_id,
)
from scripts.check_signed_draft_asset import AttestationVerifier, GitHubAttestationCLI
from scripts.check_signed_python_dispatch_binding import (
    DispatchClient,
    DispatchIdentity,
    _check_live,
    dispatch_bytes,
    verify_dispatch_binding,
    verify_worker_request,
)
from scripts.check_signed_python_handoff import (
    HandoffIdentity,
    _read_manifest,
    manifest_bytes,
    verify_manifest_record,
)
from scripts.extract_draft_producer_zip import _members
from scripts.runtime_path_safety import approved_runtime_path

_MAX_ARCHIVE = 65536
_MAX_MEMBER = 16384
_MAX_POLLS = 30
_POLL_INTERVAL = 5
_FILES = {"python-worker-dispatch.json", "python-worker-manifest.json"}


class DeliveryClient(DispatchClient, Protocol):
    def workflow_artifacts(self, repo: str, run_id: int) -> dict[str, Any]: ...

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]: ...


class RequestNotReadyError(ValueError):
    """Only an absent matching artifact may be retried."""


def discover_request(client: DeliveryClient, identity: DispatchIdentity) -> dict[str, Any]:
    """One bounded listing; missing, ambiguous or truncated metadata fails closed."""
    dispatch_bytes(identity)
    handoff = identity.handoff
    _check_live(client, identity)
    name = f"python-worker-request-{handoff.owner_attempt}-{identity.worker_run_id}"
    collection = client.workflow_artifacts(REPOSITORY, handoff.owner_run_id)
    if not isinstance(collection, dict):
        raise ValueError("invalid owner artifact listing")
    artifacts = collection.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or len(artifacts) > 100
        or not _exact_id(collection.get("total_count"), len(artifacts))
        or any(not isinstance(item, dict) for item in artifacts)
    ):
        raise ValueError("incomplete owner artifact listing")
    candidates = [item for item in artifacts if item.get("name") == name]
    if not candidates:
        raise RequestNotReadyError("owner request artifact not yet present")
    if len(candidates) != 1:
        raise ValueError("expected exactly one owner request artifact")
    item = candidates[0]
    artifact_id = item.get("id")
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ValueError("invalid request artifact ID")
    _verify_artifact(
        item,
        repo=REPOSITORY,
        repo_id=_REPOSITORY_ID,
        run_id=handoff.owner_run_id,
        head_sha=handoff.source_commit,
        artifact_id=artifact_id,
        role=name,
    )
    if item["size_in_bytes"] > _MAX_ARCHIVE:
        raise ValueError("owner request artifact exceeds size limit")
    if client.artifact(REPOSITORY, artifact_id) != item:
        raise ValueError("owner request artifact metadata changed")
    return item


def wait_for_request(client: DeliveryClient, identity: DispatchIdentity) -> dict[str, Any]:
    """Bound discovery attempts; retry absence only, never conflicting evidence.

    The enclosing job must also impose a wall-clock timeout on API calls.
    """
    dispatch_bytes(identity)
    for attempt in range(_MAX_POLLS):
        try:
            metadata = discover_request(client, identity)
        except RequestNotReadyError:
            if attempt + 1 < _MAX_POLLS:
                time.sleep(_POLL_INTERVAL)
            continue
        _check_live(client, identity)
        return metadata
    raise ValueError("owner request artifact delivery timed out")


def _read_archive(archive: Path, metadata: dict[str, Any]) -> bytes:
    if archive.is_symlink():
        raise ValueError("linked owner request archive")
    path = approved_runtime_path(archive)
    if not path.is_file():
        raise ValueError("missing owner request archive")
    with path.open("rb") as stream:
        data = stream.read(_MAX_ARCHIVE + 1)
    if (
        len(data) > _MAX_ARCHIVE
        or len(data) != metadata["size_in_bytes"]
        or "sha256:" + hashlib.sha256(data).hexdigest() != metadata["digest"]
    ):
        raise ValueError("owner request archive size or digest mismatch")
    return data


def _extract_request(data: bytes, output: Path) -> None:
    """Read only the two bounded, exact JSON members into a private temp directory."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = _members(archive, _FILES)
            for info in entries:
                if info.file_size > _MAX_MEMBER:
                    raise ValueError("owner request member exceeds size limit")
                with archive.open(info) as member:
                    raw = member.read(_MAX_MEMBER + 1)
                if len(raw) != info.file_size or len(raw) > _MAX_MEMBER:
                    raise ValueError("owner request member size mismatch")
                (output / info.filename).write_bytes(raw)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("unreadable owner request archive") from exc


def verify_request_delivery(
    client: DeliveryClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    artifact_id: int,
    archive: Path,
    runtime_ref: str,
    runtime_sha: str,
    runtime_run_id: int,
    runtime_attempt: int,
) -> dict[str, Any]:
    """Verify the exact signed request before downloading any producer packages."""
    return _verify_delivery(
        client,
        verifier,
        identity=identity,
        artifact_id=artifact_id,
        archive=archive,
        directory=None,
        runtime_ref=runtime_ref,
        runtime_sha=runtime_sha,
        runtime_run_id=runtime_run_id,
        runtime_attempt=runtime_attempt,
    )


def verify_delivery(
    client: DeliveryClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    artifact_id: int,
    archive: Path,
    directory: Path,
    runtime_ref: str,
    runtime_sha: str,
    runtime_run_id: int,
    runtime_attempt: int,
) -> dict[str, Any]:
    """Verify the exact signed request and independently downloaded packages."""
    if directory is None:
        raise ValueError("package directory is required for full verification")
    return _verify_delivery(
        client,
        verifier,
        identity=identity,
        artifact_id=artifact_id,
        archive=archive,
        directory=directory,
        runtime_ref=runtime_ref,
        runtime_sha=runtime_sha,
        runtime_run_id=runtime_run_id,
        runtime_attempt=runtime_attempt,
    )


def _verify_request_records(
    client: DeliveryClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    binding: Path,
    manifest: Path,
    runtime_ref: str,
    runtime_sha: str,
    runtime_run_id: int,
    runtime_attempt: int,
) -> dict[str, Any]:
    dispatch = verify_dispatch_binding(
        client,
        verifier,
        identity=identity,
        binding=binding,
        runtime_ref=runtime_ref,
        runtime_sha=runtime_sha,
        runtime_run_id=runtime_run_id,
        runtime_attempt=runtime_attempt,
    )
    request = verify_manifest_record(
        verifier,
        identity=identity.handoff,
        manifest=manifest,
        manifest_sha256=identity.manifest_sha256,
    )
    _check_live(client, identity)
    if (
        binding.is_symlink()
        or manifest.is_symlink()
        or _read_manifest(binding) != dispatch_bytes(identity)
        or hashlib.sha256(_read_manifest(manifest)).hexdigest() != identity.manifest_sha256
    ):
        raise ValueError("worker request changed during preflight")
    return {**request, **dispatch, "signedOwnerManifestVerified": True}


def _verify_delivery(
    client: DeliveryClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    artifact_id: int,
    archive: Path,
    directory: Path | None,
    runtime_ref: str,
    runtime_sha: str,
    runtime_run_id: int,
    runtime_attempt: int,
) -> dict[str, Any]:
    """Validate exact artifact bytes and both signatures; never grant publish authority."""
    metadata = discover_request(client, identity)
    if not _exact_id(artifact_id, metadata["id"]):
        raise ValueError("owner request artifact ID mismatch")
    data = _read_archive(archive, metadata)
    with tempfile.TemporaryDirectory(prefix="kicad-worker-request-") as temporary:
        root = Path(temporary)
        _extract_request(data, root)
        binding = root / "python-worker-dispatch.json"
        manifest = root / "python-worker-manifest.json"
        runtime = {
            "runtime_ref": runtime_ref,
            "runtime_sha": runtime_sha,
            "runtime_run_id": runtime_run_id,
            "runtime_attempt": runtime_attempt,
        }
        if directory is None:
            report = _verify_request_records(
                client,
                verifier,
                identity=identity,
                binding=binding,
                manifest=manifest,
                **runtime,
            )
        else:
            report = verify_worker_request(
                client,
                verifier,
                identity=identity,
                binding=binding,
                manifest=manifest,
                directory=directory,
                **runtime,
            )
    if discover_request(client, identity) != metadata or _read_archive(archive, metadata) != data:
        raise ValueError("owner request archive changed during verification")
    _check_live(client, identity)
    if (
        directory is not None
        and hashlib.sha256(manifest_bytes(identity.handoff, directory)).hexdigest()
        != identity.manifest_sha256
    ):
        raise ValueError("worker package bytes changed during delivery verification")
    return {
        **report,
        "ownerRequestArtifactId": artifact_id,
        "ownerRequestArchiveSha256": metadata["digest"][7:],
        "ownerRequestArtifactVerified": True,
        "artifactProducedByOwnerJobVerified": False,
    }


class DeliveryGitHubCLI(OwnerGitHubCLI):
    """Reuse the existing GitHub CLI read-side adapter."""

    def workflow_artifacts(self, repo: str, run_id: int) -> dict[str, Any]:
        return self._json(f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]:
        return self._json(f"repos/{repo}/actions/artifacts/{artifact_id}")


def _positive_id(value: str) -> int:
    if re.fullmatch(r"[1-9][0-9]{0,14}", value) is None:
        raise ValueError("expected canonical positive decimal ID")
    return int(value)


def _runtime(handoff: HandoffIdentity, pin: str) -> DispatchIdentity:
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("GITHUB_REF") != f"refs/tags/{handoff.tag}"
        or os.environ.get("GITHUB_SHA") != handoff.source_commit
    ):
        raise ValueError("unexpected worker runtime repository, event, ref or commit")
    identity = DispatchIdentity(
        handoff,
        pin,
        _positive_id(os.environ.get("GITHUB_RUN_ID", "")),
        _positive_id(os.environ.get("GITHUB_RUN_ATTEMPT", "")),
    )
    dispatch_bytes(identity)
    return identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("discover", "wait", "verify-request", "verify"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--release-id", required=True, type=_positive_id)
    parser.add_argument("--owner-run-id", required=True, type=_positive_id)
    parser.add_argument("--owner-attempt", required=True, type=_positive_id)
    parser.add_argument("--producer-run-id", required=True, type=_positive_id)
    parser.add_argument("--producer-attempt", required=True, type=_positive_id)
    parser.add_argument("--producer-artifact-id", required=True, type=_positive_id)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--artifact-id", type=_positive_id)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args(argv)
    handoff = HandoffIdentity(
        args.tag,
        args.source_commit,
        args.release_id,
        args.owner_run_id,
        args.owner_attempt,
        args.producer_run_id,
        args.producer_attempt,
        args.producer_artifact_id,
    )
    try:
        identity = _runtime(handoff, args.manifest_sha256)
        client = DeliveryGitHubCLI()
        if args.operation in ("discover", "wait"):
            if any(value is not None for value in (args.artifact_id, args.archive, args.directory)):
                raise ValueError("discover and wait accept identity arguments only")
            if args.operation == "wait":
                metadata = wait_for_request(client, identity)
            else:
                metadata = discover_request(client, identity)
            result = {
                "ownerRequestArtifactId": metadata["id"],
                "ownerRequestArchiveSha256": metadata["digest"][7:],
                "ownerRequestArtifactVerified": False,
                "publicationAuthorized": False,
            }
        else:
            if args.artifact_id is None or args.archive is None:
                raise ValueError("verification requires artifact ID and downloaded archive")
            if (args.operation == "verify") != (args.directory is not None):
                raise ValueError("only full verify requires a package directory")
            result = _verify_delivery(
                client,
                GitHubAttestationCLI(),
                identity=identity,
                artifact_id=args.artifact_id,
                archive=args.archive,
                directory=args.directory,
                runtime_ref=os.environ["GITHUB_REF"],
                runtime_sha=os.environ["GITHUB_SHA"],
                runtime_run_id=identity.worker_run_id,
                runtime_attempt=identity.worker_attempt,
            )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Python worker request delivery: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
