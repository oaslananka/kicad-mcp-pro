"""Ensure owner-invoked MCPB preparation never mutates a GitHub Release (#1179)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/prepare-mcpb.yml"
LEGACY = ROOT / ".github/workflows/publish-mcpb.yml"


def _config() -> dict:
    config = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    return config


def _steps() -> list[dict]:
    return _config()["jobs"]["prepare"]["steps"]


def test_mcpb_prepare_interface_is_source_bound_and_legacy_events_remain() -> None:
    config = _config()
    events = config[True]  # PyYAML 1.1 parses GitHub Actions 'on' as True
    inputs = events["workflow_call"]["inputs"]
    assert set(inputs) == {"tag", "source_commit"}
    for definition in inputs.values():
        assert definition["required"] is True
        assert definition["type"] == "string"
    assert set(events) == {"workflow_call"}
    previous = yaml.safe_load(LEGACY.read_text(encoding="utf-8"))[True]
    assert previous["release"]["types"] == ["published"]
    assert "workflow_dispatch" in previous
    assert "workflow_call" not in previous

    job = config["jobs"]["prepare"]
    condition = job["if"]
    assert "inputs.source_commit != ''" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.repository == 'oaslananka/kicad-mcp-pro'" in condition
    assert "inputs.source_commit == ''" not in condition
    assert job["permissions"]["contents"] == "read"
    assert "environment" not in job
    assert "startsWith(inputs.tag, 'mcp-server-v')" in condition


def test_mcpb_prepare_attests_but_does_not_attach_to_release() -> None:
    steps = _steps()
    source_check = next(
        s for s in steps if s.get("name") == "Verify reusable preparation source identity"
    )
    assert "if" not in source_check
    assert '[ "$CALLER_SHA" == "$EXPECTED_SOURCE" ]' in source_check["run"].replace(
        "[[", "["
    ).replace("]]", "]")
    assert "$(git rev-parse HEAD)" in source_check["run"]
    checkout = next(s for s in steps if "actions/checkout@" in s.get("uses", ""))
    assert checkout["with"]["ref"] == "refs/tags/" + "$" + "{{ steps.release.outputs.tag }}"
    source_index = next(
        i
        for i, step in enumerate(steps)
        if step.get("name") == "Verify reusable preparation source identity"
    )
    checkout_index = next(
        i for i, step in enumerate(steps) if "actions/checkout@" in step.get("uses", "")
    )
    setup_index = next(
        i for i, step in enumerate(steps) if "astral-sh/setup-uv@" in step.get("uses", "")
    )
    assert source_index == checkout_index + 1
    assert source_index < setup_index
    assert any(s.get("name") == "Attest MCPB bundle" for s in steps)
    assert any(s.get("name") == "Store MCPB release evidence" for s in steps)
    assert "gh release" not in WORKFLOW.read_text(encoding="utf-8")
    assert "npm publish" not in WORKFLOW.read_text(encoding="utf-8")
    assert "gh release upload" in LEGACY.read_text(encoding="utf-8")


def test_mcpb_tag_resolution_and_release_source_agree() -> None:
    steps = _steps()
    resolve = next(s for s in steps if s.get("name") == "Resolve release tag")
    assert "PREPARE_SOURCE" not in resolve["env"]
    assert 'if [[ -n "$PREPARE_SOURCE" ]]' not in resolve["run"]
    assert 'release_tag="$DISPATCH_TAG"' in resolve["run"]
    assert "Unsupported MCPB release tag" in resolve["run"]
    source_verify = next(
        s for s in steps if s.get("name") == "Verify release source and manifest version"
    )
    assert 'test "$source_commit" = "$tag_commit" || exit 1' in source_verify["run"]
    assert "refs/tags/" + "$" + "{release_tag}^{commit}" in source_verify["run"]
    assert 'test "$source_commit" = "$PREPARE_SOURCE" || exit 1' in source_verify["run"]
    assert 'if [[ -z "$PREPARE_SOURCE" ]]' not in source_verify["run"]
    assert source_verify["env"]["PREPARE_SOURCE"] == "$" + "{{ inputs.source_commit }}"


def _simulate_source_step(
    tmp_path: Path, *, prepare: bool, matching: bool = True, tag_exists: bool = True
) -> tuple[int, bool]:
    """Run real bash control flow against offline git/node/gh stubs."""
    source = next(
        s for s in _steps() if s.get("name") == "Verify release source and manifest version"
    )
    sha = "a" * 40
    tag_sha = sha if matching else "b" * 40
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(
        '#!/bin/sh\ncase "$*" in\n'
        '  "rev-parse HEAD") echo ' + sha + ";;\n"
        '  "rev-list -n 1 refs/tags/mcp-server-v4.5.0^{commit}") '
        '[ "$TAG_PRESENT" = yes ] || exit 91; echo ' + tag_sha + ";;\n"
        "  *) exit 91;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (bin_dir / "node").write_text("#!/bin/sh\necho 4.5.0\n", encoding="utf-8")
    invoked = tmp_path / "gh-invoked"
    (bin_dir / "gh").write_text(
        '#!/bin/sh\necho yes > "$GH_INVOKED"\necho ' + sha + "\n",
        encoding="utf-8",
    )
    for executable in bin_dir.iterdir():
        executable.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "GH_INVOKED": str(invoked),
        "GITHUB_REPOSITORY": "oaslananka/kicad-mcp-pro",
        "RELEASE_TAG": "mcp-server-v4.5.0",
        "VERSION": "4.5.0",
        "PREPARE_SOURCE": sha if prepare else "",
        "TAG_PRESENT": "yes" if tag_exists else "no",
    }
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", source["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, invoked.exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX Bash fixture; release workflow runs on Ubuntu",
)
def test_prepare_does_not_require_a_github_release(tmp_path: Path) -> None:
    code, invoked = _simulate_source_step(tmp_path, prepare=True)
    assert code == 0
    assert invoked is False


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX Bash fixture; release workflow runs on Ubuntu",
)
def test_empty_source_is_rejected_without_release_lookup(tmp_path: Path) -> None:
    code, invoked = _simulate_source_step(tmp_path, prepare=False)
    assert code != 0
    assert invoked is False


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX Bash fixture; release workflow runs on Ubuntu",
)
def test_prepare_rejects_tag_source_mismatch_before_gh_lookup(tmp_path: Path) -> None:
    code, invoked = _simulate_source_step(tmp_path, prepare=True, matching=False)
    assert code != 0
    assert invoked is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash fixture; release workflow runs on Ubuntu")
def test_mcpb_missing_tag_rejected_even_when_branch_has_same_name(tmp_path: Path) -> None:
    # A local refs/heads/mcp-server-v4.5.0 does not substitute for refs/tags/...
    code, invoked = _simulate_source_step(tmp_path, prepare=True, tag_exists=False)
    assert code != 0
    assert invoked is False
