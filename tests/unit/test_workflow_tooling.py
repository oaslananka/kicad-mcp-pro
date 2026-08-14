from __future__ import annotations

from pathlib import Path

import yaml

from scripts.check_github_actions_policy import has_sha_pinned_action

ROOT = Path(__file__).resolve().parents[2]


def test_actionlint_is_a_locked_python_dev_tool() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    checker = (ROOT / "scripts" / "check_workflows.py").read_text(encoding="utf-8")

    assert '"actionlint-py==1.7.12.24"' in pyproject
    assert '"shellcheck-py==0.11.0.1"' in pyproject
    assert 'ACTIONLINT_COMMAND = ["actionlint"]' in checker
    assert "kicadstudio" not in checker


def test_pre_commit_uses_one_targeted_pre_push_gate() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    local = next(repo for repo in config["repos"] if repo["repo"] == "local")
    hooks = {hook["id"]: hook for hook in local["hooks"]}

    assert set(hooks) == {"targeted-pre-push"}
    targeted = hooks["targeted-pre-push"]
    assert targeted["stages"] == ["pre-push"]
    assert targeted["always_run"] is True
    assert targeted["pass_filenames"] is False
    assert targeted["language"] == "python"
    assert targeted["entry"] == (
        "python scripts/run_uv.py run --all-extras python scripts/hook_pre_push.py"
    )

    config_text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "scripts/run_pytest.py unit" not in config_text
    assert "cargo check" not in config_text
    assert "workflow_security.py" not in config_text


def test_standard_hooks_run_only_at_pre_commit() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))

    for repo in config["repos"]:
        if repo["repo"] == "local":
            continue
        for hook in repo["hooks"]:
            assert hook["stages"] == ["pre-commit"]


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
        "needs: [changes, mcp-server, coverage, mcp-npm, chatgpt-app, protocol-schemas, "
        "mcp-2026-compat, workflow-policy, security]" in workflow
    )


def test_direct_javascript_actions_use_node24_releases() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )

    assert has_sha_pinned_action(workflows, "dorny/paths-filter")
    assert "dorny/paths-filter@de90cc6fb38fc0963ad72b210f1f284cd68cea36" not in workflows
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" not in workflows


def test_sonar_source_and_test_scopes_are_disjoint() -> None:
    raw = (ROOT / "sonar-project.properties").read_text(encoding="utf-8")
    logical = raw.replace("\\\n", "")
    properties: dict[str, list[str]] = {}
    for line in logical.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        properties[key] = [item.strip() for item in value.split(",") if item.strip()]

    exclusions = properties["sonar.exclusions"]
    assert "packages/protocol-schemas/test/**" in exclusions
    assert "packages/kicad-fixtures/test/**" in exclusions
    assert "sonar.test.exclusions" not in properties
