"""Same-run SonarCloud coverage artifact integrity and trust regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import ci_coverage_artifact as artifact

COMMIT = "a" * 40


def test_coverage_artifact_accepts_only_same_sha_run_and_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "coverage.xml").write_bytes(b"<coverage />")
    artifact.write_manifest(sha=COMMIT, run_id=123, attempt=2)
    artifact.verify_manifest(sha=COMMIT, run_id=123, attempt=2)

    for sha, run_id, attempt in (("b" * 40, 123, 2), (COMMIT, 124, 2), (COMMIT, 123, 1)):
        with pytest.raises(ValueError, match="different run"):
            artifact.verify_manifest(sha=sha, run_id=run_id, attempt=attempt)

    (tmp_path / "coverage.xml").write_bytes(b"<tampered />")
    with pytest.raises(ValueError, match="tampered"):
        artifact.verify_manifest(sha=COMMIT, run_id=123, attempt=2)


def test_coverage_artifact_rejects_invalid_or_symlinked_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "coverage.xml").write_bytes(b"<coverage />")
    with pytest.raises(ValueError, match="Invalid"):
        artifact.write_manifest(sha="bad", run_id=123, attempt=2)
    with pytest.raises(ValueError, match="Invalid"):
        artifact.write_manifest(sha=COMMIT, run_id=0, attempt=2)
    artifact.write_manifest(sha=COMMIT, run_id=123, attempt=2)
    manifest_path = tmp_path / "ci-coverage-manifest.json"
    manifest_path.unlink()
    manifest_path.symlink_to(tmp_path / "coverage.xml")
    with pytest.raises(ValueError, match="symlink|regular"):
        artifact.verify_manifest(sha=COMMIT, run_id=123, attempt=2)
    manifest_path.unlink()
    manifest_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="different run"):
        artifact.verify_manifest(sha=COMMIT, run_id=123, attempt=2)


def test_coverage_artifact_refuses_symlinked_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    other = tmp_path / "outside.xml"
    other.write_bytes(b"<coverage />")
    (tmp_path / "coverage.xml").symlink_to(other)
    with pytest.raises(ValueError, match="regular file"):
        artifact.write_manifest(sha=COMMIT, run_id=123, attempt=2)
