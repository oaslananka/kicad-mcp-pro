"""A tag alone is not publication authority for the legacy Python workflow."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TAG = "mcp-server-v4.22.6"
SHA = "a" * 40


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/publish-python.yml").read_text())


def test_release_guard_precedes_build_and_oidc_publication() -> None:
    jobs = _workflow()["jobs"]
    steps = jobs["build"]["steps"]
    guard = steps[1]
    assert guard["name"] == "Verify published release source"
    assert guard["if"] == "github.event_name == 'release'"
    assert "github.event.release.id" in guard["env"]["RELEASE_ID"]
    assert "github.sha" in guard["env"]["EXPECTED_SHA"]
    assert "github.ref" in guard["env"]["EXPECTED_REF"]
    assert "github.event.release.tag_name" in guard["env"]["RELEASE_TAG"]
    assert "github.event.release.draft == false" in jobs["build"]["if"]
    assert "github.event.release.draft == false" in jobs["publish-pypi"]["if"]
    assert "github.event_name == 'release'" in jobs["publish-pypi"]["if"]
    assert jobs["publish-pypi"]["needs"] == "build"
    assert jobs["publish-pypi"]["environment"]["name"] == "pypi"
    assert "github.event_name == 'workflow_dispatch'" in jobs["publish-testpypi"]["if"]
    assert "github.event_name == 'release'" not in jobs["publish-testpypi"]["if"]


@pytest.mark.skipif(
    os.name == "nt" or not shutil.which("bash") or not shutil.which("jq"),
    reason="Bash and jq required",
)
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("published", True),
        ("draft", False),
        ("unpublished", False),
        ("wrong-id", False),
        ("wrong-tag", False),
        ("wrong-ref", False),
        ("wrong-source", False),
        ("wrong-checkout", False),
        ("wrong-version", False),
        ("api-failure", False),
        ("invalid-id", False),
    ],
)
def test_actual_guard_shell_fails_closed(tmp_path: Path, case: str, expected: bool) -> None:
    guard = _workflow()["jobs"]["build"]["steps"][1]["run"]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="4.22.6"\n')
    git = bin_dir / "git"
    git.write_text(
        '#!/bin/sh\ncase "$1" in\nrev-list) echo "$TAG_SHA";;\n'
        'rev-parse) echo "$CHECKOUT_SHA";;\n*) exit 2;;\nesac\n'
    )
    gh = bin_dir / "gh"
    gh.write_text(
        '#!/bin/sh\n[ "$1" = api ] || exit 2\n'
        '[ "$2" = "repos/oaslananka/kicad-mcp-pro/releases/42" ] || exit 2\n'
        '[ "$API_FAILURE" != true ] || exit 1\n'
        'printf \'{"id":%s,"tag_name":"%s","draft":%s,"published_at":%s}\\n\' '
        '"$API_ID" "$API_TAG" "$API_DRAFT" "$API_PUBLISHED"\n'
    )
    git.chmod(0o700)
    gh.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "GITHUB_REPOSITORY": "oaslananka/kicad-mcp-pro",
        "RELEASE_ID": "42",
        "RELEASE_TAG": TAG,
        "EXPECTED_SHA": SHA,
        "EXPECTED_REF": "refs/tags/" + TAG,
        "TAG_SHA": SHA,
        "CHECKOUT_SHA": SHA,
        "API_ID": "42",
        "API_TAG": TAG,
        "API_DRAFT": "false",
        "API_PUBLISHED": '"2026-11-25T12:00:00Z"',
        "API_FAILURE": "false",
        "GH_TOKEN": "fake-only",
    }
    variants = {
        "draft": ("API_DRAFT", "true"),
        "unpublished": ("API_PUBLISHED", "null"),
        "wrong-id": ("API_ID", "43"),
        "wrong-tag": ("API_TAG", "mcp-server-v4.22.5"),
        "wrong-ref": ("EXPECTED_REF", "refs/heads/main"),
        "wrong-source": ("TAG_SHA", "b" * 40),
        "wrong-checkout": ("CHECKOUT_SHA", "b" * 40),
        "api-failure": ("API_FAILURE", "true"),
        "invalid-id": ("RELEASE_ID", "../42"),
    }
    if case in variants:
        key, value = variants[case]
        env[key] = value
    if case == "wrong-version":
        (tmp_path / "pyproject.toml").write_text('[project]\nversion="4.22.5"\n')
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "-c", guard],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode == 0) is expected, result.stderr
