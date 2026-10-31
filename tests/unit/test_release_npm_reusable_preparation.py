"""npm reusable preparation must be source-bound, signed and non-publishing (#1179)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / ".github/workflows/prepare-npm.yml"
LEGACY = ROOT / ".github/workflows/publish-npm.yml"
SHA = "a" * 40
TAG = "mcp-npm-v4.5.0"


def _workflow() -> dict:
    return yaml.safe_load(PREPARE.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["prepare"]["steps"]


def test_only_reusable_event_with_exact_required_inputs_and_read_only_repo() -> None:
    wf = _workflow()
    assert set(wf[True]) == {"workflow_call"}
    inputs = wf[True]["workflow_call"]["inputs"]
    assert set(inputs) == {"tag", "source_commit"}
    assert all(v["required"] is True and v["type"] == "string" for v in inputs.values())
    assert wf["permissions"] == {"contents": "read"}
    job = wf["jobs"]["prepare"]
    assert set(wf["jobs"]) == {"prepare"}
    assert "environment" not in job
    assert job["permissions"]["contents"] == "read"
    assert "write" not in {job["permissions"].get("contents"), wf["permissions"].get("contents")}
    for key in ("id-token", "attestations", "artifact-metadata"):
        assert job["permissions"][key] == "write"
    condition = job["if"]
    assert "github.repository == 'oaslananka/kicad-mcp-pro'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "startsWith(inputs.tag, 'mcp-npm-v')" in condition
    assert "inputs.source_commit != ''" in condition
    prior = yaml.safe_load(LEGACY.read_text(encoding="utf-8"))[True]
    assert "workflow_call" not in prior
    assert prior["release"]["types"] == ["published"]
    assert "workflow_dispatch" in prior


def test_identity_guard_precedes_installs_and_all_repository_code() -> None:
    steps = _steps()
    checkout = next(
        i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/checkout@")
    )
    guard = next(
        i for i, s in enumerate(steps) if s.get("name") == "Verify reusable npm source identity"
    )
    installs = next(
        i for i, s in enumerate(steps) if s.get("uses", "").startswith("astral-sh/setup-uv@")
    )
    assert (checkout, guard) == (0, 1)
    assert guard < installs
    assert steps[checkout]["with"] == {
        "fetch-depth": 0,
        "persist-credentials": False,
        "ref": "${{ github.sha }}",
    }
    assert steps[guard]["env"] == {
        "EXPECTED_TAG": "${{ inputs.tag }}",
        "EXPECTED_SOURCE": "${{ inputs.source_commit }}",
        "CALLER_SHA": "${{ github.sha }}",
        "CALLER_REF": "${{ github.ref }}",
    }
    script = steps[guard]["run"]
    for part in (
        '"$EXPECTED_TAG" =~ ^mcp-npm-v',
        '"$EXPECTED_SOURCE" =~ ^[0-9a-f]{40}$',
        '"$CALLER_REF" == "refs/heads/main"',
        '"$CALLER_SHA" == "$EXPECTED_SOURCE"',
        '"$checked_out" == "$EXPECTED_SOURCE"',
        '"$tagged_source" == "$EXPECTED_SOURCE"',
        '"$EXPECTED_TAG" == "mcp-npm-v$expected_version"',
    ):
        assert part in script


def test_package_built_and_attested_without_any_release_or_registry_writes() -> None:
    source = PREPARE.read_text(encoding="utf-8")
    for phrase in (
        "gh release ",
        "gh release upload",
        "npm publish",
        "docker push",
        "mcp-publisher publish",
        "--clobber",
    ):
        assert phrase not in source
    assert "environment:" not in source
    steps = _steps()
    assert any("npm ci" in s.get("run", "") for s in steps)
    pack = next(
        i for i, s in enumerate(steps) if s.get("name") == "Pack npm launcher and generate evidence"
    )
    slsa = next(
        i for i, s in enumerate(steps) if s.get("name") == "Attest npm SLSA build provenance"
    )
    sbom = next(i for i, s in enumerate(steps) if s.get("name") == "Attest npm launcher tarball")
    upload = next(i for i, s in enumerate(steps) if s.get("name") == "Store npm draft preparation")
    assert pack < slsa < sbom < upload
    assert "npm pack --json" in steps[pack]["run"]
    assert "npm sbom" in steps[pack]["run"]
    assert "sha256sum --check" in steps[pack]["run"]
    assert "mcp-npm-SHA256SUMS.txt" in steps[pack]["run"]
    assert "mcp-npm-sbom.cdx.json" in steps[pack]["run"]
    for ix in (slsa, sbom):
        assert steps[ix]["uses"] == "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
        assert steps[ix]["with"]["subject-checksums"] == "release-assets/mcp-npm/SHA256SUMS.txt"
    assert steps[slsa]["with"] == {"subject-checksums": "release-assets/mcp-npm/SHA256SUMS.txt"}
    assert steps[sbom]["with"]["sbom-path"] == "release-assets/mcp-npm/sbom.cdx.json"
    assert steps[upload]["with"]["path"] == "release-assets/draft/mcp-npm/"
    assert steps[upload]["with"]["if-no-files-found"] == "error"
    assert "npm publish" in LEGACY.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="Ubuntu Bash identity fixture")
@pytest.mark.parametrize(
    ("tag", "source", "caller", "head", "tag_sha", "ref", "version", "expected"),
    [
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.0", True),
        (TAG, "bad", SHA, SHA, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, "b" * 40, SHA, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, "b" * 40, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, SHA, "b" * 40, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/feature", "4.5.0", False),
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.1", False),
        ("mcp-npm-v4.5.0-rc1", SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.0", False),
    ],
)
def test_bash_identity_gate_fail_closed(
    tmp_path: Path,
    tag: str,
    source: str,
    caller: str,
    head: str,
    tag_sha: str,
    ref: str,
    version: str,
    expected: bool,
) -> None:
    guard = next(
        step for step in _steps() if step.get("name") == "Verify reusable npm source identity"
    )
    fake = tmp_path / "bin"
    fake.mkdir()
    git = fake / "git"
    git.write_text(
        '#!/bin/sh\ncase "$1" in\n'
        '  rev-parse) [ "$2" = HEAD ] || exit 98; printf "%s\\n" "$MOCK_HEAD";;\n'
        '  rev-list) printf "%s\\n" "$MOCK_TAG_SHA";;\n'
        "  *) exit 98;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    py = fake / "python"
    py.write_text('#!/bin/sh\necho "$MOCK_PACKAGE_VERSION"\n', encoding="utf-8")
    py.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(fake) + os.pathsep + os.environ["PATH"],
        "EXPECTED_TAG": tag,
        "EXPECTED_SOURCE": source,
        "CALLER_SHA": caller,
        "CALLER_REF": ref,
        "MOCK_HEAD": head,
        "MOCK_TAG_SHA": tag_sha,
        "MOCK_PACKAGE_VERSION": version,
        "GITHUB_OUTPUT": str(tmp_path / "out"),
    }
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", guard["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is expected, result.stderr
