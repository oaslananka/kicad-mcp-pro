from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_actionlint_is_a_locked_python_dev_tool() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    checker = (ROOT / "scripts" / "check_workflows.py").read_text(encoding="utf-8")

    assert '"actionlint-py==1.7.12.24"' in pyproject
    assert '"shellcheck-py==0.11.0.1"' in pyproject
    assert 'ACTIONLINT_COMMAND = ["actionlint"]' in checker
    assert "kicadstudio" not in checker


def test_pre_commit_keeps_heavy_tests_on_pre_push() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    local = next(repo for repo in config["repos"] if repo["repo"] == "local")
    hooks = {hook["id"]: hook for hook in local["hooks"]}

    assert hooks["unit-tests"]["stages"] == ["pre-push"]
    assert "scripts/run_pytest.py unit" in hooks["unit-tests"]["entry"]
    assert hooks["workflow-policy"]["pass_filenames"] is False
    assert hooks["actionlint"]["pass_filenames"] is False
    assert hooks["zizmor"]["pass_filenames"] is False
    assert re.search(hooks["workflow-policy"]["files"], ".github/actions-policy.json")
    assert re.search(hooks["actionlint"]["files"], ".github/workflows/ci.yml")
    assert re.search(hooks["zizmor"]["files"], ".github/workflows/ci.yaml")
    assert "--locked" not in hooks["tauri-cargo-check"]["entry"]


def test_mixed_line_endings_are_normalized() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    standard = next(repo for repo in config["repos"] if repo["repo"].endswith("pre-commit-hooks"))
    hook = next(hook for hook in standard["hooks"] if hook["id"] == "mixed-line-ending")

    assert hook["args"] == ["--fix=lf"]


def test_workflow_policy_runs_actionlint_and_zizmor_in_required_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "scripts/check_workflows.py --actionlint" in workflow
    assert "scripts/workflow_security.py --min-severity high" in workflow
    assert (
        "needs: [changes, mcp-server, coverage, mcp-npm, protocol-schemas, "
        "mcp-2026-compat, workflow-policy, security]" in workflow
    )


def test_direct_javascript_actions_use_node24_releases() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )

    assert "dorny/paths-filter@fbd0ab8f3e69293af611ebaee6363fc25e6d187d" in workflows
    assert "dorny/paths-filter@de90cc6fb38fc0963ad72b210f1f284cd68cea36" not in workflows
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" not in workflows
