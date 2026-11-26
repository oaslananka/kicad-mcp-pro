"""Post-dispatch proof must bind the exact child, not just an Actions bot."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts.check_signed_python_dispatch_binding import (
    DispatchIdentity,
    dispatch_bytes,
    verify_dispatch_binding,
    verify_worker_request,
)
from scripts.check_signed_python_handoff import manifest_bytes
from tests.unit.test_draft_release_owner import FakeOwnerClient
from tests.unit.test_signed_draft_asset import StubVerifier
from tests.unit.test_signed_python_handoff import IDENTITY

REPO = "oaslananka/kicad-mcp-pro"
RUN = 901
PIN = "b" * 64
OWNER_URI = f"https://github.com/{REPO}/actions/runs/{IDENTITY.owner_run_id}/attempts/{IDENTITY.owner_attempt}"
DISPATCH = DispatchIdentity(IDENTITY, PIN, RUN, 1)
REF = f"refs/tags/{IDENTITY.tag}"


class ReadClient:
    """Expose only run and tag reads; a worker cannot read full rulesets/drafts."""

    def __init__(self) -> None:
        self.owner = FakeOwnerClient().run_data
        self.owner.update(
            id=IDENTITY.owner_run_id,
            url=f"https://api.github.com/repos/{REPO}/actions/runs/{IDENTITY.owner_run_id}",
            run_attempt=IDENTITY.owner_attempt,
            head_sha=IDENTITY.source_commit,
        )
        self.child = copy.deepcopy(self.owner)
        self.child.update(
            id=RUN,
            url=f"https://api.github.com/repos/{REPO}/actions/runs/{RUN}",
            actor={"login": "github-actions[bot]", "id": 41898282},
            triggering_actor={"login": "github-actions[bot]", "id": 41898282},
            path=".github/workflows/publish-python.yml",
            head_branch=IDENTITY.tag,
            run_attempt=1,
        )
        self.tag_sha = IDENTITY.source_commit
        self.reads: list[int] = []
        self.tag_reads = 0

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        assert repo == REPO
        self.reads.append(run_id)
        if run_id == IDENTITY.owner_run_id:
            return copy.deepcopy(self.owner)
        assert run_id == RUN
        return copy.deepcopy(self.child)

    def tag_commit(self, repo: str, tag: str) -> str:
        assert repo == REPO
        assert tag == IDENTITY.tag
        self.tag_reads += 1
        return self.tag_sha


@pytest.fixture
def binding(tmp_path: Path) -> tuple[ReadClient, StubVerifier, dict[str, Any]]:
    path = tmp_path / "python-worker-dispatch.json"
    path.write_bytes(dispatch_bytes(DISPATCH))
    verifier = StubVerifier(path)
    proof = verifier.output[0]["verificationResult"]
    proof["statement"]["predicate"] = {"runDetails": {"metadata": {"invocationId": OWNER_URI}}}
    proof["signature"] = {"certificate": {"runInvocationURI": OWNER_URI}}
    return (
        ReadClient(),
        verifier,
        {
            "identity": DISPATCH,
            "binding": path,
            "runtime_ref": REF,
            "runtime_sha": IDENTITY.source_commit,
            "runtime_run_id": RUN,
            "runtime_attempt": 1,
        },
    )


def test_signed_exact_child_binding_is_read_only(binding) -> None:
    client, verifier, args = binding
    result = verify_dispatch_binding(client, verifier, **args)
    assert result["signedDispatchBindingVerified"] is True
    assert result["activeOwnerRunVerified"] is True
    assert result["workerRunVerified"] is True
    assert result["tagSourceVerified"] is True
    assert result["manifestSha256"] == PIN
    assert result["workerRunId"] == RUN
    for field in (
        "ownerDispatchCausalityVerified",
        "protectedTagVerified",
        "draftReleaseVerified",
        "signedOwnerManifestVerified",
        "packageBytesVerified",
        "registryReceiptVerified",
        "exclusiveWriterVerified",
        "publicationAuthorized",
    ):
        assert result[field] is False
    assert client.reads == [IDENTITY.owner_run_id, RUN, IDENTITY.owner_run_id, RUN]
    assert client.tag_reads == 2
    assert verifier.calls[0]["signer"] == ".github/workflows/publish-release.yml"
    assert verifier.calls[0]["source_ref"] == "refs/heads/main"
    payload = json.loads(args["binding"].read_bytes())
    assert payload["workerRunId"] == RUN
    assert payload["manifestSha256"] == PIN
    assert payload["workerSourceRef"] == REF
    assert payload["publicationAuthorized"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runtime_ref", "refs/heads/mcp-server-v4.23.0"),
        ("runtime_sha", "c" * 40),
        ("runtime_run_id", RUN + 1),
        ("runtime_run_id", True),
        ("runtime_attempt", 2),
        ("runtime_attempt", True),
    ],
)
def test_runtime_identity_mismatch_rejected_before_reads(binding, field, value) -> None:
    client, verifier, args = binding
    args[field] = value
    with pytest.raises(ValueError, match="runtime"):
        verify_dispatch_binding(client, verifier, **args)
    assert not client.reads
    assert not verifier.calls


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor", {"login": "github-actions[bot]", "id": 1}),
        ("triggering_actor", {"login": "oaslananka", "id": 285490571}),
        ("path", ".github/workflows/other.yml"),
        ("event", "release"),
        ("run_attempt", 2),
        ("run_attempt", True),
        ("head_branch", "main"),
        ("head_sha", "c" * 40),
        ("status", "completed"),
        ("conclusion", "success"),
        ("repository", {"full_name": REPO, "id": 1}),
        ("id", RUN + 1),
    ],
)
def test_other_bot_run_or_changed_metadata_rejected(binding, field, value) -> None:
    client, verifier, args = binding
    client.child[field] = value
    with pytest.raises(ValueError):
        verify_dispatch_binding(client, verifier, **args)
    assert not verifier.calls


@pytest.mark.parametrize(
    "change",
    ["pin", "owner-attempt", "child-id", "certificate", "predicate", "subject", "extra", "tag"],
)
def test_wrong_signed_binding_fails_closed(binding, change: str) -> None:
    client, verifier, args = binding
    proof = verifier.output[0]["verificationResult"]
    if change == "pin":
        args["identity"] = replace(DISPATCH, manifest_sha256="c" * 64)
    elif change == "owner-attempt":
        args["identity"] = replace(DISPATCH, handoff=replace(IDENTITY, owner_attempt=2))
    elif change == "child-id":
        args["identity"] = replace(DISPATCH, worker_run_id=RUN + 1)
        args["runtime_run_id"] = RUN + 1
    elif change == "certificate":
        proof["signature"]["certificate"]["runInvocationURI"] += "-wrong"
    elif change == "predicate":
        proof["statement"]["predicate"]["runDetails"]["metadata"]["invocationId"] += "-wrong"
    elif change == "subject":
        proof["statement"]["subject"][0]["name"] = "python-worker-manifest.json"
    elif change == "extra":
        args["binding"].write_bytes(args["binding"].read_bytes() + b" ")
    else:
        client.tag_sha = "c" * 40
    with pytest.raises(ValueError):
        verify_dispatch_binding(client, verifier, **args)


@pytest.mark.parametrize("change", ["owner", "child", "tag", "binding"])
def test_changes_during_signature_check_fail_closed(binding, change: str, monkeypatch) -> None:
    client, verifier, args = binding
    original = verifier.verify

    def sign(
        *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        if change == "owner":
            client.owner["status"] = "completed"
        elif change == "child":
            client.child["run_attempt"] = 2
        elif change == "tag":
            client.tag_sha = "c" * 40
        else:
            path.write_bytes(b"changed")
        return result

    monkeypatch.setattr(verifier, "verify", sign)
    with pytest.raises(ValueError):
        verify_dispatch_binding(client, verifier, **args)


@pytest.mark.parametrize("child", [True, 0, IDENTITY.owner_run_id, IDENTITY.producer_run_id])
def test_invalid_child_identity_cannot_generate_binding(child) -> None:
    identity = replace(DISPATCH, worker_run_id=child)
    with pytest.raises(ValueError, match="dispatch identity"):
        dispatch_bytes(identity)


class CombinedSignature:
    def __init__(self, dispatch: StubVerifier, manifest: StubVerifier) -> None:
        self.dispatch = dispatch
        self.manifest = manifest

    def verify(
        self, *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        verifier = self.dispatch if path.name == "python-worker-dispatch.json" else self.manifest
        return verifier.verify(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)


@pytest.fixture
def request_case(binding) -> tuple[ReadClient, CombinedSignature, dict[str, Any]]:
    client, dispatch_signature, args = binding
    root = args["binding"].parent
    dist = root / "dist"
    dist.mkdir()
    (dist / "kicad_mcp_pro-4.23.0-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "kicad_mcp_pro-4.23.0.tar.gz").write_bytes(b"sdist")
    manifest = root / "python-worker-manifest.json"
    manifest.write_bytes(manifest_bytes(IDENTITY, dist))
    pin = hashlib.sha256(manifest.read_bytes()).hexdigest()
    args["identity"] = replace(DISPATCH, manifest_sha256=pin)
    args["binding"].write_bytes(dispatch_bytes(args["identity"]))
    dispatch_signature = StubVerifier(args["binding"])
    manifest_signature = StubVerifier(manifest)
    for verifier in (dispatch_signature, manifest_signature):
        proof = verifier.output[0]["verificationResult"]
        proof["statement"]["predicate"] = {"runDetails": {"metadata": {"invocationId": OWNER_URI}}}
        proof["signature"] = {"certificate": {"runInvocationURI": OWNER_URI}}
    return (
        client,
        CombinedSignature(dispatch_signature, manifest_signature),
        {
            **args,
            "directory": dist,
            "manifest": manifest,
        },
    )


def test_worker_request_composes_both_signatures_and_exact_packages(request_case) -> None:
    client, verifier, args = request_case
    result = verify_worker_request(client, verifier, **args)
    assert result["signedDispatchBindingVerified"] is True
    assert result["signedOwnerManifestVerified"] is True
    assert result["packageBytesVerified"] is True
    assert result["workerRunVerified"] is True
    assert result["ownerDispatchCausalityVerified"] is False
    assert result["protectedTagVerified"] is False
    assert result["draftReleaseVerified"] is False
    assert result["producerArtifactVerified"] is False
    assert result["publicationAuthorized"] is False
    assert len(verifier.dispatch.calls) == len(verifier.manifest.calls) == 1


def test_different_validly_signed_manifest_cannot_replace_bound_request(request_case) -> None:
    client, verifier, args = request_case
    next(args["directory"].glob("*.whl")).write_bytes(b"different signed wheel")
    args["manifest"].write_bytes(manifest_bytes(IDENTITY, args["directory"]))
    verifier.manifest = StubVerifier(args["manifest"])
    proof = verifier.manifest.output[0]["verificationResult"]
    proof["statement"]["predicate"] = {"runDetails": {"metadata": {"invocationId": OWNER_URI}}}
    proof["signature"] = {"certificate": {"runInvocationURI": OWNER_URI}}
    with pytest.raises(ValueError, match="manifest"):
        verify_worker_request(client, verifier, **args)
    assert not verifier.manifest.calls


@pytest.mark.parametrize("change", ["owner", "child", "tag", "binding"])
def test_request_rechecks_live_identity_after_manifest_signature(
    request_case, change, monkeypatch
) -> None:
    client, verifier, args = request_case
    original = verifier.manifest.verify

    def sign(
        *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        if change == "owner":
            client.owner["status"] = "completed"
        elif change == "child":
            client.child["run_attempt"] = 2
        elif change == "tag":
            client.tag_sha = "c" * 40
        else:
            args["binding"].write_bytes(b"changed")
        return result

    monkeypatch.setattr(verifier.manifest, "verify", sign)
    with pytest.raises(ValueError):
        verify_worker_request(client, verifier, **args)
