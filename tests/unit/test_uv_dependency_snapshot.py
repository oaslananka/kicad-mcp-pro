"""Dependency graph must reflect the real, patched uv.lock, not stale SBOMs."""

from __future__ import annotations

from pathlib import Path

import pytest
from packaging.version import Version

from scripts.submit_uv_dependency_snapshot import build_snapshot

ROOT = Path(__file__).resolve().parents[2]


def _build() -> dict:
    return build_snapshot(
        ROOT / "uv.lock",
        sha="a" * 40,
        ref="refs/heads/main",
        job_id="test-run",
        scanned="2026-10-22T12:00:00Z",
    )


def test_snapshot_includes_security_fixed_versions_and_full_graph() -> None:
    snapshot = _build()
    packages = snapshot["manifests"]["uv.lock"]["resolved"]
    assert len(packages) >= 150
    for name, minimum in {
        "gitpython": "3.2.1",
        "pypdf": "6.21.1",
        "opentelemetry-api": "1.45.1",
    }.items():
        assert Version(packages[name]["package_url"].split("@")[-1]) >= Version(minimum)
    assert packages["opentelemetry-api"]["scope"] == "runtime"
    assert packages["pypdf"]["scope"] == "development"
    assert packages["gitpython"]["relationship"] == "direct"
    assert "pkg:pypi/opentelemetry-api@1.45.1" in packages["opentelemetry-sdk"]["dependencies"]


def test_submission_bound_to_main_branch_with_strict_sha() -> None:
    for sha, ref in [
        ("xyz", "refs/heads/main"),
        ("a" * 40, "refs/heads/untrusted"),
    ]:
        with pytest.raises(ValueError):
            build_snapshot(
                ROOT / "uv.lock",
                sha=sha,
                ref=ref,
                job_id="test",
                scanned="2026-10-22T12:00:00Z",
            )


def test_dependency_snapshot_is_deterministic() -> None:
    assert _build() == _build()
