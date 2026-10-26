"""Verify isolated reusable attestation identity without enabling publication (#1179)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_signed_draft_asset import (
    _REUSABLE_SIGNERS,
    _SIGNERS,
    verify_signed_asset,
)
from tests.unit.test_signed_draft_asset import SHA, TAG, StubVerifier
from tests.unit.test_signed_draft_asset_run_invocation import ATTEMPT, RUN_ID, URI

_PACKAGES = (
    ("python", "kicad_mcp_pro-4.5.0-py3-none-any.whl"),
    ("python", "kicad_mcp_pro-4.5.0.tar.gz"),
    ("mcpb", "kicad-mcp-pro-4.5.0.mcpb"),
    ("pcm", "kicad-mcp-pro-pcm-4.5.0.zip"),
)


def _signed_fixture(tmp_path: Path, name: str) -> tuple[Path, StubVerifier]:
    path = tmp_path / name
    path.write_bytes(b"artifact from exact reusable producer")
    verifier = StubVerifier(path)
    result = verifier.output[0]["verificationResult"]
    result["statement"]["predicate"] = {"runDetails": {"metadata": {"invocationId": URI}}}
    result["signature"] = {"certificate": {"runInvocationURI": URI}}
    return path, verifier


def _verify(package: Path, verifier: StubVerifier, kind: str, **changes: object) -> dict:
    args = dict(
        package=package,
        tag=TAG,
        source_commit=SHA,
        kind=kind,
        source_ref="refs/heads/main",
        producer_run_id=RUN_ID,
        producer_run_attempt=ATTEMPT,
        signer_profile="reusable",
    )
    args.update(changes)
    return verify_signed_asset(verifier, **args)


@pytest.mark.parametrize(("kind", "name"), _PACKAGES)
def test_exact_reusable_signer_is_pinned_per_family(tmp_path: Path, kind: str, name: str) -> None:
    path, verifier = _signed_fixture(tmp_path, name)
    result = _verify(path, verifier, kind)
    assert result["signedAttestationVerified"] is True
    assert result["producerRunInvocationVerified"] is True
    assert result["signerProfile"] == "reusable"
    assert result["signerWorkflow"] == _REUSABLE_SIGNERS[kind]
    assert verifier.calls[0]["signer"] == _REUSABLE_SIGNERS[kind]
    assert verifier.calls[0]["signer"] != _SIGNERS[kind]
    assert result["producerJobBindingVerified"] is False
    assert result["registryReceiptVerified"] is False
    assert result["publicationAuthorized"] is False


@pytest.mark.parametrize(("kind", "name"), _PACKAGES)
def test_legacy_profile_default_remains_isolated(tmp_path: Path, kind: str, name: str) -> None:
    path, verifier = _signed_fixture(tmp_path, name)
    result = verify_signed_asset(verifier, package=path, tag=TAG, source_commit=SHA, kind=kind)
    assert verifier.calls[0]["signer"] == _SIGNERS[kind]
    assert result["signerProfile"] == "legacy"
    assert result["producerRunInvocationVerified"] is False
    assert result["publicationAuthorized"] is False


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"signer_profile": "published"}, "unapproved signed workflow profile"),
        ({"signer_profile": "legacy-priority"}, "unapproved signed workflow profile"),
        ({"source_ref": "refs/tags/mcp-server-v4.5.0"}, "signed refs/heads/main"),
        ({"source_ref": "refs/heads/release"}, "source ref"),
        ({"producer_run_id": None, "producer_run_attempt": None}, "exact producer run"),
        ({"producer_run_id": RUN_ID, "producer_run_attempt": None}, "provided together"),
        ({"producer_run_id": 0}, "invalid producer run"),
        ({"producer_run_attempt": 0}, "invalid producer run"),
    ],
)
def test_unapproved_reusable_identity_rejected_before_crypto(
    tmp_path: Path, changes: dict, reason: str
) -> None:
    path, verifier = _signed_fixture(tmp_path, "kicad-mcp-pro-4.5.0.mcpb")
    with pytest.raises(ValueError, match=reason):
        _verify(path, verifier, "mcpb", **changes)
    assert verifier.calls == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"producer_run_id": RUN_ID + 1}, "signed SLSA invocation"),
        ({"producer_run_attempt": ATTEMPT + 1}, "signed SLSA invocation"),
    ],
)
def test_other_reusable_run_cannot_claim_same_signed_artifact(
    tmp_path: Path, changes: dict, reason: str
) -> None:
    path, verifier = _signed_fixture(tmp_path, "kicad-mcp-pro-4.5.0.mcpb")
    with pytest.raises(ValueError, match=reason):
        _verify(path, verifier, "mcpb", **changes)
    assert verifier.calls[0]["signer"] == _REUSABLE_SIGNERS["mcpb"]
