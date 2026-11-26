"""Prepare an unsigned, read-only Python registry receipt for a future release owner.

A PyPI publish attestation authenticates the trusted publisher and distribution,
not the exact worker invocation. No receipt is signed or accepted here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import urllib3

from scripts.check_draft_producer_archive import REPOSITORY
from scripts.check_draft_release_inventory import digest
from scripts.check_python_worker_request_delivery import (
    DeliveryClient,
    DeliveryGitHubCLI,
    _read_archive,
    _runtime,
    discover_request,
    verify_delivery,
)
from scripts.check_signed_draft_asset import AttestationVerifier, GitHubAttestationCLI
from scripts.check_signed_python_dispatch_binding import (
    DispatchIdentity,
    _check_live,
    dispatch_bytes,
)
from scripts.check_signed_python_handoff import _MAX_MANIFEST_BYTES, _version, manifest_bytes
from scripts.generate_release_evidence import (
    PYPI_ENDPOINTS,
    PYPI_INTEGRITY_ENDPOINTS,
    _cryptographic_provenance_failure,
    _provenance_failure,
)
from scripts.python_worker_dispatch_inputs import positive_id, read_event_inputs

_PACKAGE = "kicad-mcp-pro"
_REGISTRY = "pypi"
_WORKFLOW = "publish-python.yml"
_MAX_JSON = 4 * 1024 * 1024


class RegistryClient(Protocol):
    def inventory(self, version: str) -> dict[str, Any]: ...
    def provenance(self, version: str, filename: str) -> dict[str, Any]: ...


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate registry JSON key")
        result[key] = value
    return result


def _read_registry_json(url: str, accept: str) -> dict[str, Any]:
    target = urlsplit(url)
    if target.scheme != "https" or target.netloc != "pypi.org" or target.query or target.fragment:
        raise ValueError("unapproved registry URL")
    # The project already pins urllib3; no proxy, redirects, retries or decompression.
    pool = urllib3.PoolManager(cert_reqs="CERT_REQUIRED", timeout=30.0)
    try:
        with pool.request(
            "GET",
            url,
            headers={"Accept": accept, "Accept-Encoding": "identity"},
            preload_content=False,
            redirect=False,
            retries=False,
            decode_content=False,
        ) as response:
            if response.status != 200:
                raise ValueError("registry response is not HTTP 200")
            raw = response.read(_MAX_JSON + 1)
    finally:
        pool.clear()
    if len(raw) > _MAX_JSON:
        raise ValueError("registry JSON exceeds size limit")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid registry JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid registry response")
    return payload


class PyPIReadClient:
    """Fixed production PyPI endpoints; no credentials or registry mutations."""

    def inventory(self, version: str) -> dict[str, Any]:
        url = PYPI_ENDPOINTS[_REGISTRY].format(name=_PACKAGE, version=quote(version, safe=""))
        return _read_registry_json(url, "application/json")

    def provenance(self, version: str, filename: str) -> dict[str, Any]:
        url = PYPI_INTEGRITY_ENDPOINTS[_REGISTRY].format(
            name=_PACKAGE, version=quote(version, safe=""), filename=quote(filename, safe="")
        )
        return _read_registry_json(url, "application/vnd.pypi.integrity.v1+json")


def _matches_distribution(item: object, asset: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    digests = item.get("digests")
    return (
        item.get("filename") == asset["name"]
        and type(item.get("size")) is int
        and item["size"] == asset["size"]
        and item.get("yanked") is False
        and isinstance(digests, dict)
        and digests.get("sha256") == asset["sha256"]
    )


def _check_inventory(registry: RegistryClient, version: str, assets: list[dict[str, Any]]) -> None:
    payload = registry.inventory(version)
    info = payload.get("info") if isinstance(payload, dict) else None
    urls = payload.get("urls") if isinstance(payload, dict) else None
    if (
        not isinstance(info, dict)
        or info.get("name") != _PACKAGE
        or info.get("version") != version
        or not isinstance(urls, list)
        or len(urls) != len(assets)
    ):
        raise ValueError("registry package, version or complete inventory mismatch")
    for asset in assets:
        if sum(_matches_distribution(item, asset) for item in urls) != 1:
            raise ValueError("registry distribution digest, size or identity mismatch")


def verify_registry_provenance(payload: dict[str, Any], path: Path) -> str | None:
    """Require PEP 740 publish provenance and cryptographic verification."""
    expected = {
        "publisher_repository": REPOSITORY,
        "publisher_workflow": _WORKFLOW,
        "publisher_environment": _REGISTRY,
    }
    failure = _provenance_failure(payload, filename=path.name, digest=digest(path), **expected)
    if failure:
        return failure
    return _cryptographic_provenance_failure(payload, artifact_path=path, **expected)


def _check_provenance(
    registry: RegistryClient,
    verify: Callable[[dict[str, Any], Path], str | None],
    version: str,
    directory: Path,
    assets: list[dict[str, Any]],
) -> None:
    for asset in assets:
        path = directory / asset["name"]
        payload = registry.provenance(version, path.name)
        if path.is_symlink() or digest(path) != asset["sha256"]:
            raise ValueError("worker package changed before provenance verification")
        if verify(payload, path) is not None:
            raise ValueError("registry publisher provenance verification failed")


def prepare_registry_receipt(
    client: DeliveryClient,
    verifier: AttestationVerifier,
    registry: RegistryClient,
    verify: Callable[[dict[str, Any], Path], str | None],
    *,
    identity: DispatchIdentity,
    artifact_id: int,
    archive: Path,
    directory: Path,
    runtime_ref: str,
    runtime_sha: str,
    runtime_run_id: int,
    runtime_attempt: int,
) -> bytes:
    """Compose the signed owner request with independent live registry evidence."""
    request = verify_delivery(
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
    expected = manifest_bytes(identity.handoff, directory)
    if hashlib.sha256(expected).hexdigest() != identity.manifest_sha256:
        raise ValueError("worker packages changed before registry verification")
    assets = json.loads(expected)["assets"]
    version = _version(identity.handoff)
    _check_inventory(registry, version, assets)
    _check_provenance(registry, verify, version, directory, assets)
    _check_inventory(registry, version, assets)
    metadata = discover_request(client, identity)
    if metadata["digest"][7:] != request["ownerRequestArchiveSha256"]:
        raise ValueError("owner request changed during registry verification")
    _check_live(client, identity)
    _read_archive(archive, metadata)
    if manifest_bytes(identity.handoff, directory) != expected:
        raise ValueError("worker packages changed during registry verification")
    record = json.loads(dispatch_bytes(identity))
    record.update(
        kind="python-worker-registry-receipt",
        registry=_REGISTRY,
        package=_PACKAGE,
        version=version,
        ownerRequestArtifactId=artifact_id,
        ownerRequestArchiveSha256=request["ownerRequestArchiveSha256"],
        assets=assets,
        registryDigestInventoryVerified=True,
        registryPublisherProvenanceVerified=True,
        registryPublicationRunVerified=False,
        registryReceiptVerified=False,
        exclusiveWriterVerified=False,
        producerArtifactVerified=False,
        protectedTagVerified=False,
        draftReleaseVerified=False,
    )
    data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ValueError("registry receipt exceeds size limit")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-event", action="store_true", required=True)
    parser.add_argument("--artifact-id", type=positive_id, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        event = os.environ.get("GITHUB_EVENT_PATH")
        if not event:
            raise ValueError("missing Actions dispatch event path")
        runner_temp = os.environ.get("RUNNER_TEMP")
        handoff, pin = read_event_inputs(
            Path(event), runner_temp=Path(runner_temp) if runner_temp else None
        )
        identity = _runtime(handoff, pin)
        data = prepare_registry_receipt(
            DeliveryGitHubCLI(),
            GitHubAttestationCLI(),
            PyPIReadClient(),
            verify_registry_provenance,
            identity=identity,
            artifact_id=args.artifact_id,
            archive=args.archive,
            directory=args.directory,
            runtime_ref=os.environ["GITHUB_REF"],
            runtime_sha=os.environ["GITHUB_SHA"],
            runtime_run_id=identity.worker_run_id,
            runtime_attempt=identity.worker_attempt,
        )
    except (ValueError, OSError, urllib3.exceptions.HTTPError) as exc:
        parser.exit(2, f"Python registry receipt: FAIL: {exc}\n")
    print(data.decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
