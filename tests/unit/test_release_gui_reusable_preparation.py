"""Pre-publication GUI producer is callable, source-bound, and cannot publish (#1179)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/prepare-gui.yml"
LEGACY = ROOT / ".github/workflows/gui-release.yml"
SOURCE_SHA = "a" * 40


def _config() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps(job: str) -> list[dict]:
    return _config()["jobs"][job]["steps"]


def test_non_publishing_reusable_interface_keeps_legacy_publisher() -> None:
    cfg = _config()
    events = cfg[True]  # PyYAML 1.1 parses GitHub Actions "on" as True.
    assert set(events) == {"workflow_call"}
    assert set(events["workflow_call"]["inputs"]) == {"tag", "source_commit"}
    assert all(
        spec["type"] == "string" and spec["required"] is True
        for spec in events["workflow_call"]["inputs"].values()
    )
    assert cfg["permissions"] == {"contents": "read"}
    assert cfg["concurrency"]["cancel-in-progress"] is False
    previous = yaml.safe_load(LEGACY.read_text(encoding="utf-8"))[True]
    assert set(previous) == {"push", "workflow_dispatch"}
    assert previous["push"]["tags"] == ["kicad-mcp-gui-v*"]


def test_all_jobs_are_derived_from_owner_approved_main_and_tag() -> None:
    jobs = _config()["jobs"]
    assert set(jobs) == {"source", "tauri-build", "attest-and-store"}
    condition = jobs["source"]["if"]
    for part in (
        "github.repository == 'oaslananka/kicad-mcp-pro'",
        "github.ref == 'refs/heads/main'",
        "inputs.source_commit != ''",
        "startsWith(inputs.tag, 'kicad-mcp-gui-v')",
    ):
        assert part in condition
    assert jobs["tauri-build"]["needs"] == "source"
    assert jobs["attest-and-store"]["needs"] == "tauri-build"
    assert jobs["source"]["permissions"] == {"contents": "read"}
    assert jobs["tauri-build"]["permissions"] == {"contents": "read"}
    assert jobs["attest-and-store"]["permissions"] == {
        "contents": "read",
        "artifact-metadata": "write",
        "attestations": "write",
        "id-token": "write",
    }


def test_source_is_checked_before_executing_external_build_tools() -> None:
    source = _steps("source")
    checkout = next(i for i, s in enumerate(source) if "actions/checkout@" in s.get("uses", ""))
    verify = next(
        i for i, s in enumerate(source) if s.get("name") == "Verify GUI preparation source identity"
    )
    setup = next(i for i, s in enumerate(source) if "astral-sh/setup-uv@" in s.get("uses", ""))
    assert verify == checkout + 1 < setup
    assert source[checkout]["with"]["persist-credentials"] is False
    assert source[checkout]["with"]["fetch-depth"] == 0
    assert "if" not in source[verify]
    script = source[verify]["run"]
    assert "refs/tags/${EXPECTED_TAG}^{commit}" in script
    assert '[[ "$CALLER_SHA" == "$EXPECTED_SOURCE" ]]' in script
    assert '[[ "$(git rev-parse HEAD)" == "$EXPECTED_SOURCE" ]]' in script
    assert "src-tauri/Cargo.toml" in script
    assert "src-tauri/tauri.conf.json" in script


def test_complete_three_platform_matrix_and_local_evidence_only() -> None:
    jobs = _config()["jobs"]
    matrix = jobs["tauri-build"]["strategy"]["matrix"]["include"]
    assert {(x["os"], x["artifact-name"]) for x in matrix} == {
        ("ubuntu-24.04", "gui-linux-tauri"),
        ("macos-15", "gui-macos-tauri"),
        ("windows-2025", "gui-windows-tauri"),
    }
    build = _steps("tauri-build")
    assert next(s for s in build if "actions/checkout@" in s.get("uses", ""))["with"]["ref"] == (
        "refs/tags/${{ inputs.tag }}"
    )
    names = [s.get("name") for s in build]
    assert names.index("Verify checked-out GUI source") < names.index("Install Tauri CLI")
    assert names.index("Verify locked Tauri dependencies") < names.index("Build Tauri installers")
    store = next(s for s in build if s.get("name") == "Store non-publishing GUI bundles")
    assert store["with"]["if-no-files-found"] == "error"
    assert store["with"]["retention-days"] == 14

    prepare = _steps("attest-and-store")
    names = [step.get("name") for step in prepare]
    assert (
        names.index("Verify GUI evidence source identity")
        < names.index("Download exact-run GUI builder bundles")
        < names.index("Validate and stage complete GUI installer inventory")
        < names.index("Generate GUI draft evidence")
        < names.index("Verify GUI draft evidence")
        < names.index("Attest GUI SLSA build provenance")
        < names.index("Attest GUI installers")
        < names.index("Store GUI draft installers")
    )
    assert (
        "scripts/stage_gui_draft_assets.py"
        in prepare[names.index("Validate and stage complete GUI installer inventory")]["run"]
    )
    assert (
        "generate_gui_release_evidence.py verify-local"
        in prepare[names.index("Verify GUI draft evidence")]["run"]
    )
    assert (
        next(s for s in prepare if s.get("name") == "Download exact-run GUI builder bundles")[
            "with"
        ]["merge-multiple"]
        is False
    )
    assert (
        next(s for s in prepare if s.get("name") == "Store GUI draft installers")["with"]["name"]
        == "gui-draft-installers"
    )
    assert (
        next(
            s
            for s in prepare
            if s.get("name") == "Store GUI draft checksums and attestable evidence"
        )["with"]["name"]
        == "gui-draft-evidence"
    )
    contents = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "gh release ",
        "release create ",
        "release upload ",
        "npm publish",
        "pypa/gh-action-pypi-publish",
        "docker push",
        "contents: write",
        "workflow_dispatch:",
        "on:\n  push:",
        "release:\n",
    ):
        assert forbidden not in contents


@pytest.mark.skipif(os.name == "nt", reason="Bash identity check runs on Ubuntu")
@pytest.mark.parametrize(
    ("tag", "source_sha", "caller_sha", "caller_ref", "tag_sha", "expected_ok"),
    [
        ("kicad-mcp-gui-v4.7.0", SOURCE_SHA, SOURCE_SHA, "refs/heads/main", SOURCE_SHA, True),
        ("kicad-mcp-gui-v4.7.0", "b" * 40, SOURCE_SHA, "refs/heads/main", SOURCE_SHA, False),
        ("kicad-mcp-gui-v4.7.0", SOURCE_SHA, "b" * 40, "refs/heads/main", SOURCE_SHA, False),
        ("kicad-mcp-gui-v4.7.0", SOURCE_SHA, SOURCE_SHA, "refs/heads/feature", SOURCE_SHA, False),
        ("kicad-mcp-gui-v4.7.0", SOURCE_SHA, SOURCE_SHA, "refs/heads/main", "b" * 40, False),
        ("kicad-mcp-gui-v4.7.1", SOURCE_SHA, SOURCE_SHA, "refs/heads/main", SOURCE_SHA, False),
        ("kicad-mcp-gui-v4.7.0/evil", SOURCE_SHA, SOURCE_SHA, "refs/heads/main", SOURCE_SHA, False),
        ("mcp-server-v4.7.0", SOURCE_SHA, SOURCE_SHA, "refs/heads/main", SOURCE_SHA, False),
    ],
)
def test_real_bash_source_guard_blocks_untrusted_identity_before_build(
    tmp_path: Path,
    tag: str,
    source_sha: str,
    caller_sha: str,
    caller_ref: str,
    tag_sha: str,
    expected_ok: bool,
) -> None:
    bundle = tmp_path / "src-tauri"
    bundle.mkdir()
    (bundle / "tauri.conf.json").write_text('{"version": "4.7.0"}', encoding="utf-8")
    (bundle / "Cargo.toml").write_text('[package]\nversion="4.7.0"\n', encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "git").write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  rev-parse) echo {SOURCE_SHA};;\n"
        f"  rev-list) echo {tag_sha};;\n"
        "  *) exit 2;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (fake / "git").chmod(0o755)
    step = next(
        s for s in _steps("source") if s.get("name") == "Verify GUI preparation source identity"
    )
    env = {
        **os.environ,
        "PATH": str(fake) + os.pathsep + os.environ["PATH"],
        "EXPECTED_TAG": tag,
        "EXPECTED_SOURCE": source_sha,
        "CALLER_SHA": caller_sha,
        "CALLER_REF": caller_ref,
    }
    run = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (run.returncode == 0) is expected_ok, run.stderr
