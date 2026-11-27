"""Nonpublishing Python worker handoff contract; cryptography is mocked offline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts.check_signed_python_handoff import (
    HandoffIdentity,
    main,
    manifest_bytes,
    verify_manifest,
)
from tests.unit.test_signed_draft_asset import StubVerifier

IDENTITY = HandoffIdentity("mcp-server-v4.23.0", "a" * 40, 42, 101, 1, 102, 1, 103)
URI = "https://github.com/oaslananka/kicad-mcp-pro/actions/runs/101/attempts/1"


@pytest.fixture
def handoff(tmp_path: Path) -> tuple[StubVerifier, dict[str, Any]]:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "kicad_mcp_pro-4.23.0-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "kicad_mcp_pro-4.23.0.tar.gz").write_bytes(b"sdist")
    manifest = tmp_path / "python-worker-manifest.json"
    manifest.write_bytes(manifest_bytes(IDENTITY, dist))
    verifier = StubVerifier(manifest)
    proof = verifier.output[0]["verificationResult"]
    proof["statement"]["predicate"] = {"runDetails": {"metadata": {"invocationId": URI}}}
    proof["signature"] = {"certificate": {"runInvocationURI": URI}}
    args = {
        "identity": IDENTITY,
        "directory": dist,
        "manifest": manifest,
        "manifest_sha256": verifier.digest,
    }
    return verifier, args


def test_exact_signed_request_never_authorizes_publication(handoff) -> None:
    verifier, args = handoff
    result = verify_manifest(verifier, **args)
    assert result["signedOwnerManifestVerified"] is True
    assert result["ownerRunInvocationVerified"] is True
    assert result["packageBytesVerified"] is True
    assert result["publicationAuthorized"] is False
    assert result["activeOwnerVerified"] is False
    assert result["protectedTagVerified"] is False
    assert result["producerArtifactVerified"] is False
    assert result["registryReceiptVerified"] is False
    assert result["exclusiveWriterVerified"] is False
    assert result["workerRunVerified"] is False
    assert verifier.calls == [
        {
            "path": args["manifest"].resolve(),
            "repo": "oaslananka/kicad-mcp-pro",
            "sha": IDENTITY.source_commit,
            "signer": ".github/workflows/publish-release.yml",
            "source_ref": "refs/heads/main",
        }
    ]
    payload = json.loads(args["manifest"].read_bytes())
    assert payload["workerWorkflow"] == ".github/workflows/publish-python.yml"
    assert payload["workerSourceRef"] == "refs/tags/mcp-server-v4.23.0"
    assert payload["releaseId"] == 42
    assert payload["producerArtifactId"] == 103
    assert len(payload["assets"]) == 2
    assert "registryReceipt" not in payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release_id", 43),
        ("owner_run_id", 104),
        ("owner_attempt", 2),
        ("producer_run_id", 105),
        ("producer_attempt", 2),
        ("producer_artifact_id", 106),
        ("source_commit", "b" * 40),
    ],
)
def test_caller_identity_mismatch_rejected_before_crypto(handoff, field, value) -> None:
    verifier, args = handoff
    args["identity"] = replace(IDENTITY, **{field: value})
    with pytest.raises(ValueError, match="manifest"):
        verify_manifest(verifier, **args)
    assert not verifier.calls


@pytest.mark.parametrize("change", ["mutated", "missing", "extra"])
def test_package_inventory_mismatch_fails_closed(handoff, change) -> None:
    verifier, args = handoff
    dist = args["directory"]
    wheel = dist / "kicad_mcp_pro-4.23.0-py3-none-any.whl"
    if change == "mutated":
        wheel.write_bytes(b"wrong")
    elif change == "missing":
        wheel.unlink()
    else:
        (dist / "extra.whl").write_bytes(b"extra")
    with pytest.raises(ValueError):
        verify_manifest(verifier, **args)
    assert not verifier.calls


@pytest.mark.parametrize("field", ["release_id", "owner_run_id", "producer_artifact_id"])
def test_non_integer_ids_rejected(handoff, field) -> None:
    verifier, args = handoff
    args["identity"] = replace(IDENTITY, **{field: True})
    with pytest.raises(ValueError, match="identity"):
        verify_manifest(verifier, **args)
    assert not verifier.calls


@pytest.mark.parametrize("change", ["digest", "subject", "certificate", "predicate", "empty"])
def test_wrong_signed_evidence_fails_closed(handoff, change) -> None:
    verifier, args = handoff
    proof = verifier.output[0]["verificationResult"]
    if change == "digest":
        proof["statement"]["subject"][0]["digest"]["sha256"] = "0" * 64
    elif change == "subject":
        proof["statement"]["subject"][0]["name"] = "other.json"
    elif change == "certificate":
        proof["signature"]["certificate"]["runInvocationURI"] = URI + "2"
    elif change == "predicate":
        proof["statement"]["predicate"]["runDetails"]["metadata"]["invocationId"] = URI + "2"
    else:
        verifier.output = []
    with pytest.raises(ValueError, match="signed|attestation"):
        verify_manifest(verifier, **args)


def test_wrong_external_digest_rejected_before_crypto(handoff) -> None:
    verifier, args = handoff
    args["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="manifest"):
        verify_manifest(verifier, **args)
    assert not verifier.calls


def test_noncanonical_manifest_rejected_even_if_hash_is_updated(handoff) -> None:
    verifier, args = handoff
    manifest = args["manifest"]
    manifest.write_bytes(manifest.read_bytes() + b" ")
    args["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="manifest"):
        verify_manifest(verifier, **args)
    assert not verifier.calls


def test_package_change_during_verification_rejected(handoff, monkeypatch) -> None:
    verifier, args = handoff
    original = verifier.verify

    def change(
        *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        (args["directory"] / "kicad_mcp_pro-4.23.0.tar.gz").write_bytes(b"changed")
        return result

    monkeypatch.setattr(verifier, "verify", change)
    with pytest.raises(ValueError, match="changed"):
        verify_manifest(verifier, **args)


@pytest.mark.parametrize("field", ["manifest", "directory"])
def test_linked_inputs_rejected(handoff, tmp_path: Path, field: str) -> None:
    verifier, args = handoff
    original = args[field]
    target = tmp_path / "moved"
    original.rename(target)
    try:
        original.symlink_to(target, target_is_directory=field == "directory")
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="symlink|linked"):
        verify_manifest(verifier, **args)
    assert not verifier.calls


def test_wrong_tag_family_rejected_before_crypto(handoff) -> None:
    verifier, args = handoff
    args["identity"] = replace(IDENTITY, tag="mcp-npm-v4.23.0")
    with pytest.raises(ValueError, match="identity"):
        verify_manifest(verifier, **args)
    assert not verifier.calls


def test_wrong_signed_workflow_subject_cannot_be_accepted(handoff) -> None:
    verifier, args = handoff
    verifier.output[0]["verificationResult"]["statement"]["predicateType"] = "other"
    with pytest.raises(ValueError, match="predicate"):
        verify_manifest(verifier, **args)


def test_manifest_change_during_verification_rejected(handoff, monkeypatch) -> None:
    verifier, args = handoff
    original = verifier.verify

    def change(
        *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        path.write_bytes(b"changed manifest")
        return result

    monkeypatch.setattr(verifier, "verify", change)
    with pytest.raises(ValueError, match="changed"):
        verify_manifest(verifier, **args)


def test_cli_generate_and_verify(handoff, monkeypatch, capsys) -> None:
    verifier, args = handoff
    common = [
        "--directory",
        str(args["directory"]),
        "--tag",
        IDENTITY.tag,
        "--source-commit",
        IDENTITY.source_commit,
        "--release-id",
        "42",
        "--owner-run-id",
        "101",
        "--owner-attempt",
        "1",
        "--producer-run-id",
        "102",
        "--producer-attempt",
        "1",
        "--producer-artifact-id",
        "103",
    ]
    monkeypatch.setattr("sys.argv", ["handoff", "generate", *common])
    assert main() == 0
    assert capsys.readouterr().out.encode() == args["manifest"].read_bytes()
    monkeypatch.setattr(
        "scripts.check_signed_python_handoff.GitHubAttestationCLI", lambda: verifier
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "handoff",
            "verify",
            *common,
            "--manifest",
            str(args["manifest"]),
            "--manifest-sha256",
            args["manifest_sha256"],
        ],
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["publicationAuthorized"] is False


def test_verify_cli_requires_independent_pin(handoff, monkeypatch) -> None:
    verifier, args = handoff
    monkeypatch.setattr(
        "sys.argv",
        [
            "handoff",
            "verify",
            "--directory",
            str(args["directory"]),
            "--tag",
            IDENTITY.tag,
            "--source-commit",
            IDENTITY.source_commit,
            "--release-id",
            "42",
            "--owner-run-id",
            "101",
            "--owner-attempt",
            "1",
            "--producer-run-id",
            "102",
            "--producer-attempt",
            "1",
            "--producer-artifact-id",
            "103",
            "--manifest",
            str(args["manifest"]),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not verifier.calls


def _record_args(args):
    return {key: value for key, value in args.items() if key != "directory"}


def test_manifest_record_verification_does_not_claim_package_bytes(handoff) -> None:
    from scripts import check_signed_python_handoff as owner

    verifier, args = handoff
    report = owner.verify_manifest_record(verifier, **_record_args(args))
    assert report["signedOwnerManifestVerified"] is True
    assert report["packageBytesVerified"] is False
    assert report["publicationAuthorized"] is False
    assert len(verifier.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        "identity",
        "extra",
        "duplicate",
        "name",
        "size",
        "bool",
        "digest",
        "order",
        "authorization",
        "noncanonical",
        "oversize",
    ],
)
def test_manifest_record_rejects_malformed_even_with_matching_pin(handoff, change) -> None:
    from scripts import check_signed_python_handoff as owner

    verifier, args = handoff
    manifest = args["manifest"]
    record = json.loads(manifest.read_bytes())
    if change == "identity":
        record["producerArtifactId"] += 1
    elif change == "extra":
        record["extra"] = True
    elif change == "duplicate":
        record["assets"][1] = record["assets"][0]
    elif change == "name":
        record["assets"][0]["name"] = "../other.whl"
    elif change == "size":
        record["assets"][0]["size"] = 0
    elif change == "bool":
        record["assets"][0]["size"] = True
    elif change == "digest":
        record["assets"][0]["sha256"] = "A" * 64
    elif change == "order":
        record["assets"].reverse()
    elif change == "authorization":
        record["publicationAuthorized"] = True
    data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    if change == "noncanonical":
        data += b" "
    elif change == "oversize":
        data += b" " * 16384
    manifest.write_bytes(data)
    args["manifest_sha256"] = hashlib.sha256(data).hexdigest()
    options = _record_args(args)
    with pytest.raises(ValueError):
        owner.verify_manifest_record(verifier, **options)
    assert not verifier.calls
