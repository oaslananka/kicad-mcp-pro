"""Python workflow-call preparation is source-bound and cannot publish (#1179)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/prepare-python.yml"
LEGACY = ROOT / ".github/workflows/publish-python.yml"
TAG = "mcp-server-v4.4.0"
SHA = "a" * 40


def _workflow() -> dict:
    config = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    return config


def test_exact_reusable_inputs_and_published_legacy_events() -> None:
    wf = _workflow()
    on = wf[True]
    assert set(on["workflow_call"]["inputs"]) == {"tag", "source_commit"}
    for config in on["workflow_call"]["inputs"].values():
        assert config["type"] == "string"
        assert config["required"] is True
    assert set(on) == {"workflow_call"}
    previous = yaml.safe_load(LEGACY.read_text(encoding="utf-8"))[True]
    assert previous["workflow_dispatch"] is None
    assert previous["release"]["types"] == ["published"]
    assert "push" not in previous
    assert "workflow_call" not in previous


def test_prepare_mode_is_allowed_only_on_main_with_approved_source() -> None:
    build = _workflow()["jobs"]["build"]
    condition = build["if"]
    assert "inputs.source_commit != ''" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.repository == 'oaslananka/kicad-mcp-pro'" in condition
    assert "startsWith(inputs.tag, 'mcp-server-v')" in condition
    assert "inputs.source_commit == ''" not in condition
    assert "github.event_name" not in condition
    assert build["permissions"]["contents"] == "read"
    assert "environment" not in build


def test_source_guard_runs_immediately_after_checkout_and_before_repo_code() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    checkout = next(i for i, s in enumerate(steps) if "actions/checkout@" in s.get("uses", ""))
    identity = next(
        i
        for i, s in enumerate(steps)
        if s.get("name") == "Verify reusable preparation source identity"
    )
    setup = next(i for i, s in enumerate(steps) if "astral-sh/setup-uv@" in s.get("uses", ""))
    assert identity == checkout + 1
    assert identity < setup
    guard = steps[identity]
    assert "if" not in guard
    assert guard["env"] == {
        "EXPECTED_TAG": "$" + "{{ inputs.tag }}",
        "EXPECTED_SOURCE": "$" + "{{ inputs.source_commit }}",
        "CALLER_SHA": "$" + "{{ github.sha }}",
        "CALLER_REF": "$" + "{{ github.ref }}",
    }
    script = guard["run"]
    assert 'checked_out="$(git rev-parse HEAD)" || exit 1' in script
    assert '[[ "$checked_out" == "$EXPECTED_SOURCE" ]] || exit 1' in script
    for condition in (
        '[[ "$EXPECTED_TAG" =~ ^mcp-server-v',
        '[[ "$EXPECTED_SOURCE" =~ ^[0-9a-f]{40}$ ]]',
        '[[ "$CALLER_REF" == "refs/heads/main" ]]',
        '[[ "$CALLER_SHA" == "$EXPECTED_SOURCE" ]]',
        '[[ "$tagged_source" == "$EXPECTED_SOURCE" ]]',
        '[[ "$EXPECTED_TAG" == "mcp-server-v$expected_version" ]]',
    ):
        assert any(
            line.strip().startswith(condition) and line.endswith("|| exit 1")
            for line in script.splitlines()
        )
    assert '[[ "$tagged_source" == "$EXPECTED_SOURCE" ]]' in script
    assert '[[ "$CALLER_SHA" == "$EXPECTED_SOURCE" ]]' in script
    assert '[[ "$CALLER_REF" == "refs/heads/main" ]]' in script
    assert '[[ "$EXPECTED_TAG" == "mcp-server-v$expected_version" ]]' in script


def test_no_registry_or_github_release_writes_in_prepare_mode() -> None:
    wf = _workflow()
    jobs = wf["jobs"]
    assert set(jobs) == {"build"}
    assert "pypa/gh-action-pypi-publish" not in WORKFLOW.read_text(encoding="utf-8")
    assert "gh release" not in WORKFLOW.read_text(encoding="utf-8")
    assert "environment:" not in WORKFLOW.read_text(encoding="utf-8")
    assert "pypa/gh-action-pypi-publish" in LEGACY.read_text(encoding="utf-8")
    assert "scripts.attach_published_release_assets" not in WORKFLOW.read_text(encoding="utf-8")
    assert "scripts.attach_published_release_assets" in LEGACY.read_text(encoding="utf-8")
    build = jobs["build"]["steps"]
    attest = [s for s in build if str(s.get("uses", "")).startswith("actions/attest@")]
    uploads = [s for s in build if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(attest) == 2
    assert len(uploads) == 2
    assert next(s for s in build if s.get("name") == "Attest Python SLSA build provenance")
    assert next(s for s in build if s.get("name") == "Attest Python distributions")


def _run_python_source_guard(
    tmp_path: Path,
    workflow: Path,
    step_name: str,
    variables: dict[str, str],
    *,
    version: str = "4.4.0",
) -> tuple[int, str]:
    """Exercise either reviewed workflow guard with no ambient credentials."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text(
        f'[project]\nname = "kicad-mcp-pro"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    git.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  "rev-parse HEAD") printf "%s\\n" "$MOCK_HEAD";;\n'
        '  "rev-list -n 1 refs/tags/"*|"rev-list -n1 refs/tags/"*) '
        'printf "%s\\n" "$MOCK_TAG_SOURCE";;\n'
        "  *) exit 91;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    gh = fake_bin / "gh"
    gh.write_text(
        '#!/bin/sh\n[ "$1" = api ] || exit 2\n'
        '[ "$2" = "repos/oaslananka/kicad-mcp-pro/releases/42" ] || exit 2\n'
        '[ "$API_FAILURE" != true ] || exit 1\n'
        'printf \'{"id":%s,"tag_name":"%s","draft":%s,"published_at":%s}\\n\' '
        '"$API_ID" "$API_TAG" "$API_DRAFT" "$API_PUBLISHED"\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    (fake_bin / "python3").symlink_to(Path(sys.executable).resolve())
    jq = shutil.which("jq")
    if jq:
        (fake_bin / "jq").symlink_to(Path(jq).resolve())
    config = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    guard = next(s["run"] for s in config["jobs"]["build"]["steps"] if s.get("name") == step_name)
    env = {
        "PATH": str(fake_bin) + os.pathsep + os.defpath,
        "HOME": str(tmp_path),
        "LANG": "C",
        **variables,
    }
    proc = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", guard],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return proc.returncode, proc.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX Bash-only Actions workflow")
@pytest.mark.parametrize(
    ("tag", "source_sha", "caller_sha", "checkout_sha", "tag_sha", "ref", "pass_expected"),
    [
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/main", True),
        (TAG, SHA, "b" * 40, SHA, SHA, "refs/heads/main", False),
        (TAG, SHA, SHA, "b" * 40, SHA, "refs/heads/main", False),
        (TAG, SHA, SHA, SHA, "b" * 40, "refs/heads/main", False),
        (TAG, SHA, SHA, SHA, SHA, "refs/heads/feature", False),
        ("mcp-server-v4.4.1", SHA, SHA, SHA, SHA, "refs/heads/main", False),
        ("mcp-server-v4.4.0-rc1", SHA, SHA, SHA, SHA, "refs/heads/main", False),
        (TAG, "invalid", SHA, SHA, SHA, "refs/heads/main", False),
    ],
)
def test_bash_source_identity_accepts_only_matching_protected_identity(
    tmp_path: Path,
    tag: str,
    source_sha: str,
    caller_sha: str,
    checkout_sha: str,
    tag_sha: str,
    ref: str,
    pass_expected: bool,
) -> None:
    exit_code, stderr = _run_python_source_guard(
        tmp_path,
        WORKFLOW,
        "Verify reusable preparation source identity",
        {
            "EXPECTED_TAG": tag,
            "EXPECTED_SOURCE": source_sha,
            "CALLER_SHA": caller_sha,
            "CALLER_REF": ref,
            "MOCK_HEAD": checkout_sha,
            "MOCK_TAG_SOURCE": tag_sha,
        },
    )
    assert (exit_code == 0) is pass_expected, stderr


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
def test_published_release_guard_fails_closed(tmp_path: Path, case: str, expected: bool) -> None:
    tag = "mcp-server-v4.22.6"
    variables = {
        "GITHUB_REPOSITORY": "oaslananka/kicad-mcp-pro",
        "RELEASE_ID": "42",
        "RELEASE_TAG": tag,
        "EXPECTED_SHA": SHA,
        "EXPECTED_REF": "refs/tags/" + tag,
        "MOCK_TAG_SOURCE": SHA,
        "MOCK_HEAD": SHA,
        "API_ID": "42",
        "API_TAG": tag,
        "API_DRAFT": "false",
        "API_PUBLISHED": '"2026-11-25T12:00:00Z"',
        "API_FAILURE": "false",
    }
    variants = {
        "draft": ("API_DRAFT", "true"),
        "unpublished": ("API_PUBLISHED", "null"),
        "wrong-id": ("API_ID", "43"),
        "wrong-tag": ("API_TAG", "mcp-server-v4.22.5"),
        "wrong-ref": ("EXPECTED_REF", "refs/heads/main"),
        "wrong-source": ("MOCK_TAG_SOURCE", "b" * 40),
        "wrong-checkout": ("MOCK_HEAD", "b" * 40),
        "api-failure": ("API_FAILURE", "true"),
        "invalid-id": ("RELEASE_ID", "../42"),
    }
    if case in variants:
        key, value = variants[case]
        variables[key] = value
    exit_code, stderr = _run_python_source_guard(
        tmp_path,
        LEGACY,
        "Verify published release source",
        variables,
        version="4.22.5" if case == "wrong-version" else "4.22.6",
    )
    assert (exit_code == 0) is expected, stderr
