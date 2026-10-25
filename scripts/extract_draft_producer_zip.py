"""Atomically extract only expected files from a previously verified Actions ZIP.

This stage adds ZIP-member and decompression safety to artifact identity checks;
it never interprets the archive as a signed attestation or publishes a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
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
from scripts.runtime_path_safety import approved_runtime_path

_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 1000
_ROLE_GROUP = {
    "python-dist": "python_dist",
    "python-release-evidence": "python_evidence",
    "mcpb-release-evidence": "mcpb",
    "kicad-pcm-release-evidence": "pcm",
}


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
) -> dict[str, object]:
    """Verify exact GitHub ZIP metadata before atomically extracting approved files."""
    parsed = _VERSION.fullmatch(tag)
    if parsed is None or role not in _ROLE_GROUP:
        raise ValueError("unapproved mcp-server tag or producer role")
    expected_names = _expected(parsed.group(1))[_ROLE_GROUP[role]]
    verified = verify_archive(
        client,
        repo=repo,
        role=role,
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_id=artifact_id,
        head_sha=head_sha,
        downloaded_zip=downloaded_zip,
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
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        p.exit(2, f"draft ZIP extraction: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
