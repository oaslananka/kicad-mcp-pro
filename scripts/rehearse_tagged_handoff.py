"""Isolated tagged handoff acceptance; never authorize a production release."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.check_draft_producer_archive import REPOSITORY, _verify_artifact
from scripts.check_draft_release_owner import _REPOSITORY_ID, _exact_id
from scripts.check_python_worker_request_delivery import (
    DeliveryClient,
    DeliveryGitHubCLI,
    RequestNotReadyError,
    _read_archive,
)
from scripts.check_signed_draft_asset import AttestationVerifier, GitHubAttestationCLI
from scripts.check_signed_python_dispatch_binding import _bot, _same_repository
from scripts.check_signed_python_handoff import _verify_signature
from scripts.extract_draft_producer_zip import _members
from scripts.rehearse_signed_python_handoff import _identity, generate
from scripts.runtime_path_safety import approved_runtime_path

OWNER_PATH = ".github/workflows/tagged-handoff-rehearsal.yml"
WORKER_PATH = ".github/workflows/tagged-handoff-worker.yml"
MANIFEST = "python-worker-rehearsal.json"
BINDING = "tagged-handoff-binding.json"
RECEIPT = "tagged-handoff-receipt.json"
_PENDING = ("queued", "requested", "waiting", "pending", "in_progress")


@dataclass(frozen=True)
class Identity:
    source: str
    owner: int
    child: int

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[0-9a-f]{40}", self.source) is None
            or any(type(n) is not int or n <= 0 for n in (self.owner, self.child))
            or self.owner == self.child
        ):
            raise ValueError("invalid rehearsal identity")

    @property
    def tag(self) -> str:
        return f"handoff-rehearsal-{self.source}"


def _encoded(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_name(identity: Identity) -> str:
    return f"tagged-handoff-request-1-{identity.child}"


def receipt_name(identity: Identity) -> str:
    return f"tagged-handoff-receipt-1-{identity.child}"


def _owner_actor(actor: object) -> bool:
    return (
        isinstance(actor, dict)
        and actor.get("login") == "oaslananka"
        and _exact_id(actor.get("id"), 285490571)
    )


def _run_status(client: DeliveryClient, *, source: str, run_id: int, owner: bool) -> str:
    run = client.workflow_run(REPOSITORY, run_id)
    branch = "main" if owner else f"handoff-rehearsal-{source}"
    path = OWNER_PATH if owner else WORKER_PATH
    actor = _owner_actor if owner else _bot
    if (
        not isinstance(run, dict)
        or not _exact_id(run.get("id"), run_id)
        or not _exact_id(run.get("run_attempt"), 1)
        or run.get("url") != f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}"
        or not _same_repository(run.get("repository"))
        or not _same_repository(run.get("head_repository"))
        or not actor(run.get("actor"))
        or not actor(run.get("triggering_actor"))
        or run.get("path") not in (path, f"{path}@{branch}")
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != branch
        or run.get("head_sha") != source
    ):
        raise ValueError("rehearsal run identity mismatch")
    status = run.get("status")
    if status in _PENDING and run.get("conclusion") is None:
        return str(status)
    if status == "completed" and run.get("conclusion") == "success":
        return "completed"
    raise ValueError("rehearsal run failed or unexpected status")


def _check_owner(client: DeliveryClient, source: str, owner: int) -> None:
    if _run_status(client, source=source, run_id=owner, owner=True) != "in_progress":
        raise ValueError("rehearsal owner is not active")
    if client.tag_commit(REPOSITORY, f"handoff-rehearsal-{source}") != source:
        raise ValueError("rehearsal tag source mismatch")


def _check_runs(client: DeliveryClient, identity: Identity, statuses: tuple[str, ...]) -> str:
    """Wait for an exact owner to resume between jobs, never accept a pending owner."""
    for poll in range(12):
        owner_status = _run_status(
            client, source=identity.source, run_id=identity.owner, owner=True
        )
        if owner_status == "completed":
            raise ValueError("rehearsal owner is not active")
        if client.tag_commit(REPOSITORY, identity.tag) != identity.source:
            raise ValueError("rehearsal tag source mismatch")
        status = _run_status(client, source=identity.source, run_id=identity.child, owner=False)
        if status not in statuses:
            raise ValueError("unexpected rehearsal worker status")
        if owner_status == "in_progress":
            return status
        print(
            f"tagged rehearsal: owner status {owner_status} (poll {poll + 1}/12)", file=sys.stderr
        )
        if poll < 11:
            time.sleep(5)
    raise ValueError("rehearsal owner transition timed out")


def records(identity: Identity) -> dict[str, bytes]:
    """Independently regenerate synthetic evidence; no downloaded identity inputs."""
    with tempfile.TemporaryDirectory(prefix="tagged-handoff-") as scratch:
        bundle = Path(scratch) / "fixture"
        pin = generate(bundle, identity.source, identity.owner, 1)
        manifest = (bundle / MANIFEST).read_bytes()
    binding = _encoded(
        {
            "schemaVersion": 1,
            "rehearsal": True,
            "syntheticPackages": True,
            "repository": REPOSITORY,
            "sourceCommit": identity.source,
            "tag": identity.tag,
            "ownerRunId": identity.owner,
            "ownerRunAttempt": 1,
            "workerRunId": identity.child,
            "workerRunAttempt": 1,
            "workerWorkflow": WORKER_PATH,
            "manifestSha256": pin,
            "publicationAuthorized": False,
        }
    )
    return {MANIFEST: manifest, BINDING: binding}


def _verify_tagged_receipt_metadata(
    item: dict[str, Any], identity: Identity, artifact_id: int
) -> None:
    # Deliberately separate from the main-only production artifact gate.
    run = item.get("workflow_run")
    if (
        not isinstance(run, dict)
        or not _exact_id(run.get("id"), identity.child)
        or not _exact_id(run.get("repository_id"), _REPOSITORY_ID)
        or not _exact_id(run.get("head_repository_id"), _REPOSITORY_ID)
        or run.get("head_branch") != identity.tag
        or run.get("head_sha") != identity.source
        or item.get("expired") is not False
        or item.get("url")
        != f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact_id}"
        or item.get("archive_download_url")
        != f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"
        or not isinstance(item.get("digest"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"]) is None
    ):
        raise ValueError("invalid tagged receipt artifact identity")


def _metadata(client: DeliveryClient, identity: Identity, *, owner: bool) -> dict[str, Any]:
    run_id = identity.owner if owner else identity.child
    name = request_name(identity) if owner else receipt_name(identity)
    listing = client.workflow_artifacts(REPOSITORY, run_id)
    items = listing.get("artifacts") if isinstance(listing, dict) else None
    if (
        not isinstance(items, list)
        or len(items) > 100
        or not _exact_id(listing.get("total_count"), len(items))
        or any(not isinstance(item, dict) for item in items)
    ):
        raise ValueError("incomplete rehearsal artifact listing")
    candidates = [item for item in items if item.get("name") == name]
    if not candidates:
        raise RequestNotReadyError("rehearsal artifact not yet present")
    if len(candidates) != 1:
        raise ValueError("duplicate rehearsal artifact")
    item = candidates[0]
    artifact_id = item.get("id")
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ValueError("invalid rehearsal artifact ID")
    if owner:
        _verify_artifact(
            item,
            repo=REPOSITORY,
            repo_id=_REPOSITORY_ID,
            run_id=run_id,
            head_sha=identity.source,
            artifact_id=artifact_id,
            role=name,
        )
    else:
        _verify_tagged_receipt_metadata(item, identity, artifact_id)
    size = item.get("size_in_bytes")
    if type(size) is not int or not 0 < size <= 65536:
        raise ValueError("invalid rehearsal artifact size")
    if client.artifact(REPOSITORY, artifact_id) != item:
        raise ValueError("rehearsal artifact metadata changed")
    return item


def wait_request(client: DeliveryClient, identity: Identity) -> dict[str, Any]:
    for poll in range(30):
        _check_runs(client, identity, ("in_progress",))
        try:
            item = _metadata(client, identity, owner=True)
        except RequestNotReadyError:
            if poll < 29:
                time.sleep(5)
            continue
        _check_runs(client, identity, ("in_progress",))
        return item
    raise ValueError("rehearsal request delivery timed out")


def wait_receipt(client: DeliveryClient, identity: Identity) -> dict[str, Any]:
    for poll in range(60):
        status = _check_runs(client, identity, (*_PENDING, "completed"))
        if status == "completed":
            return _metadata(client, identity, owner=False)
        if poll < 59:
            time.sleep(5)
    raise ValueError("rehearsal worker timed out")


def _archive_files(path: Path, metadata: dict[str, Any], names: set[str]) -> dict[str, bytes]:
    data = _read_archive(path, metadata)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = _members(archive, names)
            result = {}
            for info in entries:
                if info.file_size > 16384:
                    raise ValueError("rehearsal member too large")
                with archive.open(info) as member:
                    raw = member.read(16385)
                if len(raw) != info.file_size:
                    raise ValueError("rehearsal member size mismatch")
                result[info.filename] = raw
            return result
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("invalid rehearsal archive") from exc


def _receipt(identity: Identity, metadata: dict[str, Any], files: dict[str, bytes]) -> bytes:
    return _encoded(
        {
            "schemaVersion": 1,
            "rehearsal": True,
            "syntheticPackages": True,
            "repository": REPOSITORY,
            "sourceCommit": identity.source,
            "tag": identity.tag,
            "ownerRunId": identity.owner,
            "ownerRunAttempt": 1,
            "workerRunId": identity.child,
            "workerRunAttempt": 1,
            "requestArtifactId": metadata["id"],
            "requestArchiveSha256": metadata["digest"][7:],
            "manifestSha256": _digest(files[MANIFEST]),
            "bindingSha256": _digest(files[BINDING]),
            "rehearsalSignaturesVerified": True,
            "productionTagProtectedVerified": False,
            "registryReceiptVerified": False,
            "exclusiveWriterVerified": False,
            "publicationAuthorized": False,
        }
    )


def verify_request(
    client: DeliveryClient,
    verifier: AttestationVerifier,
    identity: Identity,
    artifact_id: int,
    archive: Path,
) -> bytes:
    _check_runs(client, identity, ("in_progress",))
    item = _metadata(client, identity, owner=True)
    if not _exact_id(artifact_id, item["id"]):
        raise ValueError("rehearsal request artifact ID mismatch")
    files = records(identity)
    if _archive_files(archive, item, set(files)) != files:
        raise ValueError("rehearsal request bytes mismatch")
    with tempfile.TemporaryDirectory(prefix="tagged-signatures-") as scratch:
        for name, data in files.items():
            path = Path(scratch) / name
            path.write_bytes(data)
            _verify_signature(
                verifier,
                path,
                _identity(identity.source, identity.owner, 1),
                _digest(data),
                signer=OWNER_PATH,
            )
            if path.read_bytes() != data:
                raise ValueError("signed rehearsal record changed")
    _check_runs(client, identity, ("in_progress",))
    if _metadata(client, identity, owner=True) != item:
        raise ValueError("rehearsal request metadata changed")
    if _archive_files(archive, item, set(files)) != files:
        raise ValueError("rehearsal request changed")
    _check_runs(client, identity, ("in_progress",))
    return _receipt(identity, item, files)


def verify_receipt(
    client: DeliveryClient, identity: Identity, artifact_id: int, archive: Path
) -> bytes:
    _check_runs(client, identity, ("completed",))
    request = _metadata(client, identity, owner=True)
    item = _metadata(client, identity, owner=False)
    if not _exact_id(artifact_id, item["id"]):
        raise ValueError("rehearsal receipt artifact ID mismatch")
    expected = _receipt(identity, request, records(identity))
    if _archive_files(archive, item, {RECEIPT}) != {RECEIPT: expected}:
        raise ValueError("rehearsal receipt bytes mismatch")
    _check_runs(client, identity, ("completed",))
    if (
        _metadata(client, identity, owner=True) != request
        or _metadata(client, identity, owner=False) != item
    ):
        raise ValueError("rehearsal receipt metadata changed")
    if _archive_files(archive, item, {RECEIPT}) != {RECEIPT: expected}:
        raise ValueError("rehearsal receipt changed")
    _check_runs(client, identity, ("completed",))
    return expected


def _owner_selector(child: int) -> int:
    """An untrusted dispatch selector, never evidence of owner authorization."""
    value = os.environ.get("REHEARSAL_OWNER_RUN_ID", "")
    if re.fullmatch(r"[1-9]\d{0,14}", value, flags=re.ASCII) is None:
        raise ValueError("invalid rehearsal owner selector")
    owner = int(value)
    if owner == child:
        raise ValueError("self-referential rehearsal owner selector")
    return owner


def _runtime() -> tuple[str, int, str]:
    source = os.environ.get("GITHUB_SHA", "")
    ref = os.environ.get("GITHUB_REF", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
        or re.fullmatch(r"[0-9a-f]{40}", source) is None
        or re.fullmatch(r"[1-9]\d{0,14}", run_id, flags=re.ASCII) is None
    ):
        raise ValueError("invalid rehearsal runtime")
    return source, int(run_id), ref


def _validate_arguments(args: argparse.Namespace) -> None:
    required = {
        "check-owner": set(),
        "prepare": {"child", "output"},
        "wait-request": set(),
        "verify-request": {"archive", "artifact_id"},
        "wait-receipt": {"child"},
        "verify-receipt": {"child", "archive", "artifact_id"},
    }
    supplied = {
        name
        for name in ("child", "archive", "artifact_id", "output")
        if getattr(args, name) is not None
    }
    if supplied != required[args.operation]:
        raise ValueError("incorrect arguments for rehearsal operation")


def _prepare_request(client: DeliveryClient, identity: Identity, directory: Path | None) -> None:
    _check_runs(client, identity, _PENDING)
    if directory is None or directory.exists() or directory.is_symlink():
        raise ValueError("expected fresh request output directory")
    output = approved_runtime_path(directory)
    output.mkdir()
    for name, data in records(identity).items():
        (output / name).write_bytes(data)


def _verify_downloaded(
    client: DeliveryClient, identity: Identity, args: argparse.Namespace, *, worker: bool
) -> None:
    if args.archive is None or args.artifact_id is None:
        raise ValueError("exact downloaded artifact ID and ZIP required")
    result = (
        verify_request(client, GitHubAttestationCLI(), identity, args.artifact_id, args.archive)
        if worker
        else verify_receipt(client, identity, args.artifact_id, args.archive)
    )
    print(result.decode(), end="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "check-owner",
            "prepare",
            "wait-request",
            "verify-request",
            "wait-receipt",
            "verify-receipt",
        ),
    )
    parser.add_argument("--child", type=int)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--artifact-id", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        _validate_arguments(args)
        source, run_id, ref = _runtime()
        worker = args.operation in ("wait-request", "verify-request")
        expected_ref = f"refs/tags/handoff-rehearsal-{source}" if worker else "refs/heads/main"
        if ref != expected_ref:
            raise ValueError("wrong rehearsal runtime ref")
        owner = _owner_selector(run_id) if worker else run_id
        client = DeliveryGitHubCLI()
        if args.operation == "check-owner":
            _check_owner(client, source, run_id)
            return 0
        identity = Identity(
            source,
            owner,
            run_id if worker else args.child,
        )
        if args.operation == "prepare":
            _prepare_request(client, identity, args.output)
        elif args.operation in ("wait-request", "wait-receipt"):
            metadata = wait_request(client, identity) if worker else wait_receipt(client, identity)
            print(metadata["id"])
        else:
            _verify_downloaded(client, identity, args, worker=worker)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"tagged rehearsal: FAIL: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
