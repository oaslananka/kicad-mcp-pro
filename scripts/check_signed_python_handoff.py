"""Prepare and verify a signed Python worker request without publishing anything.

The owner signs this pre-registry inventory, not the eventual final Release
inventory (which also needs registry receipts). No production workflow calls
this diagnostic yet. A matching signature and package set is not permission
to publish.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.assemble_mcp_server_draft_assets import _SHA, _VERSION, _expected, _source_files
from scripts.check_draft_producer_archive import REPOSITORY
from scripts.check_draft_release_inventory import digest
from scripts.check_signed_draft_asset import (
    AttestationVerifier,
    GitHubAttestationCLI,
    _approved_run_invocation,
    _attestation_match_counts,
)
from scripts.runtime_path_safety import approved_runtime_path

_MANIFEST = "python-worker-manifest.json"
_OWNER_WORKFLOW = ".github/workflows/publish-release.yml"
_WORKER_WORKFLOW = ".github/workflows/publish-python.yml"
_MAX_MANIFEST_BYTES = 16384


@dataclass(frozen=True)
class HandoffIdentity:
    tag: str
    source_commit: str
    release_id: int
    owner_run_id: int
    owner_attempt: int
    producer_run_id: int
    producer_attempt: int
    producer_artifact_id: int


def _version(identity: HandoffIdentity) -> str:
    match = _VERSION.fullmatch(identity.tag)
    numbers = (
        identity.release_id,
        identity.owner_run_id,
        identity.owner_attempt,
        identity.producer_run_id,
        identity.producer_attempt,
        identity.producer_artifact_id,
    )
    if (
        match is None
        or _SHA.fullmatch(identity.source_commit) is None
        or any(type(number) is not int or number <= 0 for number in numbers)
    ):
        raise ValueError("invalid Python handoff identity")
    return match.group(1)


def manifest_bytes(identity: HandoffIdentity, directory: Path) -> bytes:
    """Generate the exact bytes the owner would attest; does not sign them."""
    version = _version(identity)
    packages = _source_files(directory, _expected(version)["python_dist"])
    payload = {
        "schemaVersion": 1,
        "kind": "python-worker-handoff",
        "repository": REPOSITORY,
        "releaseTag": identity.tag,
        "sourceCommit": identity.source_commit,
        "releaseId": identity.release_id,
        "ownerRunId": identity.owner_run_id,
        "ownerRunAttempt": identity.owner_attempt,
        "producerRunId": identity.producer_run_id,
        "producerRunAttempt": identity.producer_attempt,
        "producerArtifactId": identity.producer_artifact_id,
        "workerWorkflow": _WORKER_WORKFLOW,
        "workerSourceRef": f"refs/tags/{identity.tag}",
        "assets": [
            {"name": name, "size": path.stat().st_size, "sha256": digest(path)}
            for name, path in sorted(packages.items())
        ],
        "publicationAuthorized": False,
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > _MAX_MANIFEST_BYTES:
        raise ValueError("Python worker manifest exceeds size limit")
    return encoded


def _read_manifest(path: Path) -> bytes:
    with path.open("rb") as stream:
        return stream.read(_MAX_MANIFEST_BYTES + 1)


def _verify_signature(
    verifier: AttestationVerifier, path: Path, identity: HandoffIdentity, sha256: str
) -> None:
    invocation = _approved_run_invocation(identity.owner_run_id, identity.owner_attempt)
    signed = verifier.verify(
        path=path,
        repo=REPOSITORY,
        sha=identity.source_commit,
        signer=_OWNER_WORKFLOW,
        source_ref="refs/heads/main",
    )
    if not isinstance(signed, list) or not signed:
        raise ValueError("no cryptographically verified owner attestations")
    matches = 0
    for entry in signed:
        _, run_matches = _attestation_match_counts(
            entry, filename=path.name, sha256=sha256, expected_invocation=invocation
        )
        matches += run_matches
    if matches == 0:
        raise ValueError("signed owner manifest or exact run invocation mismatch")


def verify_manifest(
    verifier: AttestationVerifier,
    *,
    identity: HandoffIdentity,
    directory: Path,
    manifest: Path,
    manifest_sha256: str,
) -> dict[str, object]:
    """Check canonical request bytes, exact input packages and owner signature.

    All identity inputs and the digest pin must come from a trusted caller,
    not from the manifest or archive being verified.
    """
    expected = manifest_bytes(identity, directory)
    if manifest.is_symlink() or manifest.name != _MANIFEST:
        raise ValueError("unapproved or linked Python worker manifest")
    path = approved_runtime_path(manifest)
    if not path.is_file():
        raise ValueError("missing Python worker manifest")
    if hashlib.sha256(expected).hexdigest() != manifest_sha256 or _read_manifest(path) != expected:
        raise ValueError("Python worker manifest bytes or independent digest pin mismatch")

    _verify_signature(verifier, path, identity, manifest_sha256)
    if _read_manifest(path) != expected or manifest_bytes(identity, directory) != expected:
        raise ValueError("Python worker manifest or packages changed during verification")
    return {
        "repository": REPOSITORY,
        "releaseTag": identity.tag,
        "sourceCommit": identity.source_commit,
        "releaseId": identity.release_id,
        "ownerRunId": identity.owner_run_id,
        "ownerRunAttempt": identity.owner_attempt,
        "producerRunId": identity.producer_run_id,
        "producerRunAttempt": identity.producer_attempt,
        "producerArtifactId": identity.producer_artifact_id,
        "manifestSha256": manifest_sha256,
        "workerWorkflow": _WORKER_WORKFLOW,
        "signedOwnerManifestVerified": True,
        "ownerRunInvocationVerified": True,
        "packageBytesVerified": True,
        "activeOwnerVerified": False,
        "protectedTagVerified": False,
        "producerArtifactVerified": False,
        "registryReceiptVerified": False,
        "exclusiveWriterVerified": False,
        "workerRunVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("generate", "verify"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--release-id", required=True, type=int)
    parser.add_argument("--owner-run-id", required=True, type=int)
    parser.add_argument("--owner-attempt", required=True, type=int)
    parser.add_argument("--producer-run-id", required=True, type=int)
    parser.add_argument("--producer-attempt", required=True, type=int)
    parser.add_argument("--producer-artifact-id", required=True, type=int)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args()
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
        if args.operation == "generate":
            if args.manifest is not None or args.manifest_sha256 is not None:
                raise ValueError("generate writes canonical unsigned bytes to stdout only")
            sys.stdout.buffer.write(manifest_bytes(identity, args.directory))
        else:
            if args.manifest is None or args.manifest_sha256 is None:
                raise ValueError("verify requires manifest and independent SHA-256 pin")
            result = verify_manifest(
                GitHubAttestationCLI(),
                identity=identity,
                directory=args.directory,
                manifest=args.manifest,
                manifest_sha256=args.manifest_sha256,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"signed Python handoff: FAIL: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
