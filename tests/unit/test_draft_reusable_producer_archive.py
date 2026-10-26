"""Read-only GitHub archive identity for four reusable preparation jobs (#1179).

A complete successful caller run and a verified archive do NOT prove which job
uploaded it or that its SLSA signature is valid.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_draft_producer_archive import (
    _REUSABLE_CALLER_WORKFLOW,
    verify_archive,
)
from tests.unit.test_draft_producer_archive import _case

_ROLES = (
    "python-dist",
    "python-release-evidence",
    "mcpb-release-evidence",
    "kicad-pcm-release-evidence",
    "protocol-schemas-release-evidence",
)


def _reusable_case(tmp_path: Path, role: str = "mcpb-release-evidence"):
    # The existing read-only fixture models exact GitHub run/artifact records.
    fixture_role = role if role != "protocol-schemas-release-evidence" else "mcpb-release-evidence"
    client, args = _case(tmp_path, fixture_role)
    client.run["path"] = _REUSABLE_CALLER_WORKFLOW
    client.art["name"] = role
    args["role"] = role
    args["producer_profile"] = "reusable"
    return client, args


@pytest.mark.parametrize("role", _ROLES)
def test_exact_reusable_caller_run_archive_digest_only(tmp_path: Path, role: str) -> None:
    client, args = _reusable_case(tmp_path, role)
    report = verify_archive(client, **args)
    assert report["producerProfile"] == "reusable"
    assert report["reusableCallerWorkflowVerified"] is True
    assert report["workflowRunIdentityVerified"] is True
    assert report["artifactArchiveDigestVerified"] is True
    assert report["producerJobIdentityVerified"] is False
    assert report["signedAttestationVerified"] is False
    assert report["registryReceiptVerified"] is False
    assert report["publicationAuthorized"] is False
    assert client.artifact_reads == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", ".github/workflows/publish-python.yml"),
        ("path", ".github/workflows/prepare-python.yml"),
        ("path", ".github/workflows/draft-producer-preflight.yml@refs/heads/main"),
        ("path", ".github/workflows/publish-release.yml"),
        ("event", "workflow_call"),
        ("event", "pull_request"),
        ("head_branch", "release"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("head_sha", "b" * 40),
        ("run_attempt", 2),
    ],
)
def test_reusable_run_identity_must_match_exact_caller(
    tmp_path: Path, field: str, value: object
) -> None:
    client, args = _reusable_case(tmp_path)
    client.run[field] = value
    with pytest.raises(ValueError, match="approved completed main producer"):
        verify_archive(client, **args)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "malicious-artifact"),
        ("digest", "sha256:" + "0" * 64),
        ("expired", True),
    ],
)
def test_reusable_artifact_wrong_identity_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    client, args = _reusable_case(tmp_path)
    client.art[field] = value
    with pytest.raises(ValueError):
        verify_archive(client, **args)


def test_reusable_does_not_accept_legacy_publisher_run(tmp_path: Path) -> None:
    client, args = _case(tmp_path)
    args["producer_profile"] = "reusable"
    with pytest.raises(ValueError, match="approved completed main producer"):
        verify_archive(client, **args)


def test_legacy_cannot_accept_new_reusable_caller(tmp_path: Path) -> None:
    client, args = _reusable_case(tmp_path)
    args["producer_profile"] = "legacy"
    with pytest.raises(ValueError, match="approved completed main producer"):
        verify_archive(client, **args)


def test_schema_role_has_no_legacy_fallback(tmp_path: Path) -> None:
    client, args = _reusable_case(tmp_path, "protocol-schemas-release-evidence")
    args["producer_profile"] = "legacy"
    with pytest.raises(ValueError, match="unapproved"):
        verify_archive(client, **args)
    assert client.artifact_reads == 0


@pytest.mark.parametrize("profile", ["", "all", "legacy,reusable", None, False])
def test_unapproved_profile_rejected_before_api(tmp_path: Path, profile: object) -> None:
    client, args = _reusable_case(tmp_path)
    args["producer_profile"] = profile
    with pytest.raises(ValueError, match="unapproved producer profile"):
        verify_archive(client, **args)
    assert client.artifact_reads == 0


def test_reusable_archive_tampering_cannot_pass(tmp_path: Path) -> None:
    client, args = _reusable_case(tmp_path)
    args["downloaded_zip"].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="ZIP differs"):
        verify_archive(client, **args)
