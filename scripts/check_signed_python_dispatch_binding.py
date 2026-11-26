"""Verify a post-dispatch owner-signed binding without publication authority.

The owner must separately obtain the exact child ID from the dispatch response.
This library neither issues that signature nor dispatches a workflow. A worker
can check the binding with read-only run/tag access; no draft or ruleset access
is required. The production signer remains distinct from rehearsal signers.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts.check_draft_producer_archive import REPOSITORY
from scripts.check_draft_release_owner import (
    _REPOSITORY_ID,
    OwnerRunClient,
    _exact_id,
    _owner_run_status,
)
from scripts.check_signed_draft_asset import AttestationVerifier
from scripts.check_signed_python_handoff import (
    _OWNER_WORKFLOW,
    _WORKER_WORKFLOW,
    HandoffIdentity,
    _read_manifest,
    _verify_signature,
    _version,
    manifest_bytes,
    verify_manifest,
)
from scripts.runtime_path_safety import approved_runtime_path

_NAME = "python-worker-dispatch.json"
_BOT_ID = 41898282
_BOT_LOGIN = "github-actions[bot]"


class DispatchClient(OwnerRunClient, Protocol):
    def tag_commit(self, repo: str, tag: str) -> str: ...


@dataclass(frozen=True)
class DispatchIdentity:
    handoff: HandoffIdentity
    manifest_sha256: str
    worker_run_id: int
    worker_attempt: int


def dispatch_bytes(identity: DispatchIdentity) -> bytes:
    """Canonical unsigned record generated only after the exact dispatch response."""
    handoff = identity.handoff
    _version(handoff)
    if (
        not isinstance(identity.manifest_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", identity.manifest_sha256) is None
        or type(identity.worker_run_id) is not int
        or identity.worker_run_id <= 0
        or identity.worker_run_id in (handoff.owner_run_id, handoff.producer_run_id)
        or not _exact_id(identity.worker_attempt, 1)
    ):
        raise ValueError("invalid Python dispatch identity")
    return (
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "python-worker-dispatch",
                "repository": REPOSITORY,
                "releaseTag": handoff.tag,
                "sourceCommit": handoff.source_commit,
                "releaseId": handoff.release_id,
                "ownerRunId": handoff.owner_run_id,
                "ownerRunAttempt": handoff.owner_attempt,
                "producerRunId": handoff.producer_run_id,
                "producerRunAttempt": handoff.producer_attempt,
                "producerArtifactId": handoff.producer_artifact_id,
                "manifestSha256": identity.manifest_sha256,
                "workerRunId": identity.worker_run_id,
                "workerRunAttempt": identity.worker_attempt,
                "workerWorkflow": _WORKER_WORKFLOW,
                "workerSourceRef": f"refs/tags/{handoff.tag}",
                "publicationAuthorized": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _same_repository(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("full_name") == REPOSITORY
        and _exact_id(value.get("id"), _REPOSITORY_ID)
    )


def _bot(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("login") == _BOT_LOGIN
        and _exact_id(value.get("id"), _BOT_ID)
    )


def _check_child(run: object, identity: DispatchIdentity) -> None:
    if not isinstance(run, dict):
        raise ValueError("invalid worker run response")
    expected = {
        "url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{identity.worker_run_id}",
        "path": _WORKER_WORKFLOW,
        "event": "workflow_dispatch",
        "head_branch": identity.handoff.tag,
        "head_sha": identity.handoff.source_commit,
        "status": "in_progress",
        "conclusion": None,
    }
    if (
        not _exact_id(run.get("id"), identity.worker_run_id)
        or not _exact_id(run.get("run_attempt"), 1)
        or not _same_repository(run.get("repository"))
        or not _same_repository(run.get("head_repository"))
        or not _bot(run.get("actor"))
        or not _bot(run.get("triggering_actor"))
        or any(run.get(key) != value for key, value in expected.items())
    ):
        raise ValueError("worker run does not match expected active tag dispatch")


def _check_live(client: DispatchClient, identity: DispatchIdentity) -> None:
    """Wait for a verified owner to resume, without accepting pending authority."""
    handoff = identity.handoff
    for poll in range(12):
        status = _owner_run_status(
            client,
            repo=REPOSITORY,
            owner_run_id=handoff.owner_run_id,
            owner_run_attempt=handoff.owner_attempt,
            owner_head_sha=handoff.source_commit,
        )
        _check_child(client.workflow_run(REPOSITORY, identity.worker_run_id), identity)
        if client.tag_commit(REPOSITORY, handoff.tag) != handoff.source_commit:
            raise ValueError("worker tag source mismatch")
        if status == "in_progress":
            return
        print(f"Python handoff: owner status {status} (poll {poll + 1}/12)", file=sys.stderr)
        if poll < 11:
            time.sleep(5)
    raise ValueError("Python handoff owner transition timed out")


def verify_dispatch_binding(
    client: DispatchClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    binding: Path,
    runtime_ref: str,
    runtime_sha: str,
    runtime_run_id: int,
    runtime_attempt: int,
) -> dict[str, Any]:
    """Verify the signed record against independently supplied IDs and runtime.

    The runtime values must originate from trusted Actions context, not from
    the downloaded record. This is a read-only pre-publication diagnostic.
    """
    expected = dispatch_bytes(identity)
    handoff = identity.handoff
    if (
        runtime_ref != f"refs/tags/{handoff.tag}"
        or runtime_sha != handoff.source_commit
        or not _exact_id(runtime_run_id, identity.worker_run_id)
        or not _exact_id(runtime_attempt, identity.worker_attempt)
    ):
        raise ValueError("worker runtime identity mismatch")
    if binding.is_symlink() or binding.name != _NAME:
        raise ValueError("unapproved or linked dispatch binding")
    path = approved_runtime_path(binding)
    if not path.is_file() or _read_manifest(path) != expected:
        raise ValueError("dispatch binding bytes differ from expected record")
    _check_live(client, identity)
    _verify_signature(
        verifier,
        path,
        handoff,
        hashlib.sha256(expected).hexdigest(),
        signer=_OWNER_WORKFLOW,
    )
    _check_live(client, identity)
    if binding.is_symlink() or _read_manifest(path) != expected:
        raise ValueError("dispatch binding changed during verification")
    return {
        "repository": REPOSITORY,
        "sourceCommit": handoff.source_commit,
        "releaseTag": handoff.tag,
        "releaseId": handoff.release_id,
        "ownerRunId": handoff.owner_run_id,
        "ownerRunAttempt": handoff.owner_attempt,
        "workerRunId": identity.worker_run_id,
        "workerRunAttempt": identity.worker_attempt,
        "manifestSha256": identity.manifest_sha256,
        "signedDispatchBindingVerified": True,
        "activeOwnerRunVerified": True,
        "workerRunVerified": True,
        "tagSourceVerified": True,
        "ownerDispatchCausalityVerified": False,
        "protectedTagVerified": False,
        "draftReleaseVerified": False,
        "signedOwnerManifestVerified": False,
        "packageBytesVerified": False,
        "registryReceiptVerified": False,
        "exclusiveWriterVerified": False,
        "publicationAuthorized": False,
    }


def verify_worker_request(
    client: DispatchClient,
    verifier: AttestationVerifier,
    *,
    identity: DispatchIdentity,
    binding: Path,
    directory: Path,
    manifest: Path,
    runtime_ref: str,
    runtime_sha: str,
    runtime_run_id: int,
    runtime_attempt: int,
) -> dict[str, Any]:
    """Compose both owner signatures with the exact local package bytes."""
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
    request = verify_manifest(
        verifier,
        identity=identity.handoff,
        directory=directory,
        manifest=manifest,
        manifest_sha256=identity.manifest_sha256,
    )
    _check_live(client, identity)
    expected = manifest_bytes(identity.handoff, directory)
    if (
        binding.is_symlink()
        or manifest.is_symlink()
        or _read_manifest(approved_runtime_path(binding)) != dispatch_bytes(identity)
        or _read_manifest(approved_runtime_path(manifest)) != expected
        or hashlib.sha256(expected).hexdigest() != identity.manifest_sha256
    ):
        raise ValueError("worker request changed during verification")
    return {
        **request,
        **dispatch,
        "signedOwnerManifestVerified": True,
        "packageBytesVerified": True,
    }
