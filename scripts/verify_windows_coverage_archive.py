"""Verify the exact native Windows coverage archive before writing its two reports."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

_MAX_REPORT_BYTES = 10_000_000
_MAX_ARCHIVE_BYTES = 21_000_000
_FILES = frozenset({"windows-coverage.json", "windows-coverage-manifest.json"})
_SHA = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_id: int
    run_id: int
    attempt: int
    head_sha: str
    repository_id: int

    def __post_init__(self) -> None:
        ids = (self.artifact_id, self.run_id, self.attempt, self.repository_id)
        if any(type(value) is not int or value <= 0 for value in ids):
            raise ValueError("Invalid expected artifact identity")
        if _SHA.fullmatch(self.head_sha) is None:
            raise ValueError("Invalid expected workflow head")

    @property
    def name(self) -> str:
        return f"windows-python-coverage-{self.run_id}-{self.attempt}"


def _verify_run(run: object, identity: ArtifactIdentity) -> None:
    if not isinstance(run, dict):
        raise ValueError("Missing artifact workflow identity")
    if (
        type(run.get("id")) is not int
        or run["id"] != identity.run_id
        or type(run.get("repository_id")) is not int
        or run["repository_id"] != identity.repository_id
        or run.get("head_sha") != identity.head_sha
    ):
        raise ValueError("Artifact workflow identity mismatch")


def verify_metadata(metadata: object, identity: ArtifactIdentity) -> tuple[int, str]:
    if not isinstance(metadata, dict):
        raise ValueError("Invalid artifact metadata")
    digest = metadata.get("digest")
    size = metadata.get("size_in_bytes")
    if (
        type(metadata.get("id")) is not int
        or metadata["id"] != identity.artifact_id
        or metadata.get("name") != identity.name
        or metadata.get("expired") is not False
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or type(size) is not int
        or not 1 <= size <= _MAX_ARCHIVE_BYTES
    ):
        raise ValueError("Invalid or mismatched artifact metadata")
    _verify_run(metadata.get("workflow_run"), identity)
    return size, digest


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    mode = stat.S_IFMT(info.external_attr >> 16)
    if (
        info.is_dir()
        or mode not in (0, stat.S_IFREG)
        or info.flag_bits & 1
        or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
        or not 1 <= info.file_size <= _MAX_REPORT_BYTES
    ):
        raise ValueError("Invalid or unsafe archive entry")
    with archive.open(info) as entry:
        data = entry.read(_MAX_REPORT_BYTES + 1)
    if len(data) != info.file_size or len(data) > _MAX_REPORT_BYTES:
        raise ValueError("Invalid decompressed archive entry size")
    return data


def _read_reports(blob: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries = archive.infolist()
            if len(entries) != len(_FILES) or {entry.filename for entry in entries} != _FILES:
                raise ValueError("Unexpected or missing archive entries")
            return {entry.filename: _read_entry(archive, entry) for entry in entries}
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("Invalid native coverage ZIP") from exc


def verify_and_extract(
    metadata: object, blob: bytes, root: Path, identity: ArtifactIdentity
) -> None:
    """Validate all bytes before exclusively creating the two fixed report files."""
    size, digest = verify_metadata(metadata, identity)
    if size != len(blob) or digest != "sha256:" + hashlib.sha256(blob).hexdigest():
        raise ValueError("Artifact archive size or digest mismatch")
    reports = _read_reports(blob)
    if any((root / name).exists() or (root / name).is_symlink() for name in _FILES):
        raise ValueError("Refusing to replace existing coverage inputs")
    for name, data in reports.items():
        with (root / name).open("xb") as output:
            output.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repository-id", required=True, type=int)
    parser.add_argument("--metadata", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--archive", type=Path)
    mode.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    try:
        identity = ArtifactIdentity(
            args.artifact_id, args.run_id, args.attempt, args.head, args.repository_id
        )
        with args.metadata.open("rb") as metadata_file:
            raw = metadata_file.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Artifact metadata exceeds size limit")
        metadata = json.loads(raw)
        if args.metadata_only:
            verify_metadata(metadata, identity)
            return 0
        with args.archive.open("rb") as archive:
            blob = archive.read(_MAX_ARCHIVE_BYTES + 1)
        verify_and_extract(metadata, blob, Path.cwd(), identity)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"::error::{exc}\n")
    print("Verified exact native Windows coverage archive SHA-256 and file entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
