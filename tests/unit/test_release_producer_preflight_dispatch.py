"""The opt-in family draft producer caller never publishes a Release (#1179)."""

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
    assert set(inputs) == {
        "server_tag",
        "schemas_tag",
        "source_commit",
        "npm_tag",
        "gui_tag",
        "include_npm",
        "include_gui",
        "include_container",
        "include_registry",
    }
    for name in ("server_tag", "schemas_tag", "source_commit"):
        assert inputs[name]["required"] is True and inputs[name]["type"] == "string"
    for name in ("npm_tag", "gui_tag"):
        assert inputs[name]["required"] is False and inputs[name]["type"] == "string"
    for name in ("include_npm", "include_gui", "include_container", "include_registry"):
        assert inputs[name]["type"] == "boolean"
        assert inputs[name]["required"] is False
        assert inputs[name]["default"] is False
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


@pytest.mark.parametrize(
    ("name", "workflow", "tag_input", "flag"),
    [
        ("npm", "prepare-npm.yml", "npm_tag", "include_npm"),
        ("gui", "prepare-gui.yml", "gui_tag", "include_gui"),
        ("container", "prepare-mcp-container.yml", "server_tag", "include_container"),
        ("registry", "prepare-mcp-registry.yml", "server_tag", "include_registry"),
    ],
)
def test_new_producers_are_opt_in_and_bound_to_same_source(
    name: str, workflow: str, tag_input: str, flag: str
) -> None:
    job = _config()["jobs"][name]
    assert job["needs"] == "source"
    assert job["uses"] == f"./.github/workflows/{workflow}"
    assert job["if"] == f"inputs.{flag} == true"
    assert job["with"] == {
        "tag": "$" + "{{ inputs." + tag_input + " }}",
        "source_commit": "$" + "{{ inputs.source_commit }}",
    }
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    if name == "gui":
        assert job["secrets"] == {
            "TAURI_SIGNING_PRIVATE_KEY": "$" + "{{ secrets.TAURI_SIGNING_PRIVATE_KEY }}",
            "TAURI_SIGNING_PRIVATE_KEY_PASSWORD": "$"
            + "{{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}",
        }
    else:
        assert "secrets" not in job


def test_optional_sources_checked_before_any_optional_build() -> None:
    source = _config()["jobs"]["source"]
    script = source["steps"][1]["run"]
    environment = source["steps"][1]["env"]
    for flag in ("NPM", "GUI", "CONTAINER", "REGISTRY"):
        assert environment[f"INCLUDE_{flag}"] == "$" + "{{ inputs.include_" + flag.lower() + " }}"
        assert f"$INCLUDE_{flag}" in script
    for key in ("NPM_TAG", "GUI_TAG"):
        assert environment[key] == "$" + "{{ inputs." + key.lower() + " }}"
        assert ("refs/tags/$" + key + "^{commit}") in script
    assert "packages/mcp-npm/package.json" in script
    assert "src-tauri/tauri.conf.json" in script
    assert "src-tauri/Cargo.toml" in script


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
        "INCLUDE_NPM": "false",
        "INCLUDE_GUI": "false",
        "INCLUDE_CONTAINER": "false",
        "INCLUDE_REGISTRY": "false",
        "NPM_TAG": "",
        "GUI_TAG": "",
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash fixture; source job runs on Ubuntu")
@pytest.mark.parametrize(
    ("overrides", "succeeds"),
    [
        ({}, True),
        ({"INCLUDE_NPM": "true", "NPM_TAG": "mcp-npm-v4.5.0"}, True),
        ({"INCLUDE_GUI": "true", "GUI_TAG": "kicad-mcp-gui-v4.5.0"}, True),
        ({"INCLUDE_CONTAINER": "true", "INCLUDE_REGISTRY": "true"}, True),
        (
            {
                "INCLUDE_NPM": "true",
                "NPM_TAG": "mcp-npm-v4.5.0",
                "INCLUDE_GUI": "true",
                "GUI_TAG": "kicad-mcp-gui-v4.5.0",
                "INCLUDE_CONTAINER": "true",
                "INCLUDE_REGISTRY": "true",
            },
            True,
        ),
        ({"INCLUDE_NPM": "true"}, False),
        ({"NPM_TAG": "mcp-npm-v4.5.0"}, False),
        ({"INCLUDE_NPM": "true", "NPM_TAG": "mcp-npm-v4.5.0", "NPM_SOURCE": "b" * 40}, False),
        ({"INCLUDE_NPM": "true", "NPM_TAG": "mcp-npm-v4.5.1"}, False),
        ({"INCLUDE_GUI": "true"}, False),
        ({"GUI_TAG": "kicad-mcp-gui-v4.5.0"}, False),
        ({"INCLUDE_GUI": "true", "GUI_TAG": "kicad-mcp-gui-v4.5.0", "GUI_SOURCE": "b" * 40}, False),
        (
            {"INCLUDE_GUI": "true", "GUI_TAG": "kicad-mcp-gui-v4.5.0", "CARGO_VERSION": "4.6.0"},
            False,
        ),
        ({"INCLUDE_GUI": "true", "GUI_TAG": "kicad-mcp-gui-v4.5.1"}, False),
        ({"INCLUDE_CONTAINER": "TRUE"}, False),
        ({"INCLUDE_REGISTRY": "yes"}, False),
    ],
)
def test_optional_family_tag_identity_and_cost_flags_fail_closed(
    tmp_path: Path, overrides: dict[str, str], succeeds: bool
) -> None:
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    git = mock_bin / "git"
    git.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        ' "rev-parse HEAD") echo ' + SOURCE + ";;\n"
        ' "rev-list -n 1 refs/tags/mcp-server-v4.5.0^{commit}") echo ' + SOURCE + ";;\n"
        ' "rev-list -n 1 refs/tags/protocol-schemas-v2.0.0^{commit}") echo ' + SOURCE + ";;\n"
        ' "rev-list -n 1 refs/tags/mcp-npm-v4.5.0^{commit}") echo "$NPM_SOURCE";;\n'
        ' "rev-list -n 1 refs/tags/kicad-mcp-gui-v4.5.0^{commit}") echo "$GUI_SOURCE";;\n'
        " *) exit 91;;\nesac\n",
        encoding="utf-8",
    )
    python = mock_bin / "python3"
    python.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        " *mcp-npm/package.json*) echo 4.5.0;;\n"
        " *tauri.conf.json*) echo 4.5.0;;\n"
        ' *Cargo.toml*) echo "$CARGO_VERSION";;\n'
        " *pyproject.toml*) echo 4.5.0;;\n"
        " *protocol-schemas/package.json*) echo 2.0.0;;\n"
        " *) exit 91;;\nesac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    python.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(mock_bin) + os.pathsep + os.environ["PATH"],
        "EXPECTED_SHA": SOURCE,
        "SERVER_TAG": "mcp-server-v4.5.0",
        "SCHEMAS_TAG": "protocol-schemas-v2.0.0",
        "CALLER_REF": "refs/heads/main",
        "CALLER_SHA": SOURCE,
        "INCLUDE_NPM": "false",
        "INCLUDE_GUI": "false",
        "INCLUDE_CONTAINER": "false",
        "INCLUDE_REGISTRY": "false",
        "NPM_TAG": "",
        "GUI_TAG": "",
        "NPM_SOURCE": SOURCE,
        "GUI_SOURCE": SOURCE,
        "CARGO_VERSION": "4.5.0",
        **overrides,
    }
    proc = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", _source_script()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (proc.returncode == 0) is succeeds, proc.stderr
