"""Independent safe-ZIP extraction of reusable caller artifacts (#1179)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.extract_draft_producer_zip import verify_and_extract
from tests.unit.test_extract_draft_producer_zip import (
    SHA,
    TAG,
    FixtureClient,
    _files,
    _zip,
)

ROLE = "protocol-schemas-release-evidence"
SCHEMA_TAG = "protocol-schemas-v2.0.0"
_SCHEMA_MEMBERS = [
    ("oaslananka-kicad-protocol-schemas-2.0.0.tgz", b"archive"),
    (
        "SHA256SUMS.txt",
        hashlib.sha256(b"archive").hexdigest().encode()
        + b"  oaslananka-kicad-protocol-schemas-2.0.0.tgz\n",
    ),
    ("sbom.cdx.json", b"{}"),
]


def _case(tmp_path: Path, role: str, tag: str) -> tuple[FixtureClient, dict]:
    if role == ROLE:
        files = list(_SCHEMA_MEMBERS)
        source_role = "mcpb-release-evidence"
    else:
        files = _files(role)
        source_role = role
    zipped = _zip(files)
    client = FixtureClient(source_role, zipped)
    client.run["path"] = ".github/workflows/draft-producer-preflight.yml"
    client.art["name"] = role
    local = tmp_path / "caller.zip"
    local.write_bytes(zipped)
    return client, dict(
        repo="oaslananka/kicad-mcp-pro",
        role=role,
        tag=tag,
        run_id=991122,
        run_attempt=1,
        artifact_id=778899,
        head_sha=SHA,
        downloaded_zip=local,
        output=tmp_path / "extracted",
        producer_profile="reusable",
    )


@pytest.mark.parametrize(
    ("role", "tag", "count"),
    [
        ("python-dist", TAG, 2),
        ("python-release-evidence", TAG, 3),
        ("mcpb-release-evidence", TAG, 3),
        ("kicad-pcm-release-evidence", TAG, 3),
        (ROLE, SCHEMA_TAG, 3),
    ],
)
def test_reusable_archive_exact_role_members_only(
    tmp_path: Path, role: str, tag: str, count: int
) -> None:
    client, args = _case(tmp_path, role, tag)
    verified = verify_and_extract(client, **args)
    assert verified["extractedCount"] == count
    assert verified["zipMemberSafetyVerified"] is True
    assert verified["producerProfile"] == "reusable"
    assert verified["publicationAuthorized"] is False
    assert verified["signedAttestationVerified"] is False
    assert len(list(args["output"].iterdir())) == count


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("profile_legacy", "unapproved package family"),
        ("legacy_workflow", "approved completed main producer"),
        ("wrong_tag", "unapproved protocol-schemas tag"),
        ("wrong_role", "unapproved package family"),
        ("wrong_subject", "unexpected, duplicate or missing ZIP"),
        ("wrong_digest", "ZIP differs"),
        ("wrong_inner_checksum", "tarball checksum"),
        ("checksum_wrong_subject", "checksum subject"),
    ],
)
def test_schema_caller_untrusted_inputs_never_extract(
    tmp_path: Path, change: str, reason: str
) -> None:
    client, args = _case(tmp_path, ROLE, SCHEMA_TAG)
    if change == "profile_legacy":
        args["producer_profile"] = "legacy"
    elif change == "legacy_workflow":
        client.run["path"] = ".github/workflows/publish-protocol-schemas.yml"
    elif change == "wrong_tag":
        args["tag"] = "mcp-server-v2.0.0"
    elif change == "wrong_role":
        args["role"] = "npm-release-evidence"
    elif change == "wrong_subject":
        original = _zip(_SCHEMA_MEMBERS[:-1] + [("other.exe", b"x")])
        client.art["digest"] = "sha256:" + hashlib.sha256(original).hexdigest()
        args["downloaded_zip"].write_bytes(original)
    elif change == "wrong_digest":
        client.art["digest"] = "sha256:" + "0" * 64
    elif change in {"wrong_inner_checksum", "checksum_wrong_subject"}:
        checksum = (
            ("0" * 64 + "  oaslananka-kicad-protocol-schemas-2.0.0.tgz\n").encode()
            if change == "wrong_inner_checksum"
            else (hashlib.sha256(b"archive").hexdigest() + "  other.tgz\n").encode()
        )
        damaged = _zip([_SCHEMA_MEMBERS[0], ("SHA256SUMS.txt", checksum), _SCHEMA_MEMBERS[2]])
        client.art["digest"] = "sha256:" + hashlib.sha256(damaged).hexdigest()
        args["downloaded_zip"].write_bytes(damaged)
    with pytest.raises(ValueError, match=reason):
        verify_and_extract(client, **args)
    assert not args["output"].exists()


def test_schema_archive_never_passes_legacy_profile(tmp_path: Path) -> None:
    client, args = _case(tmp_path, ROLE, SCHEMA_TAG)
    args.pop("producer_profile")
    with pytest.raises(ValueError, match="unapproved package family"):
        verify_and_extract(client, **args)
    assert not args["output"].exists()
