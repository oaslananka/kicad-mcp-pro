"""Rehearsal trust is isolated from production publishing authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from scripts.check_signed_python_handoff import HandoffIdentity, verify_manifest
from scripts.rehearse_signed_python_handoff import generate, verify
from tests.unit.test_signed_draft_asset import StubVerifier

SHA = "a" * 40
RUN = 101
ATTEMPT = 1
SIGNER = ".github/workflows/signed-python-handoff-rehearsal.yml"
URI = f"https://github.com/oaslananka/kicad-mcp-pro/actions/runs/{RUN}/attempts/{ATTEMPT}"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def signed_fixture(tmp_path: Path) -> tuple[Path, str, StubVerifier]:
    bundle = tmp_path / "bundle"
    pin = generate(bundle, SHA, RUN, ATTEMPT)
    manifest = bundle / "python-worker-rehearsal.json"
    verifier = StubVerifier(manifest)
    proof = verifier.output[0]["verificationResult"]
    proof["statement"]["predicate"] = {"runDetails": {"metadata": {"invocationId": URI}}}
    proof["signature"] = {"certificate": {"runInvocationURI": URI}}
    return bundle, pin, verifier


def test_rehearsal_exact_bytes_and_signer(signed_fixture) -> None:
    bundle, pin, verifier = signed_fixture
    result = verify(verifier, bundle, SHA, RUN, ATTEMPT, pin)
    assert result["rehearsalSignatureVerified"] is True
    assert result["publicationAuthorized"] is False
    assert result["signedOwnerManifestVerified"] is False
    assert result["workerRunVerified"] is False
    assert result["registryReceiptVerified"] is False
    assert verifier.calls[0]["signer"] == SIGNER
    assert verifier.calls[0]["source_ref"] == "refs/heads/main"
    assert verifier.calls[0]["sha"] == SHA
    payload = json.loads((bundle / "python-worker-rehearsal.json").read_bytes())
    assert payload["rehearsal"] is True
    assert payload["syntheticPackages"] is True
    assert payload["request"]["publicationAuthorized"] is False


@pytest.mark.parametrize(
    "mutation", ["manifest", "package", "extra", "pin", "attempt", "certificate"]
)
def test_rehearsal_rejects_conflicting_evidence(signed_fixture, mutation) -> None:
    bundle, pin, verifier = signed_fixture
    attempt = ATTEMPT
    if mutation == "manifest":
        (bundle / "python-worker-rehearsal.json").write_bytes(b"wrong")
    elif mutation == "package":
        (bundle / "dist/kicad_mcp_pro-0.0.0.tar.gz").write_bytes(b"wrong")
    elif mutation == "extra":
        (bundle / "dist/unexpected").write_bytes(b"extra")
    elif mutation == "pin":
        pin = "0" * 64
    elif mutation == "attempt":
        attempt = 2
    else:
        verifier.output[0]["verificationResult"]["signature"]["certificate"]["runInvocationURI"] = (
            "wrong"
        )
    with pytest.raises(ValueError):
        verify(verifier, bundle, SHA, RUN, attempt, pin)


def test_rehearsal_envelope_cannot_pass_production_verifier(signed_fixture) -> None:
    bundle, _, verifier = signed_fixture
    manifest = bundle / "python-worker-manifest.json"
    manifest.write_bytes((bundle / "python-worker-rehearsal.json").read_bytes())
    pin = hashlib.sha256(manifest.read_bytes()).hexdigest()
    identity = HandoffIdentity("mcp-server-v0.0.0", SHA, 1, RUN, ATTEMPT, RUN, ATTEMPT, 1)
    dist = bundle / "dist"
    with pytest.raises(ValueError, match="manifest"):
        verify_manifest(
            verifier, identity=identity, directory=dist, manifest=manifest, manifest_sha256=pin
        )
    assert not verifier.calls


def test_workflow_separates_signing_and_read_only_verification() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/signed-python-handoff-rehearsal.yml").read_text()
    )
    assert workflow[True] == {"workflow_dispatch": None}
    assert workflow["permissions"] == {"contents": "read"}
    sign = workflow["jobs"]["sign"]
    check = workflow["jobs"]["verify"]
    assert sign["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    assert check["permissions"] == {"contents": "read", "attestations": "read"}
    assert check["needs"] == "sign"
    assert "github.actor_id == '285490571'" in sign["if"]
    assert "github.triggering_actor == 'oaslananka'" in sign["if"]
    assert "refs/heads/main" in sign["if"]
    for job in (sign, check):
        assert "environment" not in job
        assert job["timeout-minutes"] <= 5
        assert any(
            step.get("with", {}).get("persist-credentials") is False for step in job["steps"]
        )
    download = next(
        step
        for step in check["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    )
    assert download["with"]["artifact-ids"] == "${{ needs.sign.outputs.artifact-id }}"
    policy = json.loads((ROOT / ".github/actions-policy.json").read_text())
    assert policy["workflow_write_permissions"]["signed-python-handoff-rehearsal.yml"] == {
        "sign": ["artifact-metadata", "attestations", "id-token"]
    }


def test_invalid_identity_does_not_create_fixture(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    with pytest.raises(ValueError, match="identity"):
        generate(bundle, "wrong", RUN, ATTEMPT)
    assert not bundle.exists()


def test_rehearsal_manifest_change_during_signature_check(signed_fixture, monkeypatch) -> None:
    bundle, pin, verifier = signed_fixture
    original = verifier.verify

    def change(
        *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, object]]:
        result = original(path=path, repo=repo, sha=sha, signer=signer, source_ref=source_ref)
        path.write_bytes(b"changed")
        return result

    monkeypatch.setattr(verifier, "verify", change)
    with pytest.raises(ValueError, match="changed"):
        verify(verifier, bundle, SHA, RUN, ATTEMPT, pin)
