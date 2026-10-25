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


def verify_signed_asset(
    verifier: AttestationVerifier,
    *,
    package: Path,
    tag: str,
    source_commit: str,
    kind: str,
    source_ref: str = "refs/heads/main",
) -> dict[str, object]:
    match = _VERSION.fullmatch(tag)
    if match is None or _SHA.fullmatch(source_commit) is None or kind not in _SIGNERS:
        raise ValueError("unapproved signed package identity")
    if source_ref not in {"refs/heads/main", f"refs/tags/{tag}"}:
        raise ValueError("signed package source ref must match main or the exact approved tag")
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
    for entry in signed:
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
        subjects = statement.get("subject")
        if not isinstance(subjects, list):
            raise ValueError("signed provenance has no subjects")
        for subject in subjects:
            if (
                isinstance(subject, dict)
                and subject.get("name") == path.name
                and isinstance(subject.get("digest"), dict)
                and subject["digest"].get("sha256") == artifact_digest
            ):
                match_count += 1
    if match_count == 0:
        raise ValueError("verified signatures do not cover the expected package digest")
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
        default="refs/heads/main",
        help="Signed source ref: refs/heads/main or refs/tags/<exact tag>",
    )
    args = p.parse_args()
    try:
        result = verify_signed_asset(
            GitHubAttestationCLI(),
            package=args.package,
            tag=args.tag,
            source_commit=args.source_commit,
            kind=args.kind,
            source_ref=args.source_ref,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        p.exit(2, f"signed draft package attestation: FAIL: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
