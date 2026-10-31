"""MCP Registry reusable preparation is source-bound and never publishes (#1179)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / ".github/workflows/prepare-mcp-registry.yml"
LEGACY = ROOT / ".github/workflows/publish-mcp-registry.yml"
TAG = "mcp-server-v4.5.0"
SHA = "a" * 40


def _job() -> dict:
    return yaml.safe_load(PREPARE.read_text(encoding="utf-8"))["jobs"]["prepare"]


def test_reusable_only_and_existing_publisher_unchanged() -> None:
    data = yaml.safe_load(PREPARE.read_text(encoding="utf-8"))
    assert set(data[True]) == {"workflow_call"}
    inputs = data[True]["workflow_call"]["inputs"]
    assert set(inputs) == {"tag", "source_commit"}
    assert all(p["type"] == "string" and p["required"] is True for p in inputs.values())
    assert data["permissions"] == {"contents": "read"}
    job = _job()
    assert set(data["jobs"]) == {"prepare"}
    assert "environment" not in job
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    assert "github.repository == 'oaslananka/kicad-mcp-pro'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert "startsWith(inputs.tag, 'mcp-server-v')" in job["if"]
    legacy = yaml.safe_load(LEGACY.read_text(encoding="utf-8"))[True]
    assert "workflow_call" not in legacy
    assert legacy["release"]["types"] == ["published"]
    assert "workflow_dispatch" in legacy


def test_source_guard_before_installs() -> None:
    steps = _job()["steps"]
    checkout = next(
        i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/checkout@")
    )
    guard = next(
        i
        for i, s in enumerate(steps)
        if s.get("name") == "Verify reusable registry source identity"
    )
    setup = next(
        i for i, s in enumerate(steps) if s.get("uses", "").startswith("astral-sh/setup-uv@")
    )
    assert checkout == 0
    assert guard == 1
    assert setup > guard
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
    for condition in (
        '"$EXPECTED_TAG" =~ ^mcp-server-v',
        '"$EXPECTED_SOURCE" =~ ^[0-9a-f]{40}$',
        '"$CALLER_REF" == "refs/heads/main"',
        '"$CALLER_SHA" == "$EXPECTED_SOURCE"',
        '"$checked_out" == "$EXPECTED_SOURCE"',
        '"$tagged_source" == "$EXPECTED_SOURCE"',
        '"$EXPECTED_TAG" == "mcp-server-v$expected_version"',
    ):
        assert condition in script


def test_read_only_manifest_payload_has_digests_and_signed_evidence() -> None:
    text = PREPARE.read_text(encoding="utf-8")
    steps = _job()["steps"]
    assert "mcp-publisher publish" not in text
    assert "gh release" not in text
    assert "docker build" not in text
    assert "MCP_REGISTRY_TOKEN" not in text
    assert "environment:" not in text
    assert "mcp-publisher login" not in text
    assert "GITHUB_TOKEN:" not in text
    names = [step.get("name") for step in steps]
    manifest = names.index("Validate and stage registry manifest")
    sign = names.index("Attest registry manifest provenance")
    upload = names.index("Store registry draft preparation")
    assert manifest < sign < upload
    assert "scripts/validate_mcp_manifest.py server.json" in steps[manifest]["run"]
    assert "scripts/publish_mcp_registry.py --dry-run" in steps[manifest]["run"]
    assert steps[manifest]["env"]["MCP_REGISTRY_TARGET"] == "official"
    assert steps[manifest]["env"]["MCP_REGISTRY_DRY_RUN"] == "true"
    assert "sha256sum" in steps[manifest]["run"]
    assert "SHA256SUMS.txt" in steps[manifest]["run"]
    assert steps[sign]["uses"] == "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
    assert steps[sign]["with"] == {
        "subject-checksums": "release-assets/mcp-registry/SHA256SUMS.txt"
    }
    assert (
        steps[upload]["uses"] == "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"
    )
    assert steps[upload]["with"]["path"] == "release-assets/mcp-registry/"
    assert steps[upload]["with"]["if-no-files-found"] == "error"
    assert "mcp-publisher" in LEGACY.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="Ubuntu shell-only source guard")
@pytest.mark.parametrize(
    ("tag", "source", "caller", "head", "tag_sha", "ref", "version", "ok"),
    [
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.0", True),
        (TAG, "invalid", SHA, SHA, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, "b" * 40, SHA, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, "b" * 40, SHA, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, SHA, "b" * 40, "refs/heads/main", "4.5.0", False),
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/untrusted", "4.5.0", False),
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.1", False),
        ("mcp-server-v4.5.0-rc1", SHA, SHA, SHA, SHA, "refs/heads/main", "4.5.0", False),
    ],
)
def test_source_guard_fails_closed(
    tmp_path: Path,
    tag: str,
    source: str,
    caller: str,
    head: str,
    tag_sha: str,
    ref: str,
    version: str,
    ok: bool,
) -> None:
    guard = next(
        s for s in _job()["steps"] if s.get("name") == "Verify reusable registry source identity"
    )
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "git").write_text(
        '#!/bin/sh\ncase "$1" in\n'
        ' rev-parse) [ "$2" = HEAD ] || exit 78; echo "$MOCK_HEAD";;\n'
        ' rev-list) echo "$MOCK_TAG_SHA";;\n'
        " *) exit 78;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (tools / "python").write_text('#!/bin/sh\necho "$MOCK_PACKAGE_VERSION"\n', encoding="utf-8")
    for tool in tools.iterdir():
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
    }
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", guard["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is ok, result.stderr
