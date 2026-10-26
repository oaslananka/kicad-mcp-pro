"""Protocol Schemas requires independent SLSA and exact reusable signer identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_signed_draft_asset import _REUSABLE_SIGNERS, verify_signed_asset
from tests.unit.test_signed_draft_asset import SHA, StubVerifier
from tests.unit.test_signed_draft_asset_run_invocation import ATTEMPT, RUN_ID, URI

TAG = "protocol-schemas-v4.5.0"
FILENAME = "oaslananka-kicad-protocol-schemas-4.5.0.tgz"


def _case(tmp_path: Path) -> tuple[Path, StubVerifier]:
    archive = tmp_path / FILENAME
    archive.write_bytes(b"schema package from reusable producer")
    verifier = StubVerifier(archive)
    proof = verifier.output[0]["verificationResult"]
    proof["statement"]["predicate"] = {"runDetails": {"metadata": {"invocationId": URI}}}
    proof["signature"] = {"certificate": {"runInvocationURI": URI}}
    return archive, verifier


def _verify(path: Path, verifier: StubVerifier, **extra: object) -> dict:
    params = {
        "package": path,
        "tag": TAG,
        "source_commit": SHA,
        "kind": "schemas",
        "source_ref": "refs/heads/main",
        "producer_run_id": RUN_ID,
        "producer_run_attempt": ATTEMPT,
        "signer_profile": "reusable",
    }
    params.update(extra)
    return verify_signed_asset(verifier, **params)


def test_schema_signed_slsa_tarball_acceptance_is_read_only(tmp_path: Path) -> None:
    path, verifier = _case(tmp_path)
    report = _verify(path, verifier)
    assert report["signerWorkflow"] == _REUSABLE_SIGNERS["schemas"]
    assert report["signerProfile"] == "reusable"
    assert report["signedAttestationVerified"] is True
    assert report["producerRunInvocationVerified"] is True
    assert report["producerJobBindingVerified"] is False
    assert report["registryReceiptVerified"] is False
    assert report["publicationAuthorized"] is False
    assert verifier.calls[0]["signer"] == ".github/workflows/prepare-protocol-schemas.yml"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"tag": "mcp-server-v4.5.0"}, "unapproved signed package identity"),
        ({"tag": "protocol-schemas-v4.5.0-rc1"}, "unapproved signed package identity"),
        ({"tag": "protocol-schemas-v../4.5.0"}, "unapproved signed package identity"),
        ({"signer_profile": "legacy"}, "no approved legacy signer"),
        ({"signer_profile": "unknown"}, "unapproved signed workflow profile"),
        ({"source_ref": "refs/tags/protocol-schemas-v4.5.0"}, "signed refs/heads/main"),
        ({"source_ref": "refs/heads/foreign"}, "signed package source ref"),
        ({"producer_run_id": None, "producer_run_attempt": None}, "exact producer run"),
        ({"producer_run_id": 0}, "invalid producer run"),
        ({"producer_run_attempt": ATTEMPT + 1}, "signed SLSA invocation"),
    ],
)
def test_schema_identity_rejections(tmp_path: Path, changes: dict, reason: str) -> None:
    path, verifier = _case(tmp_path)
    with pytest.raises(ValueError, match=reason):
        _verify(path, verifier, **changes)
    if (
        "invalid" in reason
        or "unapproved" in reason
        or "no approved" in reason
        or "exact producer" in reason
        or "signed refs/" in reason
        or "source ref" in reason
    ):
        assert verifier.calls == []


def test_schema_requires_slsa_not_only_cyclonedx_sbom(tmp_path: Path) -> None:
    path, verifier = _case(tmp_path)
    verifier.output[0]["verificationResult"]["statement"]["predicateType"] = (
        "https://cyclonedx.org/bom/v1"
    )
    with pytest.raises(ValueError, match="unexpected signed provenance predicate"):
        _verify(path, verifier)


def test_schema_rejects_other_tarball_with_same_version(tmp_path: Path) -> None:
    path, verifier = _case(tmp_path)
    other = tmp_path / "unapproved-4.5.0.tgz"
    other.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="unapproved"):
        _verify(other, verifier)
    assert verifier.calls == []
