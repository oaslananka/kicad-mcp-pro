"""Compose exact reusable run/job/ZIP/SLSA gates without granting publishing rights."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from scripts.check_draft_producer_job import _REUSABLE_JOB_NAMES
from scripts.check_signed_draft_producer_bundle import verify_producer_bundle
from tests.unit.test_extract_draft_producer_zip import _zip
from tests.unit.test_signed_draft_producer_bundle import _case

SCHEMAS_ROLE = "protocol-schemas-release-evidence"
SCHEMAS_PACKAGE = "oaslananka-kicad-protocol-schemas-2.0.0.tgz"
REUSABLE_CALLER = ".github/workflows/draft-producer-preflight.yml"
ROLES = (
    "python-dist",
    "mcpb-release-evidence",
    "kicad-pcm-release-evidence",
    SCHEMAS_ROLE,
)
SIGNERS = {
    "python-dist": ".github/workflows/prepare-python.yml",
    "mcpb-release-evidence": ".github/workflows/prepare-mcpb.yml",
    "kicad-pcm-release-evidence": ".github/workflows/prepare-kicad-pcm.yml",
    SCHEMAS_ROLE: ".github/workflows/prepare-protocol-schemas.yml",
}


def _fixture(tmp_path: Path, role: str) -> tuple[Any, Any, dict[str, Any]]:
    base_role = "mcpb-release-evidence" if role == SCHEMAS_ROLE else role
    client, verifier, args = _case(tmp_path, base_role)
    args.update(role=role, producer_profile="reusable")
    client.run["path"] = REUSABLE_CALLER
    client.art["name"] = role
    job = client.jobs["jobs"][0]
    display, job_name, attest, upload = _REUSABLE_JOB_NAMES[role]
    job["workflow_name"] = display
    job["name"] = job_name
    steps = [
        dict(name=attest, status="completed", conclusion="success", number=7),
        dict(name=upload, status="completed", conclusion="success", number=8),
    ]
    if role == SCHEMAS_ROLE:
        args["tag"] = "protocol-schemas-v2.0.0"
        package = b"verified sample tarball"
        checksums = f"{hashlib.sha256(package).hexdigest()}  {SCHEMAS_PACKAGE}\n".encode()
        data = _zip(
            [
                (SCHEMAS_PACKAGE, package),
                ("SHA256SUMS.txt", checksums),
                ("sbom.cdx.json", b'{"bomFormat":"CycloneDX"}'),
            ]
        )
        args["downloaded_zip"].write_bytes(data)
        client.art["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
        client.art["size_in_bytes"] = len(data)
        steps.insert(
            0,
            dict(
                name="Attest Protocol Schemas SLSA build provenance",
                status="completed",
                conclusion="success",
                number=6,
            ),
        )
    if role == "python-dist":
        steps.insert(
            0,
            dict(
                name="Attest Python SLSA build provenance",
                status="completed",
                conclusion="success",
                number=6,
            ),
        )
        steps.append(
            dict(name=upload + "again", status="completed", conclusion="success", number=9)
        )
    job["steps"] = steps
    return client, verifier, args


@pytest.mark.parametrize(
    ("role", "package_count"),
    [
        ("python-dist", 2),
        ("mcpb-release-evidence", 1),
        ("kicad-pcm-release-evidence", 1),
        (SCHEMAS_ROLE, 1),
    ],
)
def test_reusable_signature_and_zip_share_exact_invocation(
    tmp_path: Path, role: str, package_count: int
) -> None:
    client, verifier, args = _fixture(tmp_path, role)
    report = verify_producer_bundle(client, verifier, **args)
    assert report["producerProfile"] == "reusable"
    assert report["producerJobMetadataVerified"] is True
    assert report["artifactArchiveDigestVerified"] is True
    assert report["zipMemberSafetyVerified"] is True
    assert report["signedRunInvocationVerified"] is True
    assert len(report["signedPackages"]) == package_count
    assert {signed["signerWorkflow"] for signed in report["signedPackages"]} == {SIGNERS[role]}
    assert {x["signer"] for x in verifier.calls} == {SIGNERS[role]}
    assert {x["source_ref"] for x in verifier.calls} == {"refs/heads/main"}
    assert report["artifactProducedByThisJobVerified"] is False
    assert report["registryReceiptVerified"] is False
    assert report["exclusiveWriterVerified"] is False
    assert report["publicationAuthorized"] is False
    assert list(tmp_path.iterdir()) == [args["downloaded_zip"]]


@pytest.mark.parametrize("role", ROLES)
def test_reusable_run_must_not_pass_legacy_default(tmp_path: Path, role: str) -> None:
    client, verifier, args = _fixture(tmp_path, role)
    args.pop("producer_profile")
    with pytest.raises(ValueError, match="approved completed main producer|signed-package role"):
        verify_producer_bundle(client, verifier, **args)
    assert verifier.calls == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("wrong_run", "signed SLSA invocation"),
        ("wrong_digest", "signatures do not cover"),
        ("no_signature", "no cryptographically verified"),
        ("wrong_caller", "approved completed main producer"),
        ("wrong_job", "producer job ID"),
        ("wrong_attempt", "producer job ID|approved completed main producer"),
        ("bad_zip_digest", "ZIP differs"),
        ("bad_schema_checksum", "tarball checksum"),
        ("bad_schema_source_tag", "invalid protocol-schemas release tag"),
    ],
)
def test_mismatched_reusable_evidence_fails_closed(
    tmp_path: Path, change: str, expected: str
) -> None:
    client, verifier, args = _fixture(tmp_path, SCHEMAS_ROLE)
    if change in {"wrong_run", "wrong_digest", "no_signature"}:
        verifier.tamper = change
    elif change == "wrong_caller":
        client.run["path"] = ".github/workflows/publish-mcpb.yml"
    elif change == "wrong_job":
        client.jobs["jobs"][0]["name"] = "foreign / prepare"
    elif change == "wrong_attempt":
        client.jobs["jobs"][0]["run_attempt"] = 2
    elif change == "bad_zip_digest":
        client.art["digest"] = "sha256:" + "0" * 64
    elif change == "bad_schema_checksum":
        names = [
            (SCHEMAS_PACKAGE, b"verified sample tarball"),
            ("SHA256SUMS.txt", b"0" * 64 + b"  " + SCHEMAS_PACKAGE.encode() + b"\n"),
            ("sbom.cdx.json", b'{"bomFormat":"CycloneDX"}'),
        ]
        archive = _zip(names)
        args["downloaded_zip"].write_bytes(archive)
        client.art["digest"] = "sha256:" + hashlib.sha256(archive).hexdigest()
        client.art["size_in_bytes"] = len(archive)
    elif change == "bad_schema_source_tag":
        args["tag"] = "mcp-server-v2.0.0"
    with pytest.raises(ValueError, match=expected):
        verify_producer_bundle(client, verifier, **args)
    assert not (tmp_path / "verified").exists()


@pytest.mark.parametrize("profile", ["", "all", "legacy,reusable", False, None])
def test_unknown_profile_refused_without_any_remote_or_signature_call(
    tmp_path: Path, profile: object
) -> None:
    client, verifier, args = _fixture(tmp_path, "mcpb-release-evidence")
    args["producer_profile"] = profile
    with pytest.raises(ValueError, match="unapproved signed producer profile"):
        verify_producer_bundle(client, verifier, **args)
    assert client.jobs["total_count"] == 1
    assert verifier.calls == []


def test_wrong_schema_role_on_mcp_package_is_refused(tmp_path: Path) -> None:
    client, verifier, args = _fixture(tmp_path, "mcpb-release-evidence")
    args["role"] = SCHEMAS_ROLE
    with pytest.raises(ValueError, match="invalid protocol-schemas release tag"):
        verify_producer_bundle(client, verifier, **args)
    assert verifier.calls == []
