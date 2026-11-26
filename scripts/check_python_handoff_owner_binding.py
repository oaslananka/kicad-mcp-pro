"""Maintainer-side preparation and read-only acceptance of a Python worker request.

The existing reusable preflight producer is a separate completed run. This
diagnostic requires complete ruleset visibility, never grants that permission
to a worker, and does not authorize dispatch or publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Protocol

from scripts.check_draft_producer_archive import REPOSITORY, _verify_artifact, _verify_run
from scripts.check_draft_release_inventory import digest
from scripts.check_draft_release_owner import (
    _REPOSITORY_ID,
    OwnerClient,
    OwnerGitHubCLI,
    verify_owner,
)
from scripts.check_signed_draft_asset import AttestationVerifier, GitHubAttestationCLI
from scripts.check_signed_draft_producer_bundle import ProducerClient, verify_producer_bundle
from scripts.check_signed_python_handoff import (
    HandoffIdentity,
    _read_manifest,
    _version,
    manifest_bytes,
    verify_manifest,
)

_ROLE = "python-dist"
_PROFILE = "reusable"


class BindingClient(OwnerClient, ProducerClient, Protocol):
    """Only the read-side operations required by the composed diagnostic."""


class BindingGitHubCLI(OwnerGitHubCLI):
    def workflow_jobs(self, repo: str, run_id: int, attempt: int) -> dict[str, Any]:
        return self._json(
            f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"
        )

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]:
        return self._json(f"repos/{repo}/actions/artifacts/{artifact_id}")


def _owner(client: OwnerClient, identity: HandoffIdentity) -> dict[str, object]:
    return verify_owner(
        client,
        repo=REPOSITORY,
        release_id=identity.release_id,
        tag=identity.tag,
        source_commit=identity.source_commit,
        owner_run_id=identity.owner_run_id,
        owner_run_attempt=identity.owner_attempt,
        owner_head_sha=identity.source_commit,
    )


def _producer_pin(client: ProducerClient, identity: HandoffIdentity) -> str:
    run = client.workflow_run(REPOSITORY, identity.producer_run_id)
    repo_id = _verify_run(
        run,
        repo=REPOSITORY,
        role=_ROLE,
        run_id=identity.producer_run_id,
        attempt=identity.producer_attempt,
        head_sha=identity.source_commit,
        producer_profile=_PROFILE,
    )
    if repo_id != _REPOSITORY_ID:
        raise ValueError("producer repository numeric identity mismatch")
    artifact = client.artifact(REPOSITORY, identity.producer_artifact_id)
    return _verify_artifact(
        artifact,
        repo=REPOSITORY,
        repo_id=repo_id,
        run_id=identity.producer_run_id,
        head_sha=identity.source_commit,
        artifact_id=identity.producer_artifact_id,
        role=_ROLE,
    )


def _match_producer_bytes(expected: bytes, producer: dict[str, object]) -> None:
    signed = producer.get("signedPackages")
    assets = json.loads(expected)["assets"]
    if not isinstance(signed, list) or len(signed) != len(assets):
        raise ValueError("producer package digests differ from signed owner request")
    actual = sorted((item["package"], item["sha256"]) for item in signed)
    wanted = sorted((item["name"], item["sha256"]) for item in assets)
    if actual != wanted:
        raise ValueError("producer package digests differ from signed owner request")


def _validate_identity(identity: HandoffIdentity, producer_job_id: int) -> None:
    _version(identity)
    if (
        identity.owner_run_id == identity.producer_run_id
        or type(producer_job_id) is not int
        or producer_job_id <= 0
    ):
        raise ValueError("expected distinct owner and completed reusable producer identity")


def _verify_producer_inputs(
    client: BindingClient,
    verifier: AttestationVerifier,
    *,
    identity: HandoffIdentity,
    producer_job_id: int,
    downloaded_zip: Path,
    expected: bytes,
    archive_pin: str,
) -> None:
    producer = verify_producer_bundle(
        client,
        verifier,
        repo=REPOSITORY,
        role=_ROLE,
        tag=identity.tag,
        source_commit=identity.source_commit,
        run_id=identity.producer_run_id,
        run_attempt=identity.producer_attempt,
        job_id=producer_job_id,
        artifact_id=identity.producer_artifact_id,
        downloaded_zip=downloaded_zip,
        producer_profile=_PROFILE,
    )
    _match_producer_bytes(expected, producer)
    if producer["archiveSha256"] != archive_pin or _producer_pin(client, identity) != archive_pin:
        raise ValueError("producer archive identity changed during verification")


def _recheck_inputs(
    client: BindingClient,
    *,
    identity: HandoffIdentity,
    owner: dict[str, object],
    archive_pin: str,
    downloaded_zip: Path,
    directory: Path,
    expected: bytes,
) -> None:
    if _owner(client, identity) != owner:
        raise ValueError("owner identity changed during verification")
    if downloaded_zip.is_symlink() or digest(downloaded_zip) != archive_pin:
        raise ValueError("producer ZIP changed during verification")
    if manifest_bytes(identity, directory) != expected:
        raise ValueError("owner package bytes changed during verification")


def prepare_owner_manifest(
    client: BindingClient,
    verifier: AttestationVerifier,
    *,
    identity: HandoffIdentity,
    producer_job_id: int,
    downloaded_zip: Path,
    directory: Path,
) -> bytes:
    """Return unsigned canonical bytes only after independent producer and owner checks."""
    _validate_identity(identity, producer_job_id)
    expected = manifest_bytes(identity, directory)
    owner = _owner(client, identity)
    archive_pin = _producer_pin(client, identity)
    _verify_producer_inputs(
        client,
        verifier,
        identity=identity,
        producer_job_id=producer_job_id,
        downloaded_zip=downloaded_zip,
        expected=expected,
        archive_pin=archive_pin,
    )
    _recheck_inputs(
        client,
        identity=identity,
        owner=owner,
        archive_pin=archive_pin,
        downloaded_zip=downloaded_zip,
        directory=directory,
        expected=expected,
    )
    return expected


def verify_owner_binding(
    client: BindingClient,
    verifier: AttestationVerifier,
    *,
    identity: HandoffIdentity,
    producer_job_id: int,
    downloaded_zip: Path,
    directory: Path,
    manifest: Path,
    manifest_sha256: str,
) -> dict[str, object]:
    """Bind separate completed producer evidence to an active owner request."""
    _validate_identity(identity, producer_job_id)
    expected = manifest_bytes(identity, directory)
    if hashlib.sha256(expected).hexdigest() != manifest_sha256:
        raise ValueError("owner manifest digest pin mismatch")
    owner = _owner(client, identity)
    archive_pin = _producer_pin(client, identity)
    request = verify_manifest(
        verifier,
        identity=identity,
        directory=directory,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    _verify_producer_inputs(
        client,
        verifier,
        identity=identity,
        producer_job_id=producer_job_id,
        downloaded_zip=downloaded_zip,
        expected=expected,
        archive_pin=archive_pin,
    )
    _recheck_inputs(
        client,
        identity=identity,
        owner=owner,
        archive_pin=archive_pin,
        downloaded_zip=downloaded_zip,
        directory=directory,
        expected=expected,
    )
    if manifest.is_symlink() or _read_manifest(manifest) != expected:
        raise ValueError("owner manifest changed during verification")
    return {
        **request,
        "activeOwnerVerified": True,
        "protectedTagVerified": True,
        "producerArtifactVerified": True,
        "producerJobId": producer_job_id,
        "producerArchiveSha256": archive_pin,
        "producerJobMetadataVerified": True,
        "producerPackageSignaturesVerified": True,
        "manifestProducerBytesMatch": True,
        "artifactProducedByThisJobVerified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument(
        "--prepare", action="store_true", help="emit verified unsigned manifest bytes"
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--downloaded-zip", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--release-id", required=True, type=int)
    parser.add_argument("--owner-run-id", required=True, type=int)
    parser.add_argument("--owner-attempt", required=True, type=int)
    parser.add_argument("--producer-run-id", required=True, type=int)
    parser.add_argument("--producer-attempt", required=True, type=int)
    parser.add_argument("--producer-artifact-id", required=True, type=int)
    parser.add_argument("--producer-job-id", required=True, type=int)
    args = parser.parse_args(argv)
    identity = HandoffIdentity(
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
        if args.prepare:
            if args.manifest is not None or args.manifest_sha256 is not None:
                raise ValueError("prepare accepts no signed manifest or pin")
            payload = prepare_owner_manifest(
                BindingGitHubCLI(),
                GitHubAttestationCLI(),
                identity=identity,
                producer_job_id=args.producer_job_id,
                downloaded_zip=args.downloaded_zip,
                directory=args.directory,
            )
            sys.stdout.buffer.write(payload)
            return 0
        if args.manifest is None or args.manifest_sha256 is None:
            raise ValueError("verification requires signed manifest and independent pin")
        result = verify_owner_binding(
            BindingGitHubCLI(),
            GitHubAttestationCLI(),
            identity=identity,
            producer_job_id=args.producer_job_id,
            downloaded_zip=args.downloaded_zip,
            directory=args.directory,
            manifest=args.manifest,
            manifest_sha256=args.manifest_sha256,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Python handoff owner binding: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
