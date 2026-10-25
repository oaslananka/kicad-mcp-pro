"""Signature verifier is always repo/source/signer/digest-bound and fail-closed."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.check_signed_draft_asset import (
    _SIGNERS,
    GitHubAttestationCLI,
    verify_signed_asset,
)

TAG = "mcp-server-v4.5.0"
SHA = "a" * 40


class StubVerifier:
    def __init__(self, package: Path) -> None:
        self.package = package
        self.digest = hashlib.sha256(package.read_bytes()).hexdigest()
        self.calls: list[dict[str, object]] = []
        self.output: list[dict[str, Any]] = [
            {
                "verificationResult": {
                    "statement": {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [{"name": package.name, "digest": {"sha256": self.digest}}],
                    }
                }
            }
        ]

    def verify(
        self, *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "path": path,
                "repo": repo,
                "sha": sha,
                "signer": signer,
                "source_ref": source_ref,
            }
        )
        return self.output


@pytest.mark.parametrize(
    ("kind", "filename"),
    [
        ("python", "kicad_mcp_pro-4.5.0-py3-none-any.whl"),
        ("python", "kicad_mcp_pro-4.5.0.tar.gz"),
        ("mcpb", "kicad-mcp-pro-4.5.0.mcpb"),
        ("pcm", "kicad-mcp-pro-pcm-4.5.0.zip"),
    ],
)
def test_valid_verified_attestation_never_authorizes_release(
    tmp_path: Path, kind: str, filename: str
) -> None:
    file = tmp_path / filename
    file.write_bytes(b"release package byte fixture")
    verifier = StubVerifier(file)
    accepted = verify_signed_asset(verifier, package=file, tag=TAG, source_commit=SHA, kind=kind)
    assert accepted["signedAttestationVerified"] is True
    assert accepted["verifiedMatchingAttestationCount"] == 1
    assert accepted["publicationAuthorized"] is False
    assert accepted["producerJobBindingVerified"] is False
    assert accepted["signerWorkflow"] == _SIGNERS[kind]
    assert verifier.calls == [
        {
            "path": file.resolve(),
            "repo": "oaslananka/kicad-mcp-pro",
            "sha": SHA,
            "signer": _SIGNERS[kind],
            "source_ref": "refs/heads/main",
        }
    ]


@pytest.mark.parametrize(
    "change", ["no_matches", "no_results", "bad_type", "bad_subject", "bad_digest"]
)
def test_missing_or_wrong_verified_provenance_rejected(tmp_path: Path, change: str) -> None:
    file = tmp_path / "kicad-mcp-pro-4.5.0.mcpb"
    file.write_bytes(b"fixture")
    verifier = StubVerifier(file)
    statement = verifier.output[0]["verificationResult"]["statement"]
    if change == "no_matches":
        statement["subject"][0]["name"] = "unrelated.mcpb"
    elif change == "no_results":
        verifier.output = []
    elif change == "bad_type":
        statement["predicateType"] = "https://example.org/not-provenance"
    elif change == "bad_subject":
        statement["subject"] = None
    elif change == "bad_digest":
        statement["subject"][0]["digest"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        verify_signed_asset(verifier, package=file, tag=TAG, source_commit=SHA, kind="mcpb")


def test_unapproved_file_and_source_tag_fail_before_verifier_call(tmp_path: Path) -> None:
    file = tmp_path / "malicious-package.mcpb"
    file.write_bytes(b"fixture")
    verifier = StubVerifier(file)
    with pytest.raises(ValueError, match="unapproved"):
        verify_signed_asset(verifier, package=file, tag=TAG, source_commit=SHA, kind="mcpb")
    with pytest.raises(ValueError, match="unapproved"):
        verify_signed_asset(
            verifier, package=file, tag="mcp-server-v4.5.0-rc1", source_commit=SHA, kind="mcpb"
        )
    assert not verifier.calls


def test_symlink_package_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "actual.mcpb"
    real.write_bytes(b"actual data")
    linked = tmp_path / "kicad-mcp-pro-4.5.0.mcpb"
    linked.symlink_to(real)
    verifier = StubVerifier(real)
    with pytest.raises(ValueError, match="linked"):
        verify_signed_asset(verifier, package=linked, tag=TAG, source_commit=SHA, kind="mcpb")


def test_real_cli_invocation_enforces_exact_source_and_signer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "package.mcpb"
    source.write_bytes(b"test")
    calls: list[list[str]] = []

    def stub_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, json.dumps([{"verificationResult": {"statement": {}}}]), ""
        )

    monkeypatch.setattr(
        "scripts.check_signed_draft_asset.shutil.which", lambda _: "/usr/local/bin/gh"
    )
    monkeypatch.setattr("scripts.check_signed_draft_asset.subprocess.run", stub_run)
    result = GitHubAttestationCLI().verify(
        path=source,
        repo="oaslananka/kicad-mcp-pro",
        sha=SHA,
        signer=".github/workflows/publish-mcpb.yml",
        source_ref="refs/heads/main",
    )
    assert result
    command = calls[0]
    assert command[:4] == ["/usr/local/bin/gh", "attestation", "verify", str(source)]
    for flag, value in (
        ("--repo", "oaslananka/kicad-mcp-pro"),
        ("--signer-workflow", "oaslananka/kicad-mcp-pro/.github/workflows/publish-mcpb.yml"),
        ("--source-ref", "refs/heads/main"),
        ("--source-digest", SHA),
        ("--predicate-type", "https://slsa.dev/provenance/v1"),
        ("--format", "json"),
    ):
        assert command[command.index(flag) + 1] == value


def test_cli_nonzero_status_must_not_be_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failing_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, command, "signature rejected")

    monkeypatch.setattr("scripts.check_signed_draft_asset.shutil.which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr("scripts.check_signed_draft_asset.subprocess.run", failing_run)
    with pytest.raises(subprocess.CalledProcessError):
        GitHubAttestationCLI().verify(
            path=tmp_path / "sample",
            repo="oaslananka/kicad-mcp-pro",
            sha=SHA,
            signer=".github/workflows/publish-mcpb.yml",
            source_ref="refs/heads/main",
        )


def test_exact_legacy_tag_ref_allowed(tmp_path: Path) -> None:
    file = tmp_path / "kicad-mcp-pro-4.5.0.mcpb"
    file.write_bytes(b"historical release")
    verifier = StubVerifier(file)
    accepted = verify_signed_asset(
        verifier,
        package=file,
        tag=TAG,
        source_commit=SHA,
        kind="mcpb",
        source_ref=f"refs/tags/{TAG}",
    )
    assert accepted["sourceRef"] == f"refs/tags/{TAG}"
    assert verifier.calls[0]["source_ref"] == f"refs/tags/{TAG}"


def test_mismatched_tag_ref_is_rejected_before_crypto_call(tmp_path: Path) -> None:
    file = tmp_path / "kicad-mcp-pro-4.5.0.mcpb"
    file.write_bytes(b"historical release")
    verifier = StubVerifier(file)
    with pytest.raises(ValueError, match="source ref"):
        verify_signed_asset(
            verifier,
            package=file,
            tag=TAG,
            source_commit=SHA,
            kind="mcpb",
            source_ref="refs/tags/mcp-server-v4.4.0",
        )
    assert not verifier.calls
