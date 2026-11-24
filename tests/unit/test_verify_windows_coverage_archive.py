"""The native coverage downloader must fail closed on foreign or unsafe archives."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from scripts.verify_windows_coverage_archive import ArtifactIdentity, main, verify_and_extract

IDENTITY = ArtifactIdentity(
    artifact_id=14892789567,
    run_id=45333003080,
    attempt=1,
    head_sha="958110d761c7f35b880ef45d9d8bc9b7079662a9",
    repository_id=1255527274,
)
REPORT = "windows-coverage.json"
MANIFEST = "windows-coverage-manifest.json"
FILES = {REPORT: b'{"files":{"src/kicad_mcp/server.py":{}}}', MANIFEST: b"{}"}


def _archive(entries: dict[str | zipfile.ZipInfo, bytes] | None = None) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in (FILES if entries is None else entries).items():
            archive.writestr(name, data)
    return stream.getvalue()


def _metadata(blob: bytes) -> dict[str, Any]:
    return {
        "id": IDENTITY.artifact_id,
        "name": f"windows-python-coverage-{IDENTITY.run_id}-{IDENTITY.attempt}",
        "expired": False,
        "size_in_bytes": len(blob),
        "digest": "sha256:" + hashlib.sha256(blob).hexdigest(),
        "workflow_run": {
            "id": IDENTITY.run_id,
            "head_sha": IDENTITY.head_sha,
            "repository_id": IDENTITY.repository_id,
        },
    }


def _verify(tmp_path: Path, blob: bytes, metadata: object) -> None:
    verify_and_extract(metadata, blob, tmp_path, IDENTITY)


def test_verified_archive_writes_only_the_exact_two_files(tmp_path: Path) -> None:
    blob = _archive()
    _verify(tmp_path, blob, _metadata(blob))
    assert {item.name for item in tmp_path.iterdir()} == set(FILES)
    for name, data in FILES.items():
        assert (tmp_path / name).read_bytes() == data


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 1),
        ("name", "windows-python-coverage-45333003080-2"),
        ("expired", True),
        ("expired", None),
        ("digest", None),
        ("size_in_bytes", 0),
    ],
)
def test_wrong_artifact_metadata_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    blob = _archive()
    metadata = _metadata(blob) | {field: value}
    with pytest.raises(ValueError, match="artifact metadata"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("field", "value"),
    [("id", 1), ("head_sha", "0" * 40), ("repository_id", 1)],
)
def test_foreign_run_identity_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    blob = _archive()
    metadata = _metadata(blob)
    metadata["workflow_run"][field] = value
    with pytest.raises(ValueError, match="workflow identity"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


def test_archive_digest_mismatch_is_rejected_before_writes(tmp_path: Path) -> None:
    blob = _archive()
    metadata = _metadata(blob) | {"digest": "sha256:" + "0" * 64}
    with pytest.raises(ValueError, match="digest"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["../outside.json", "/absolute.json", "extra.json"])
def test_unexpected_archive_entries_are_rejected(tmp_path: Path, name: str) -> None:
    blob = _archive(FILES | {name: b"unexpected"})
    metadata = _metadata(blob)
    with pytest.raises(ValueError, match="archive entries"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


def test_missing_report_is_rejected(tmp_path: Path) -> None:
    blob = _archive({MANIFEST: b"{}"})
    metadata = _metadata(blob)
    with pytest.raises(ValueError, match="archive entries"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


def test_symlink_entry_is_rejected(tmp_path: Path) -> None:
    link = zipfile.ZipInfo(REPORT)
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    blob = _archive({link: b"../../outside", MANIFEST: b"{}"})
    metadata = _metadata(blob)
    with pytest.raises(ValueError, match="unsafe archive entry"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


def test_oversized_decompressed_report_is_rejected(tmp_path: Path) -> None:
    blob = _archive(FILES | {REPORT: b"x" * 10_000_001})
    metadata = _metadata(blob)
    with pytest.raises(ValueError, match="unsafe archive entry"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


def test_existing_report_is_not_overwritten(tmp_path: Path) -> None:
    report = tmp_path / REPORT
    report.write_bytes(b"original")
    blob = _archive()
    metadata = _metadata(blob)
    with pytest.raises(ValueError, match="existing"):
        _verify(tmp_path, blob, metadata)
    assert report.read_bytes() == b"original"
    assert not (tmp_path / MANIFEST).exists()


def test_duplicate_report_name_is_rejected(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in FILES.items():
            archive.writestr(name, data)
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(REPORT, b"duplicate")
    blob = stream.getvalue()
    metadata = _metadata(blob)
    with pytest.raises(ValueError, match="archive entries"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


def test_invalid_zip_is_rejected_even_with_matching_digest(tmp_path: Path) -> None:
    blob = b"not a ZIP"
    metadata = _metadata(blob)
    with pytest.raises(ValueError, match="Invalid native coverage ZIP"):
        _verify(tmp_path, blob, metadata)
    assert not list(tmp_path.iterdir())


def test_existing_dangling_symlink_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "absent"
    try:
        (tmp_path / REPORT).symlink_to(outside)
    except OSError:
        pytest.skip("This environment cannot create symlinks.")
    blob = _archive()
    metadata = _metadata(blob)
    with pytest.raises(ValueError, match="existing"):
        _verify(tmp_path, blob, metadata)
    assert not outside.exists()
    assert not (tmp_path / MANIFEST).exists()


def test_metadata_only_cli_never_creates_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(_metadata(_archive())), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_windows_coverage_archive.py",
            "--artifact-id",
            str(IDENTITY.artifact_id),
            "--run-id",
            str(IDENTITY.run_id),
            "--attempt",
            str(IDENTITY.attempt),
            "--head",
            IDENTITY.head_sha,
            "--repository-id",
            str(IDENTITY.repository_id),
            "--metadata",
            str(metadata),
            "--metadata-only",
        ],
    )
    assert main() == 0
    assert not (tmp_path / REPORT).exists()
    assert not (tmp_path / MANIFEST).exists()
