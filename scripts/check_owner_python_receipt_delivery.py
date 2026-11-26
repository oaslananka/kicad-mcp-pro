"""Verify exact terminal worker receipt artifact delivery without publishing."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import urllib3

from scripts.check_draft_producer_archive import REPOSITORY, _verify_artifact
from scripts.check_draft_release_owner import _REPOSITORY_ID, _exact_id
from scripts.check_owner_python_registry_receipt import (
    _RECEIPT,
    ReceiptClient,
    _receipt_identity,
    _receipt_parser,
    _terminal_child,
    verify_signed_receipt,
)
from scripts.check_python_handoff_owner_binding import _owner
from scripts.check_python_registry_receipt import (
    PyPIReadClient,
    RegistryClient,
    verify_registry_provenance,
)
from scripts.check_python_worker_request_delivery import (
    _MAX_ARCHIVE,
    _MAX_MEMBER,
    ArtifactDownloader,
    DeliveryGitHubCLI,
    _read_archive,
    download_producer_archive,
)
from scripts.check_signed_draft_asset import AttestationVerifier, GitHubAttestationCLI
from scripts.check_signed_python_dispatch_binding import DispatchIdentity, dispatch_bytes
from scripts.check_signed_python_handoff import _read_manifest
from scripts.extract_draft_producer_zip import _members
from scripts.python_worker_dispatch_inputs import positive_id


def discover_receipt(client: ReceiptClient, identity: DispatchIdentity) -> dict[str, Any]:
    """Require a complete exact child-run listing; never select by name alone."""
    dispatch_bytes(identity)
    _terminal_child(client, identity)
    handoff = identity.handoff
    _owner(client, handoff)
    listing = client.workflow_artifacts(REPOSITORY, identity.worker_run_id)
    items = listing.get("artifacts") if isinstance(listing, dict) else None
    if (
        not isinstance(items, list)
        or len(items) > 100
        or not _exact_id(listing.get("total_count"), len(items))
        or any(not isinstance(item, dict) for item in items)
    ):
        raise ValueError("incomplete worker receipt artifact listing")
    name = f"python-worker-receipt-{identity.worker_attempt}-{handoff.owner_run_id}"
    candidates = [item for item in items if item.get("name") == name]
    if len(candidates) != 1:
        raise ValueError("expected exactly one worker receipt artifact")
    item = candidates[0]
    artifact_id = item.get("id")
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ValueError("invalid worker receipt artifact ID")
    _verify_artifact(
        item,
        repo=REPOSITORY,
        repo_id=_REPOSITORY_ID,
        run_id=identity.worker_run_id,
        head_sha=handoff.source_commit,
        artifact_id=artifact_id,
        role=name,
        head_branch=handoff.tag,
    )
    if item["size_in_bytes"] > _MAX_ARCHIVE:
        raise ValueError("worker receipt archive exceeds size limit")
    if client.artifact(REPOSITORY, artifact_id) != item:
        raise ValueError("worker receipt artifact metadata changed")
    return item


def _receipt_member(data: bytes) -> bytes:
    """Only the canonical receipt JSON is allowed in the bounded ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = _members(archive, {_RECEIPT})
            info = entries[0]
            if info.file_size > _MAX_MEMBER:
                raise ValueError("worker receipt member exceeds size limit")
            with archive.open(info) as member:
                raw = member.read(_MAX_MEMBER + 1)
            if len(raw) != info.file_size or len(raw) > _MAX_MEMBER:
                raise ValueError("worker receipt member size mismatch")
            return raw
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("unreadable worker receipt ZIP") from exc


def verify_receipt_delivery(
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
    receipt_artifact_id: int,
    receipt_archive: Path,
    receipt_sha256: str,
) -> dict[str, object]:
    """Compose verified receipt transport with independent owner acceptance."""
    metadata = discover_receipt(client, identity)
    if not _exact_id(receipt_artifact_id, metadata["id"]):
        raise ValueError("worker receipt artifact ID mismatch")
    data = _read_archive(receipt_archive, metadata)
    raw = _receipt_member(data)
    if hashlib.sha256(raw).hexdigest() != receipt_sha256:
        raise ValueError("worker receipt independent digest pin mismatch")
    with tempfile.TemporaryDirectory(prefix="kicad-worker-receipt-") as temporary:
        receipt = Path(temporary) / _RECEIPT
        receipt.write_bytes(raw)
        report = verify_signed_receipt(
            client,
            verifier,
            registry,
            verify,
            identity=identity,
            artifact_id=artifact_id,
            archive=archive,
            directory=directory,
            producer_job_id=producer_job_id,
            downloaded_zip=downloaded_zip,
            receipt=receipt,
            receipt_sha256=receipt_sha256,
        )
        if discover_receipt(client, identity) != metadata:
            raise ValueError("worker receipt metadata changed during verification")
        if _read_archive(receipt_archive, metadata) != data:
            raise ValueError("worker receipt archive changed during verification")
        if receipt.is_symlink() or _read_manifest(receipt) != raw:
            raise ValueError("extracted worker receipt changed during verification")
    return {
        **report,
        "receiptArtifactVerified": True,
        "receiptArtifactId": receipt_artifact_id,
        "receiptArchiveSha256": metadata["digest"][7:],
        "artifactProducedByWorkerJobVerified": False,
    }


def fetch_receipt_delivery(
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
    receipt_sha256: str,
    downloader: ArtifactDownloader,
) -> dict[str, object]:
    """Fetch the unique receipt into private staging and verify before returning."""
    metadata = discover_receipt(client, identity)
    with tempfile.TemporaryDirectory(prefix="kicad-receipt-download-") as temporary:
        path = Path(temporary) / "receipt.zip"
        downloader(REPOSITORY, metadata["id"], path, max_bytes=metadata["size_in_bytes"])
        if discover_receipt(client, identity) != metadata:
            raise ValueError("worker receipt metadata changed during download")
        report = verify_receipt_delivery(
            client,
            verifier,
            registry,
            verify,
            identity=identity,
            artifact_id=artifact_id,
            archive=archive,
            directory=directory,
            producer_job_id=producer_job_id,
            downloaded_zip=downloaded_zip,
            receipt_artifact_id=metadata["id"],
            receipt_archive=path,
            receipt_sha256=receipt_sha256,
        )
        if discover_receipt(client, identity) != metadata:
            raise ValueError("worker receipt metadata changed after download verification")
        _read_archive(path, metadata)
    return report


def _report(args: argparse.Namespace) -> dict[str, object]:
    identity = _receipt_identity(args)
    if args.fetch == (args.receipt_archive is not None or args.receipt_artifact_id is not None):
        raise ValueError("select fetch or provide both receipt artifact ID and ZIP")
    if not args.fetch and (args.receipt_archive is None or args.receipt_artifact_id is None):
        raise ValueError("manual receipt verification requires artifact ID and ZIP")
    options = {
        "identity": identity,
        "artifact_id": args.artifact_id,
        "archive": args.archive,
        "directory": args.directory,
        "producer_job_id": args.producer_job_id,
        "downloaded_zip": args.downloaded_zip,
        "receipt_sha256": args.receipt_sha256,
    }
    client = DeliveryGitHubCLI()
    verifier = GitHubAttestationCLI()
    registry = PyPIReadClient()
    if args.fetch:
        return fetch_receipt_delivery(
            client,
            verifier,
            registry,
            verify_registry_provenance,
            downloader=download_producer_archive,
            **options,
        )
    return verify_receipt_delivery(
        client,
        verifier,
        registry,
        verify_registry_provenance,
        receipt_artifact_id=args.receipt_artifact_id,
        receipt_archive=args.receipt_archive,
        **options,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _receipt_parser(__doc__ or "")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--receipt-artifact-id", type=positive_id)
    parser.add_argument("--receipt-archive", type=Path)
    args = parser.parse_args(argv)
    try:
        report = _report(args)
    except (ValueError, OSError, urllib3.exceptions.HTTPError) as exc:
        parser.exit(2, f"Owner receipt delivery: FAIL: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
