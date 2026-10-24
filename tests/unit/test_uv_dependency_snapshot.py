"""Dependency graph must reflect the real, patched uv.lock, not stale SBOMs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from packaging.version import Version

from scripts.submit_uv_dependency_snapshot import build_snapshot


def _build() -> dict[str, Any]:
    return build_snapshot(
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
                sha=sha,
                ref=ref,
                job_id="test",
                scanned="2026-10-22T12:00:00Z",
            )


def test_dependency_snapshot_is_deterministic() -> None:
    first_snapshot = _build()
    second_snapshot = _build()
    assert first_snapshot == second_snapshot
    assert first_snapshot["manifests"]["uv.lock"]["resolved"]


def test_snapshot_uses_checked_in_lock_independent_of_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A caller's CWD must not redirect the lockfile read."""
    import json
    import sys

    from scripts.submit_uv_dependency_snapshot import main

    (tmp_path / "uv.lock").write_text("not valid TOML", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "submit_uv_dependency_snapshot.py",
            "--sha",
            "a" * 40,
            "--ref",
            "refs/heads/main",
            "--job-id",
            "audit",
        ],
    )
    main()
    generated = json.loads(capsys.readouterr().out)
    assert len(generated["manifests"]["uv.lock"]["resolved"]) >= 150
    assert (tmp_path / "uv.lock").read_text(encoding="utf-8") == "not valid TOML"
    assert list(tmp_path.iterdir()) == [tmp_path / "uv.lock"]


@pytest.mark.parametrize("unsafe_option", ["--lock", "--output"])
def test_snapshot_cli_rejects_caller_controlled_file_paths(
    unsafe_option: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from scripts.submit_uv_dependency_snapshot import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "submit_uv_dependency_snapshot.py",
            "--sha",
            "a" * 40,
            "--ref",
            "refs/heads/main",
            "--job-id",
            "audit",
            unsafe_option,
            "../outside-uv.lock",
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2


def test_platform_specific_dependency_variants_keep_both_purls() -> None:
    from scripts.submit_uv_dependency_snapshot import (
        _locked_package_graph,
        _reachable_runtime,
        _resolved_packages,
    )

    packages: list[dict[str, Any]] = [
        {
            "name": "example",
            "version": "1.0.0",
            "source": {"editable": "."},
            "dependencies": [{"name": "fastmcp"}],
        },
        {
            "name": "fastmcp",
            "version": "4.1.2",
            "source": {"registry": "https://pypi.org/simple"},
            "dependencies": [
                {"name": "beartype", "version": "0.22.9"},
                {"name": "beartype", "version": "0.23.1"},
            ],
        },
        {
            "name": "beartype",
            "version": "0.22.9",
            "source": {"registry": "https://pypi.org/simple"},
        },
        {
            "name": "beartype",
            "version": "0.23.1",
            "source": {"registry": "https://pypi.org/simple"},
        },
    ]
    versions, edges = _locked_package_graph(packages)
    runtime = _reachable_runtime({"fastmcp"}, edges)
    result = _resolved_packages(versions, edges, {"fastmcp"}, runtime)
    assert set(result) == {"fastmcp", "beartype@0.22.9", "beartype@0.23.1"}
    assert set(result["fastmcp"]["dependencies"]) == {
        "pkg:pypi/beartype@0.22.9",
        "pkg:pypi/beartype@0.23.1",
    }
    assert result["beartype@0.22.9"]["scope"] == "runtime"
    assert result["beartype@0.23.1"]["scope"] == "runtime"


def test_platform_variant_dependency_must_specify_version() -> None:
    from scripts.submit_uv_dependency_snapshot import _locked_package_graph

    packages: list[dict[str, Any]] = [
        {
            "name": "foo",
            "version": "1",
            "source": {"registry": "https://pypi.org/simple"},
            "dependencies": [{"name": "beartype"}],
        },
        {
            "name": "beartype",
            "version": "0.22.9",
            "source": {"registry": "https://pypi.org/simple"},
        },
        {
            "name": "beartype",
            "version": "0.23.1",
            "source": {"registry": "https://pypi.org/simple"},
        },
    ]
    with pytest.raises(ValueError, match="Ambiguous dependency"):
        _locked_package_graph(packages)


def test_same_name_and_version_duplicate_fails_closed() -> None:
    from scripts.submit_uv_dependency_snapshot import _locked_package_graph

    entry = {
        "name": "beartype",
        "version": "0.23.1",
        "source": {"registry": "https://pypi.org/simple"},
    }
    with pytest.raises(ValueError, match="Duplicate PyPI"):
        _locked_package_graph([entry, entry])
