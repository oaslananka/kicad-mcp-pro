"""Atomically extract only expected files from a previously verified Actions ZIP.

This stage adds ZIP-member and decompression safety to artifact identity checks;
it never interprets the archive as a signed attestation or publishes a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

from scripts.assemble_mcp_server_draft_assets import _VERSION, _expected
from scripts.check_draft_producer_archive import (
    REPOSITORY,
    GitHubArtifactClient,
    ReadOnlyArtifactClient,
    verify_archive,
)
from scripts.check_signed_draft_asset import _SCHEMA_VERSION
from scripts.runtime_path_safety import approved_runtime_path

_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 1000
_ROLE_GROUP = {
    "python-dist": "python_dist",
    "python-release-evidence": "python_evidence",
    "mcpb-release-evidence": "mcpb",
    "kicad-pcm-release-evidence": "pcm",
}
_SCHEMA_ROLE = "protocol-schemas-release-evidence"


def _allowed_members(tag: str, role: str, producer_profile: str) -> set[str]:
    """A caller must select one trust root, role, and tag namespace exactly."""
    if producer_profile == "legacy":
        roles = _ROLE_GROUP
    elif producer_profile == "reusable":
        roles = {**_ROLE_GROUP, _SCHEMA_ROLE: "schemas"}
    else:
        raise ValueError("unapproved producer profile")
    if role not in roles:
        raise ValueError("unapproved package family or producer role")
    if role == _SCHEMA_ROLE:
        match = _SCHEMA_VERSION.fullmatch(tag)
        if match is None:
            raise ValueError("unapproved protocol-schemas tag")
        return {
            f"oaslananka-kicad-protocol-schemas-{match.group(1)}.tgz",
            "SHA256SUMS.txt",
            "sbom.cdx.json",
        }
    match = _VERSION.fullmatch(tag)
    if match is None:
        raise ValueError("unapproved mcp-server tag")
    return _expected(match.group(1))[_ROLE_GROUP[role]]


def _check_schema_checksum(directory: Path, package: str) -> None:
    """One exact tarball digest, never a partial/multi-target checksum list."""
    checksums = directory / "SHA256SUMS.txt"
    if checksums.stat().st_size > 256:
        raise ValueError("invalid Protocol Schemas checksum inventory")
    value = checksums.read_text(encoding="ascii").splitlines()
    if len(value) != 1:
        raise ValueError("invalid Protocol Schemas checksum inventory")
    match = re.fullmatch(r"([0-9a-f]{64}) [ *]" + re.escape(package), value[0])
    if match is None:
        raise ValueError("unapproved Protocol Schemas checksum subject")
    digest = hashlib.sha256()
    with (directory / package).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != match.group(1):
        raise ValueError("Protocol Schemas tarball checksum differs from evidence")


def _members(archive: zipfile.ZipFile, expected: set[str]) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) != len(expected) or {e.filename for e in entries} != expected:
        raise ValueError("unexpected, duplicate or missing ZIP archive members")
    total = 0
    for info in entries:
        if (
            info.is_dir()
            or info.flag_bits & 1
            or "/" in info.filename
            or "\\" in info.filename
            or info.file_size <= 0
            or info.compress_size <= 0
            or (info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16))
        ):
            raise ValueError("ZIP contains unsafe or empty member")
        total += info.file_size
        if total > _MAX_TOTAL_BYTES or info.file_size > info.compress_size * _MAX_COMPRESSION_RATIO:
            raise ValueError("ZIP member exceeds safe decompression limits")
    return entries


def verify_and_extract(
    client: ReadOnlyArtifactClient,
    *,
    repo: str,
    role: str,
    tag: str,
    run_id: int,
    run_attempt: int,
    artifact_id: int,
    head_sha: str,
    downloaded_zip: Path,
    output: Path,
    producer_profile: str = "legacy",
) -> dict[str, object]:
    """Verify exact caller ZIP metadata before atomically extracting approved files."""
    expected_names = _allowed_members(tag, role, producer_profile)
    verified = verify_archive(
        client,
        repo=repo,
        role=role,
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_id=artifact_id,
        head_sha=head_sha,
        downloaded_zip=downloaded_zip,
        producer_profile=producer_profile,
    )
    output = Path(output).expanduser()
    if output.is_symlink() or output.exists():
        raise ValueError("output must not already exist")
    source = approved_runtime_path(downloaded_zip)
    parent = approved_runtime_path(output.parent)
    parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() == source:
        raise ValueError("extract output cannot replace the downloaded ZIP")
    with tempfile.TemporaryDirectory(prefix=".kicad-verified-zip-", dir=parent) as tmp:
        staging = Path(tmp)
        try:
            with zipfile.ZipFile(source) as archive:
                entries = _members(archive, expected_names)
                for info in entries:
                    with (
                        archive.open(info, "r") as src,
                        (staging / info.filename).open("xb") as dest,
                    ):
                        shutil.copyfileobj(src, dest, length=1024 * 1024)
                    if (staging / info.filename).stat().st_size != info.file_size:
                        raise ValueError("incomplete extracted ZIP member")
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise ValueError("unreadable or corrupted producer ZIP") from exc
        if role == _SCHEMA_ROLE:
            schema_package = next(n for n in expected_names if n.endswith(".tgz"))
            _check_schema_checksum(staging, schema_package)
        # Rehash ZIP after member extraction to reject substitutions during extraction.
        h = hashlib.sha256()
        with source.open("rb") as archive_input:
            for chunk in iter(lambda: archive_input.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != verified["archiveSha256"]:
            raise ValueError("producer ZIP changed during extraction")
        os.rename(staging, output)
    return {
        **verified,
        "extractedCount": len(expected_names),
        "zipMemberSafetyVerified": True,
        "extractedMemberNames": sorted(expected_names),
        "signedAttestationVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--role", required=True)
    p.add_argument("--producer-profile", choices=("legacy", "reusable"), default="legacy")
    p.add_argument("--tag", required=True)
    p.add_argument("--run-id", required=True, type=int)
    p.add_argument("--run-attempt", required=True, type=int)
    p.add_argument("--artifact-id", required=True, type=int)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--downloaded-zip", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    try:
        result = verify_and_extract(
            GitHubArtifactClient(),
            repo=REPOSITORY,
            role=args.role,
            tag=args.tag,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            artifact_id=args.artifact_id,
            head_sha=args.head_sha,
            downloaded_zip=args.downloaded_zip,
            output=args.output,
            producer_profile=args.producer_profile,
        )
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        p.exit(2, f"draft ZIP extraction: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
