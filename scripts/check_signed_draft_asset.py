"""Verify real GitHub-signed SLSA provenance for a staged release package.

The verifier intentionally demands stronger provenance than a completed
'attest' step: gh attestation verify must succeed with exact repository,
source commit, source ref, signer workflow and expected artifact digest.
No publication or registry write is authorized by this check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol

from scripts.assemble_mcp_server_draft_assets import _VERSION, _expected
from scripts.check_draft_producer_archive import REPOSITORY
from scripts.runtime_path_safety import approved_runtime_path

_SHA = re.compile(r"^[0-9a-f]{40}$")
_MAIN_REF = "refs/heads/main"
_PREDICATE = "https://slsa.dev/provenance/v1"
_SIGNERS = {
    "python": ".github/workflows/publish-python.yml",
    "mcpb": ".github/workflows/publish-mcpb.yml",
    "pcm": ".github/workflows/publish-kicad-pcm.yml",
}


class AttestationVerifier(Protocol):
    def verify(
        self, *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]: ...


class GitHubAttestationCLI:
    """Only a read-only, cryptographic verification call to GitHub CLI."""

    def verify(
        self, *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        executable = shutil.which("gh")
        if executable is None:
            raise ValueError("GitHub CLI unavailable for signed attestation check")
        result = subprocess.run(
            [
                executable,
                "attestation",
                "verify",
                str(path),
                "--repo",
                repo,
                "--signer-workflow",
                f"{repo}/{signer}",
                "--source-ref",
                source_ref,
                "--source-digest",
                sha,
                "--predicate-type",
                _PREDICATE,
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        value = json.loads(result.stdout)
        if not isinstance(value, list):
            raise ValueError("gh attestation returned non-list verification results")
        return value


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _invocation_matches(
    result: dict[str, Any], statement: dict[str, Any], expected: str | None
) -> bool:
    """Both signed SLSA invocation locations must agree with the approved run."""
    if expected is None:
        return False
    predicate = statement.get("predicate")
    run_details = predicate.get("runDetails") if isinstance(predicate, dict) else None
    metadata = run_details.get("metadata") if isinstance(run_details, dict) else None
    signature = result.get("signature")
    certificate = signature.get("certificate") if isinstance(signature, dict) else None
    statement_invocation = metadata.get("invocationId") if isinstance(metadata, dict) else None
    certificate_invocation = (
        certificate.get("runInvocationURI") if isinstance(certificate, dict) else None
    )
    return statement_invocation == expected and certificate_invocation == expected


def _subject_matches(subject: object, filename: str, sha256: str) -> bool:
    """Only cryptographically reported matching subject name/digest pairs count."""
    if not isinstance(subject, dict) or subject.get("name") != filename:
        return False
    digest = subject.get("digest")
    return isinstance(digest, dict) and digest.get("sha256") == sha256


def _attestation_match_counts(
    entry: object, *, filename: str, sha256: str, expected_invocation: str | None
) -> tuple[int, int]:
    """Require structurally valid attestation data even when no subject matches."""
    if not isinstance(entry, dict):
        raise ValueError("malformed verified attestation")
    result = entry.get("verificationResult")
    if not isinstance(result, dict):
        raise ValueError("missing cryptographic verification result")
    statement = result.get("statement")
    if not isinstance(statement, dict):
        raise ValueError("missing attestation statement")
    if statement.get("predicateType") != _PREDICATE:
        raise ValueError("unexpected signed provenance predicate")
    run_matches = _invocation_matches(result, statement, expected_invocation)
    subjects = statement.get("subject")
    if not isinstance(subjects, list):
        raise ValueError("signed provenance has no subjects")
    count = sum(_subject_matches(subject, filename, sha256) for subject in subjects)
    return count, count if run_matches else 0


def verify_signed_asset(
    verifier: AttestationVerifier,
    *,
    package: Path,
    tag: str,
    source_commit: str,
    kind: str,
    source_ref: str = _MAIN_REF,
    producer_run_id: int | None = None,
    producer_run_attempt: int | None = None,
) -> dict[str, object]:
    match = _VERSION.fullmatch(tag)
    if match is None or _SHA.fullmatch(source_commit) is None or kind not in _SIGNERS:
        raise ValueError("unapproved signed package identity")
    if source_ref not in {_MAIN_REF, f"refs/tags/{tag}"}:
        raise ValueError("signed package source ref must match main or the exact approved tag")
    if (producer_run_id is None) != (producer_run_attempt is None):
        raise ValueError("producer run ID and attempt must be provided together")
    if producer_run_id is not None and (
        type(producer_run_id) is not int
        or producer_run_id <= 0
        or type(producer_run_attempt) is not int
        or producer_run_attempt <= 0
    ):
        raise ValueError("invalid producer run ID or attempt")
    expected_invocation = (
        f"https://github.com/{REPOSITORY}/actions/runs/"
        f"{producer_run_id}/attempts/{producer_run_attempt}"
        if producer_run_id is not None
        else None
    )
    version = match.group(1)
    allowed = _expected(version)["python_dist" if kind == "python" else kind]
    allowed_packages = {n for n in allowed if n.endswith((".whl", ".tar.gz", ".mcpb", ".zip"))}
    if package.is_symlink() or package.name not in allowed_packages:
        raise ValueError("unapproved or linked signed package")
    path = approved_runtime_path(package)
    if not path.is_file() or not path.stat().st_size:
        raise ValueError("missing or empty signed release package")
    artifact_digest = _sha256(path)
    signed = verifier.verify(
        path=path,
        repo=REPOSITORY,
        sha=source_commit,
        signer=_SIGNERS[kind],
        source_ref=source_ref,
    )
    if not isinstance(signed, list) or not signed:
        raise ValueError("no cryptographically verified GitHub attestations")
    match_count = 0
    run_binding_count = 0
    for entry in signed:
        package_matches, run_matches = _attestation_match_counts(
            entry,
            filename=path.name,
            sha256=artifact_digest,
            expected_invocation=expected_invocation,
        )
        match_count += package_matches
        run_binding_count += run_matches
    if match_count == 0:
        raise ValueError("verified signatures do not cover the expected package digest")
    if expected_invocation is not None and run_binding_count == 0:
        raise ValueError("signed SLSA invocation does not match exact producer run and attempt")
    # Ensure the verified package did not change while fetching signed evidence.
    check = _sha256(path)
    if check != artifact_digest:
        raise ValueError("release package changed during signature verification")
    return {
        "repo": REPOSITORY,
        "tag": tag,
        "sourceCommit": source_commit,
        "package": path.name,
        "sha256": artifact_digest,
        "signerWorkflow": _SIGNERS[kind],
        "sourceRef": source_ref,
        "verifiedMatchingAttestationCount": match_count,
        "signedAttestationVerified": True,
        "producerRunInvocationVerified": expected_invocation is not None,
        "producerRunId": producer_run_id,
        "producerRunAttempt": producer_run_attempt,
        "producerJobBindingVerified": False,
        "registryReceiptVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", required=True, type=Path)
    p.add_argument("--tag", required=True)
    p.add_argument("--source-commit", required=True)
    p.add_argument("--kind", required=True, choices=sorted(_SIGNERS))
    p.add_argument(
        "--source-ref",
        default=_MAIN_REF,
        help="Signed source ref: refs/heads/main or refs/tags/<exact tag>",
    )
    p.add_argument("--producer-run-id", type=int)
    p.add_argument("--producer-run-attempt", type=int)
    args = p.parse_args()
    try:
        result = verify_signed_asset(
            GitHubAttestationCLI(),
            package=args.package,
            tag=args.tag,
            source_commit=args.source_commit,
            kind=args.kind,
            source_ref=args.source_ref,
            producer_run_id=args.producer_run_id,
            producer_run_attempt=args.producer_run_attempt,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        p.exit(2, f"signed draft package attestation: FAIL: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
