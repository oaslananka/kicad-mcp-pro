"""Verify a signed terminal Python worker receipt as the active release owner.

This diagnostic neither publishes nor proves which run uploaded to PyPI.
Receipt artifact transport and exclusive writer ownership remain separate gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import urllib3

from scripts.check_draft_producer_archive import REPOSITORY
from scripts.check_draft_release_inventory import digest
from scripts.check_draft_release_owner import _exact_id
from scripts.check_python_handoff_owner_binding import BindingClient, _owner, verify_owner_binding
from scripts.check_python_registry_receipt import (
    PyPIReadClient,
    RegistryClient,
    _check_inventory,
    _check_provenance,
    receipt_bytes,
    verify_registry_provenance,
)
from scripts.check_python_worker_request_delivery import (
    DeliveryClient,
    DeliveryGitHubCLI,
    _extract_request,
    _producer_snapshot,
    _read_archive,
    _recheck_producer_job,
    _request_metadata,
)
from scripts.check_signed_draft_asset import (
    AttestationVerifier,
    GitHubAttestationCLI,
    _approved_run_invocation,
    _attestation_match_counts,
)
from scripts.check_signed_python_dispatch_binding import (
    DispatchIdentity,
    _child_identity,
    dispatch_bytes,
)
from scripts.check_signed_python_handoff import (
    _OWNER_WORKFLOW,
    _WORKER_WORKFLOW,
    HandoffIdentity,
    _read_manifest,
    _verify_signature,
    _version,
    manifest_bytes,
)
from scripts.python_worker_dispatch_inputs import dispatch_payload, positive_id
from scripts.runtime_path_safety import approved_runtime_path

_RECEIPT = "python-worker-registry-receipt.json"


class ReceiptClient(BindingClient, DeliveryClient, Protocol):
    """Read-only maintainer-side evidence operations."""


def _terminal_child(client: DeliveryClient, identity: DispatchIdentity) -> None:
    run = _child_identity(client.workflow_run(REPOSITORY, identity.worker_run_id), identity)
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("worker has not completed successfully")


def _receipt_record(path: Path, expected: bytes, pin: str) -> Path:
    if path.is_symlink() or path.name != _RECEIPT:
        raise ValueError("unapproved or linked registry receipt")
    resolved = approved_runtime_path(path)
    if (
        not resolved.is_file()
        or hashlib.sha256(expected).hexdigest() != pin
        or _read_manifest(resolved) != expected
    ):
        raise ValueError("registry receipt bytes or independent pin mismatch")
    return resolved


def _verify_worker_signature(
    verifier: AttestationVerifier, path: Path, identity: DispatchIdentity, pin: str
) -> None:
    handoff = identity.handoff
    signed = verifier.verify(
        path=path,
        repo=REPOSITORY,
        sha=handoff.source_commit,
        signer=_WORKER_WORKFLOW,
        source_ref=f"refs/tags/{handoff.tag}",
    )
    invocation = _approved_run_invocation(identity.worker_run_id, identity.worker_attempt)
    if not isinstance(signed, list) or not signed:
        raise ValueError("missing cryptographically verified worker receipt")
    matches = sum(
        _attestation_match_counts(
            entry, filename=path.name, sha256=pin, expected_invocation=invocation
        )[1]
        for entry in signed
    )
    if not matches:
        raise ValueError("worker receipt signature or exact invocation mismatch")


def _verify_owner_request(
    client: ReceiptClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    request: bytes,
    producer_job_id: int,
    downloaded_zip: Path,
    directory: Path,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="kicad-owner-receipt-") as temporary:
        root = Path(temporary)
        _extract_request(request, root)
        binding = root / "python-worker-dispatch.json"
        expected = dispatch_bytes(identity)
        if _read_manifest(binding) != expected:
            raise ValueError("owner dispatch bytes mismatch")
        _verify_signature(
            verifier,
            binding,
            identity.handoff,
            hashlib.sha256(expected).hexdigest(),
            signer=_OWNER_WORKFLOW,
        )
        result = verify_owner_binding(
            client,
            verifier,
            identity=identity.handoff,
            producer_job_id=producer_job_id,
            downloaded_zip=downloaded_zip,
            directory=directory,
            manifest=root / "python-worker-manifest.json",
            manifest_sha256=identity.manifest_sha256,
        )
        if binding.is_symlink() or _read_manifest(binding) != expected:
            raise ValueError("owner dispatch changed during receipt verification")
        return result


@dataclass(frozen=True)
class _OwnerEvidence:
    owner: dict[str, object]
    metadata: dict[str, Any]
    request: bytes
    manifest: bytes
    producer: tuple[dict[str, Any], str]


def _capture_owner_evidence(
    client: ReceiptClient,
    *,
    identity: DispatchIdentity,
    artifact_id: int,
    archive: Path,
    directory: Path,
    downloaded_zip: Path,
) -> _OwnerEvidence:
    handoff = identity.handoff
    dispatch_bytes(identity)
    dispatch_payload(handoff, identity.manifest_sha256)
    _terminal_child(client, identity)
    owner = _owner(client, handoff)
    metadata = _request_metadata(client, identity)
    if not _exact_id(artifact_id, metadata["id"]):
        raise ValueError("owner request artifact ID mismatch")
    request = _read_archive(archive, metadata)
    manifest = manifest_bytes(handoff, directory)
    if hashlib.sha256(manifest).hexdigest() != identity.manifest_sha256:
        raise ValueError("owner manifest pin mismatch")
    producer = _producer_snapshot(client, handoff, downloaded_zip)
    return _OwnerEvidence(owner, metadata, request, manifest, producer)


def _verify_owner_evidence(
    client: ReceiptClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    evidence: _OwnerEvidence,
    producer_job_id: int,
    downloaded_zip: Path,
    directory: Path,
) -> dict[str, object]:
    report = _verify_owner_request(
        client,
        verifier,
        identity=identity,
        request=evidence.request,
        producer_job_id=producer_job_id,
        downloaded_zip=downloaded_zip,
        directory=directory,
    )
    if report["producerArchiveSha256"] != evidence.producer[1]:
        raise ValueError("producer archive pin changed")
    return report


def _recheck_owner_evidence(
    client: ReceiptClient,
    *,
    identity: DispatchIdentity,
    evidence: _OwnerEvidence,
    archive: Path,
    directory: Path,
    producer_job_id: int,
    downloaded_zip: Path,
) -> None:
    handoff = identity.handoff
    _terminal_child(client, identity)
    if (
        _owner(client, handoff) != evidence.owner
        or _request_metadata(client, identity) != evidence.metadata
    ):
        raise ValueError("owner or request identity changed during receipt verification")
    _recheck_producer_job(client, handoff, producer_job_id)
    if (
        _producer_snapshot(client, handoff, downloaded_zip) != evidence.producer
        or digest(downloaded_zip) != evidence.producer[1]
    ):
        raise ValueError("producer archive changed during receipt verification")
    if _read_archive(archive, evidence.metadata) != evidence.request:
        raise ValueError("owner request archive changed during receipt verification")
    if manifest_bytes(handoff, directory) != evidence.manifest:
        raise ValueError("owner package bytes changed during receipt verification")


def prepare_receipt_pin(
    client: ReceiptClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    artifact_id: int,
    archive: Path,
    directory: Path,
    producer_job_id: int,
    downloaded_zip: Path,
) -> str:
    """Derive the expected receipt digest from independently verified owner evidence.

    No worker receipt or registry data is read. The digest is an expectation,
    not evidence that registry verification or publication occurred.
    """
    evidence = _capture_owner_evidence(
        client,
        identity=identity,
        artifact_id=artifact_id,
        archive=archive,
        directory=directory,
        downloaded_zip=downloaded_zip,
    )
    _verify_owner_evidence(
        client,
        verifier,
        identity=identity,
        evidence=evidence,
        producer_job_id=producer_job_id,
        downloaded_zip=downloaded_zip,
        directory=directory,
    )
    _recheck_owner_evidence(
        client,
        identity=identity,
        evidence=evidence,
        archive=archive,
        directory=directory,
        producer_job_id=producer_job_id,
        downloaded_zip=downloaded_zip,
    )
    expected = receipt_bytes(
        identity,
        artifact_id,
        evidence.metadata["digest"][7:],
        json.loads(evidence.manifest)["assets"],
    )
    return hashlib.sha256(expected).hexdigest()


def verify_signed_receipt(
    client: ReceiptClient,
    verifier: AttestationVerifier,
    registry: RegistryClient,
    verify: Callable[[dict[str, Any], Path], str | None],
    *,
    identity: DispatchIdentity,
    artifact_id: int,
    archive: Path,
    directory: Path,
    producer_job_id: int,
    downloaded_zip: Path,
    receipt: Path,
    receipt_sha256: str,
) -> dict[str, object]:
    """Accept signed receipt evidence, not permission to publish a Release."""
    evidence = _capture_owner_evidence(
        client,
        identity=identity,
        artifact_id=artifact_id,
        archive=archive,
        directory=directory,
        downloaded_zip=downloaded_zip,
    )
    assets = json.loads(evidence.manifest)["assets"]
    expected = receipt_bytes(identity, artifact_id, evidence.metadata["digest"][7:], assets)
    path = _receipt_record(receipt, expected, receipt_sha256)
    _verify_worker_signature(verifier, path, identity, receipt_sha256)
    report = _verify_owner_evidence(
        client,
        verifier,
        identity=identity,
        evidence=evidence,
        producer_job_id=producer_job_id,
        downloaded_zip=downloaded_zip,
        directory=directory,
    )
    version = _version(identity.handoff)
    _check_inventory(registry, version, assets)
    _check_provenance(registry, verify, version, directory, assets)
    _check_inventory(registry, version, assets)
    _recheck_owner_evidence(
        client,
        identity=identity,
        evidence=evidence,
        archive=archive,
        directory=directory,
        producer_job_id=producer_job_id,
        downloaded_zip=downloaded_zip,
    )
    _receipt_record(receipt, expected, receipt_sha256)
    return {
        **report,
        "workerRunId": identity.worker_run_id,
        "workerRunAttempt": identity.worker_attempt,
        "ownerRequestArtifactId": artifact_id,
        "ownerRequestArchiveSha256": evidence.metadata["digest"][7:],
        "receiptSha256": receipt_sha256,
        "signedDispatchBindingVerified": True,
        "ownerRequestArtifactVerified": True,
        "artifactProducedByOwnerJobVerified": False,
        "terminalWorkerVerified": True,
        "workerReceiptSignatureVerified": True,
        "registryReceiptVerified": True,
        "registryDigestInventoryVerified": True,
        "registryPublisherProvenanceVerified": True,
        "registryPublicationRunVerified": False,
        "receiptArtifactVerified": False,
        "ownerDispatchCausalityVerified": False,
        "draftReleaseVerified": True,
        "exclusiveWriterVerified": False,
        "publicationAuthorized": False,
    }


def _receipt_parser(description: str, *, require_pin: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    for field in ("tag", "source-commit", "manifest-sha256"):
        parser.add_argument(f"--{field}", required=True)
    parser.add_argument("--receipt-sha256", required=require_pin)
    for field in (
        "release-id",
        "owner-run-id",
        "owner-attempt",
        "producer-run-id",
        "producer-attempt",
        "producer-artifact-id",
        "worker-run-id",
        "worker-attempt",
        "artifact-id",
        "producer-job-id",
    ):
        parser.add_argument(f"--{field}", type=positive_id, required=True)
    for field in ("archive", "directory", "downloaded-zip"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    return parser


def _receipt_identity(args: argparse.Namespace) -> DispatchIdentity:
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
    return DispatchIdentity(handoff, args.manifest_sha256, args.worker_run_id, args.worker_attempt)


def main(argv: list[str] | None = None) -> int:
    parser = _receipt_parser(__doc__ or "")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    identity = _receipt_identity(args)
    try:
        report = verify_signed_receipt(
            DeliveryGitHubCLI(),
            GitHubAttestationCLI(),
            PyPIReadClient(),
            verify_registry_provenance,
            identity=identity,
            artifact_id=args.artifact_id,
            archive=args.archive,
            directory=args.directory,
            producer_job_id=args.producer_job_id,
            downloaded_zip=args.downloaded_zip,
            receipt=args.receipt,
            receipt_sha256=args.receipt_sha256,
        )
    except (ValueError, OSError, urllib3.exceptions.HTTPError) as exc:
        parser.exit(2, f"Owner registry receipt: FAIL: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
