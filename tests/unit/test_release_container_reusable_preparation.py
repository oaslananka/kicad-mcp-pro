"""Non-publishing container reusable preparation for #1179."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / ".github/workflows/prepare-mcp-container.yml"
PUBLISH = ROOT / ".github/workflows/publish-mcp-container.yml"
TAG = "mcp-server-v4.5.0"
SHA = "a" * 40


def _workflow() -> dict:
    return yaml.safe_load(PREPARE.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["prepare"]["steps"]


def test_reusable_only_with_scoped_attestation_permissions() -> None:
    data = _workflow()
    assert set(data[True]) == {"workflow_call"}
    inputs = data[True]["workflow_call"]["inputs"]
    assert set(inputs) == {"tag", "source_commit"}
    assert all(x["type"] == "string" and x["required"] is True for x in inputs.values())
    assert data["permissions"] == {"contents": "read"}
    assert set(data["jobs"]) == {"prepare"}
    job = data["jobs"]["prepare"]
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    assert "environment" not in job
    condition = job["if"]
    assert "github.repository == 'oaslananka/kicad-mcp-pro'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "startsWith(inputs.tag, 'mcp-server-v')" in condition
    assert "workflow_call" not in yaml.safe_load(PUBLISH.read_text())[True]


def test_source_identity_checked_before_build_or_repo_code() -> None:
    steps = _steps()
    assert steps[0]["uses"].startswith("actions/checkout@")
    assert steps[0]["with"] == {
        "fetch-depth": 0,
        "persist-credentials": False,
        "ref": "${{ github.sha }}",
    }
    guard = steps[1]
    assert guard["name"] == "Verify container source identity"
    assert guard["env"] == {
        "EXPECTED_TAG": "${{ inputs.tag }}",
        "EXPECTED_SOURCE": "${{ inputs.source_commit }}",
        "CALLER_SHA": "${{ github.sha }}",
        "CALLER_REF": "${{ github.ref }}",
    }
    for marker in (
        '"$EXPECTED_TAG" =~ ^mcp-server-v',
        '"$EXPECTED_SOURCE" =~ ^[0-9a-f]{40}$',
        '"$CALLER_REF" == "refs/heads/main"',
        '"$CALLER_SHA" == "$EXPECTED_SOURCE"',
        '"$checked_out" == "$EXPECTED_SOURCE"',
        '"$tagged_source" == "$EXPECTED_SOURCE"',
        '"$EXPECTED_TAG" == "mcp-server-v$expected_version"',
    ):
        assert marker in guard["run"]


def test_same_pinned_multiarch_builder_but_no_ghcr_push() -> None:
    steps = _steps()
    text = PREPARE.read_text(encoding="utf-8")
    assert "docker/login-action@" not in text
    assert "cosign sign " not in text
    assert "gh release " not in text
    assert "packages: write" not in text
    assert "push: true" not in text
    assert "mcp-publisher publish" not in text
    assert "environment:" not in text
    qemu = next(x for x in steps if x.get("uses", "").startswith("docker/setup-qemu-action@"))
    buildx = next(x for x in steps if x.get("uses", "").startswith("docker/setup-buildx-action@"))
    builder = next(x for x in steps if x.get("uses", "").startswith("docker/build-push-action@"))
    for action in (qemu, buildx, builder):
        assert action["uses"] in PUBLISH.read_text(encoding="utf-8")
    args = builder["with"]
    assert args["platforms"] == "linux/amd64,linux/arm64"
    assert args["outputs"] == "type=cacheonly"
    assert args["push"] is False
    assert args["sbom"] is True
    assert args["provenance"] == "mode=max"
    assert "KICAD_MCP_VERSION=" in args["build-args"]
    assert "VCS_REF=" in args["build-args"]


def test_cacheonly_artifact_is_labeled_as_source_evidence_not_oci_digest() -> None:
    steps = _steps()
    names = [s.get("name") for s in steps]
    stage = names.index("Stage container build-source evidence")
    attest = names.index("Attest container build-source evidence")
    upload = names.index("Store container build-source evidence")
    assert stage < attest < upload
    source = steps[stage]["run"]
    assert "build-source.json" in source
    assert "mode" in source
    assert "cacheonly" in source
    assert "sha256sum --check" in source
    assert "SHA256SUMS.txt" in source
    assert "Dockerfile" in source
    assert "uv.lock" in source
    assert steps[attest]["uses"] == "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
    assert steps[attest]["with"] == {
        "subject-checksums": "release-assets/mcp-container/SHA256SUMS.txt"
    }
    assert steps[upload]["with"]["path"] == "release-assets/mcp-container/"
    assert steps[upload]["with"]["if-no-files-found"] == "error"
    assert "ghcr.io/oaslananka/kicad-mcp-pro" in PREPARE.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="Bash source-identity test")
@pytest.mark.parametrize(
    ("tag", "source", "caller", "head", "tag_sha", "ref", "version", "accepted"),
    [
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.0", True),
        (TAG, "bad", SHA, SHA, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, "b" * 40, SHA, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, "b" * 40, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, SHA, "b" * 40, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/feature", "4.5.0", False),
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.1", False),
        ("mcp-server-v4.5.0-rc1", SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.0", False),
    ],
)
def test_source_gate_fail_closed(
    tmp_path: Path,
    tag: str,
    source: str,
    caller: str,
    head: str,
    tag_sha: str,
    ref: str,
    version: str,
    accepted: bool,
) -> None:
    guard = _steps()[1]
    tools = tmp_path / "bin"
    tools.mkdir()
    git = tools / "git"
    git.write_text(
        '#!/bin/sh\ncase "$1" in\n'
        'rev-parse) [ "$2" = HEAD ] || exit 77; echo "$MOCK_HEAD";;\n'
        'rev-list) echo "$MOCK_TAG_SHA";;\n'
        "*) exit 77;;\nesac\n",
        encoding="utf-8",
    )
    py = tools / "python"
    py.write_text('#!/bin/sh\necho "$MOCK_PACKAGE_VERSION"\n', encoding="utf-8")
    for tool in (git, py):
        tool.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "EXPECTED_TAG": tag,
        "EXPECTED_SOURCE": source,
        "CALLER_SHA": caller,
        "CALLER_REF": ref,
        "MOCK_HEAD": head,
        "MOCK_TAG_SHA": tag_sha,
        "MOCK_PACKAGE_VERSION": version,
        "GITHUB_OUTPUT": str(tmp_path / "output"),
    }
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", guard["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr
