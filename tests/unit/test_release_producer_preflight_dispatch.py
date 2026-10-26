"""The four-family draft producer caller never publishes a Release (#1179)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/draft-producer-preflight.yml"
SOURCE = "a" * 40


def _config() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_only_manual_nonpublishing_dispatch_and_minimal_permissions() -> None:
    config = _config()
    assert set(config[True]) == {"workflow_dispatch"}
    inputs = config[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"server_tag", "schemas_tag", "source_commit"}
    assert all(x["required"] is True and x["type"] == "string" for x in inputs.values())
    assert config["permissions"] == {"contents": "read"}
    assert config["concurrency"]["cancel-in-progress"] is False
    assert "source_commit" in config["concurrency"]["group"]
    source = config["jobs"]["source"]
    assert "github.ref == 'refs/heads/main'" in source["if"]
    assert "github.repository == 'oaslananka/kicad-mcp-pro'" in source["if"]
    assert source["permissions"] == {"contents": "read"}
    text = WORKFLOW.read_text(encoding="utf-8").lower()
    for forbidden in ("gh release", "npm publish", "uv publish", "gh api -x", "create-release"):
        assert forbidden not in text


@pytest.mark.parametrize(
    ("name", "workflow", "tag_input"),
    [
        ("python", "prepare-python.yml", "server_tag"),
        ("mcpb", "prepare-mcpb.yml", "server_tag"),
        ("pcm", "prepare-kicad-pcm.yml", "server_tag"),
        ("schemas", "prepare-protocol-schemas.yml", "schemas_tag"),
    ],
)
def test_reusable_producers_share_same_verified_source(
    name: str, workflow: str, tag_input: str
) -> None:
    job = _config()["jobs"][name]
    assert job["needs"] == "source"
    assert job["uses"] == f"./.github/workflows/{workflow}"
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    assert job["with"]["tag"] == "$" + "{{ inputs." + tag_input + " }}"
    assert job["with"]["source_commit"] == "$" + "{{ inputs.source_commit }}"


def _source_script() -> str:
    steps = _config()["jobs"]["source"]["steps"]
    checkout = steps[0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False
    return steps[1]["run"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash fixture; job runs on Ubuntu")
@pytest.mark.parametrize(
    ("sha_ok", "server_tag", "schemas_tag", "server_exists", "schemas_exists", "succeeds"),
    [
        (True, "mcp-server-v4.5.0", "protocol-schemas-v2.0.0", True, True, True),
        (False, "mcp-server-v4.5.0", "protocol-schemas-v2.0.0", True, True, False),
        (True, "mcp-server-v../4.5.0", "protocol-schemas-v2.0.0", True, True, False),
        (True, "mcp-server-v4.5.0", "protocol-schemas-vX.Y.Z", True, True, False),
        (True, "mcp-server-v4.5.0", "protocol-schemas-v2.0.0", False, True, False),
        (True, "mcp-server-v4.5.0", "protocol-schemas-v2.0.0", True, False, False),
    ],
)
def test_no_missing_tag_can_be_substituted_by_a_same_named_branch(
    tmp_path: Path,
    sha_ok: bool,
    server_tag: str,
    schemas_tag: str,
    server_exists: bool,
    schemas_exists: bool,
    succeeds: bool,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    git.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        ' "rev-parse HEAD") echo ' + SOURCE + ";;\n"
        ' "rev-list -n 1 refs/tags/mcp-server-v4.5.0^{commit}") '
        '[ "$SERVER_EXISTS" = yes ] || exit 91; echo ' + SOURCE + ";;\n"
        ' "rev-list -n 1 refs/tags/protocol-schemas-v2.0.0^{commit}") '
        '[ "$SCHEMAS_EXISTS" = yes ] || exit 91; echo ' + SOURCE + ";;\n"
        " *) exit 91;;\nesac\n",
        encoding="utf-8",
    )
    python = fake_bin / "python3"
    python.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        " *pyproject.toml*) echo 4.5.0;;\n"
        " *protocol-schemas/package.json*) echo 2.0.0;;\n"
        " *) exit 91;;\nesac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    python.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
        "EXPECTED_SHA": SOURCE if sha_ok else "b" * 40,
        "SERVER_TAG": server_tag,
        "SCHEMAS_TAG": schemas_tag,
        "CALLER_SHA": SOURCE,
        "CALLER_REF": "refs/heads/main",
        "SERVER_EXISTS": "yes" if server_exists else "no",
        "SCHEMAS_EXISTS": "yes" if schemas_exists else "no",
    }
    proc = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", _source_script()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (proc.returncode == 0) is succeeds, proc.stderr


def test_source_fails_closed_without_producer_or_release_mutations() -> None:
    script = _source_script()
    assert "refs/tags/$SERVER_TAG^{commit}" in script
    assert "refs/tags/$SCHEMAS_TAG^{commit}" in script
    assert '[[ "$CALLER_SHA" == "$EXPECTED_SHA" ]] || exit 1' in script
    assert '[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || exit 1' in script
    assert '[[ "$schemas_sha" == "$EXPECTED_SHA" ]] || exit 1' in script
