from __future__ import annotations

from pathlib import Path

from scripts import runtime_policy
from scripts.runtime_policy import (
    DriftSourceVersions,
    RuntimePolicyFinding,
    RuntimePolicyPaths,
    RuntimeSupportSnapshot,
    detect_runtime_drift,
    detect_runtime_lowering,
    validate_runtime_policy,
)


def _snapshot(
    *,
    vscode_range: str = "^1.120.0",
    python_range: str = ">=3.13",
    kicad_primary: str = "10.0.x",
) -> RuntimeSupportSnapshot:
    return RuntimeSupportSnapshot(
        vscode_engines_range=vscode_range,
        python_requires=python_range,
        kicad_primary=kicad_primary,
        kicad_supported_ranges=("10.0.x", "9.x", "8.x"),
    )


def test_repository_runtime_policy_is_parseable_and_in_sync() -> None:
    assert validate_runtime_policy() == []


def test_repository_runtime_metadata_matches_current_bugfix_window() -> None:
    snapshot = runtime_policy.snapshot_from_repo()

    if (Path(__file__).resolve().parents[2] / "apps" / "vscode-extension").is_dir():
        assert snapshot.vscode_engines_range == "^1.120.0"
    assert snapshot.python_requires == ">=3.13"
    assert snapshot.python_supported_minors == ("3.13", "3.14")


def test_vscode_engine_drift_reports_minimum_lag() -> None:
    findings = detect_runtime_drift(
        snapshot=_snapshot(vscode_range="^1.99.0"),
        current=DriftSourceVersions(
            vscode_stable="1.102.0",
            vscode_insiders="1.103.0-insider",
            python_bugfix_minors=("3.13", "3.14"),
            kicad_stable="10.0.4",
        ),
        max_vscode_minor_lag=1,
        python_supported_minor_window=2,
    )

    assert any(
        finding.surface == "VS Code"
        and finding.severity == "release-blocker"
        and "1.99.0" in finding.message
        for finding in findings
    )


def test_python_drift_reports_missing_current_supported_window() -> None:
    findings = detect_runtime_drift(
        snapshot=_snapshot(python_range=">=3.12"),
        current=DriftSourceVersions(
            vscode_stable="1.100.0",
            vscode_insiders="1.101.0-insider",
            python_bugfix_minors=("3.13", "3.14"),
            kicad_stable="10.0.4",
        ),
        max_vscode_minor_lag=1,
        python_supported_minor_window=2,
    )

    assert any(
        finding.surface == "Python"
        and "3.13, 3.14" in finding.message
        and ">=3.12" in finding.message
        for finding in findings
    )


def test_runtime_lowering_requires_product_changelog() -> None:
    findings = detect_runtime_lowering(
        base=_snapshot(vscode_range="^1.120.0", python_range=">=3.13"),
        current=_snapshot(vscode_range="^1.119.0", python_range=">=3.12"),
        changed_files=(Path("docs/status/runtime-policy-matrix.md"),),
    )

    assert [finding.surface for finding in findings] == ["VS Code", "Python"]
    assert all(finding.severity == "error" for finding in findings)


def test_runtime_lowering_accepts_required_changelogs() -> None:
    findings = detect_runtime_lowering(
        base=_snapshot(vscode_range="^1.120.0", python_range=">=3.13"),
        current=_snapshot(vscode_range="^1.119.0", python_range=">=3.12"),
        changed_files=(
            Path("apps/vscode-extension/CHANGELOG.md"),
            Path("CHANGELOG.md"),
            Path("docs/status/runtime-policy-matrix.md"),
        ),
    )

    assert findings == []


def test_runtime_lowering_uses_policy_changelog_paths() -> None:
    policy_paths = RuntimePolicyPaths(
        vscode_changelog=Path("custom/extension-changelog.md"),
        mcp_changelog=Path("custom/mcp-changelog.md"),
        kicad_changelogs=(
            Path("custom/extension-changelog.md"),
            Path("custom/mcp-changelog.md"),
        ),
    )

    findings = detect_runtime_lowering(
        base=_snapshot(vscode_range="^1.120.0", python_range=">=3.13", kicad_primary="10.0.x"),
        current=_snapshot(vscode_range="^1.119.0", python_range=">=3.12", kicad_primary="9.x"),
        changed_files=(
            Path("custom/extension-changelog.md"),
            Path("custom/mcp-changelog.md"),
            Path("docs/status/runtime-policy-matrix.md"),
        ),
        policy_paths=policy_paths,
    )

    assert findings == []


def test_snapshot_from_metadata_reports_missing_required_keys() -> None:
    try:
        runtime_policy._snapshot_from_metadata(  # noqa: SLF001 - verifies git-ref guard failure mode.
            compatibility={},
            extension_package={},
            pyproject={},
        )
    except ValueError as exc:
        assert "compatibility.kicad must be a mapping" in str(exc)
    else:
        raise AssertionError("missing runtime metadata should raise ValueError")


def test_write_drift_outputs_creates_parent_directories(tmp_path: Path) -> None:
    finding = RuntimePolicyFinding(
        surface="Python",
        severity="warning",
        message="Python support window drifted.",
        action="Update runtime metadata.",
    )
    markdown_output = tmp_path / "nested" / "reports" / "drift.md"
    json_output = tmp_path / "nested" / "reports" / "drift.json"

    runtime_policy._write_drift_outputs(  # noqa: SLF001 - exercises CLI output helper.
        findings=[finding],
        markdown_output=markdown_output,
        json_output=json_output,
    )

    assert "Python support window drifted." in markdown_output.read_text(encoding="utf-8")
    assert json_output.exists()


def test_fetch_current_versions_reads_release_feeds(monkeypatch) -> None:
    def fake_json(url: str):
        if url == runtime_policy.VSCODE_STABLE_RELEASES_URL:
            return ["1.100.0"]
        if url == runtime_policy.VSCODE_INSIDER_RELEASES_URL:
            return {"name": "1.101.0-insider"}
        if url == runtime_policy.PYTHON_RELEASES_URL:
            return {
                "metadata": {
                    "3.13": {"status": "bugfix"},
                    "3.14": {"status": "bugfix"},
                    "3.15": {"status": "prerelease"},
                }
            }
        raise AssertionError(url)

    monkeypatch.setattr(runtime_policy, "_fetch_json", fake_json)
    monkeypatch.setattr(
        runtime_policy,
        "_fetch_text",
        lambda url: "<p>Current Version: <strong>    10.0.4  </strong></p>",
    )

    current = runtime_policy.fetch_current_versions(python_supported_minor_window=2)

    assert current.vscode_stable == "1.100.0"
    assert current.vscode_insiders == "1.101.0-insider"
    assert current.python_bugfix_minors == ("3.13", "3.14")
    assert current.kicad_stable == "10.0.4"
    assert current.source_errors == ()
