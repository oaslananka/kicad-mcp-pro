from __future__ import annotations

from pathlib import Path

import yaml

from scripts.check_github_actions_policy import has_sha_pinned_action

ROOT = Path(__file__).resolve().parents[2]


def _sonar_properties() -> dict[str, list[str]]:
    raw = (ROOT / "sonar-project.properties").read_text(encoding="utf-8")
    logical = raw.replace("\\\n", "")
    properties: dict[str, list[str]] = {}
    for line in logical.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        properties[key] = [item.strip() for item in value.split(",") if item.strip()]
    return properties


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
        "needs: [changes, release-metadata, mcp-server, coverage, mcp-npm, chatgpt-app, "
        "protocol-schemas, mcp-2026-compat, workflow-policy, security]" in workflow
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
    properties = _sonar_properties()

    exclusions = properties["sonar.exclusions"]
    assert "packages/protocol-schemas/test/**" in exclusions
    assert "packages/kicad-fixtures/test/**" in exclusions
    assert "**/*.png" in exclusions
    assert "sonar.test.exclusions" not in properties


def test_sonar_excludes_package_test_runners_from_coverage() -> None:
    properties = _sonar_properties()

    exclusions = properties["sonar.coverage.exclusions"]
    assert "packages/kicad-fixtures/scripts/run-tests.cjs" in exclusions
    assert "packages/protocol-schemas/scripts/run-tests.cjs" in exclusions


def test_sonar_s8541_exception_is_limited_to_github_workflows() -> None:
    raw = (ROOT / "sonar-project.properties").read_text(encoding="utf-8")

    assert "sonar.issue.ignore.multicriteria.e1.ruleKey=githubactions:S8541" in raw
    assert "sonar.issue.ignore.multicriteria.e1.resourceKey=.github/workflows/**" in raw
    assert "sonar.issue.ignore.multicriteria.e1.resourceKey=**\n" not in raw


def test_sonar_skips_fork_pull_requests_before_secret_bearing_steps() -> None:
    path = ROOT / ".github" / "workflows" / "sonarcloud.yml"
    raw = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    condition = workflow["jobs"]["sonarcloud"]["if"]

    assert "pull_request_target" not in raw
    assert "github.event_name != 'pull_request'" in condition
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition
    assert "github.event.pull_request.user.login != 'dependabot[bot]'" in condition


def test_live_model_workflows_install_opencode_from_lockfile() -> None:
    live_workflows = [
        ROOT / ".github" / "workflows" / "live-model-assurance.yml",
        ROOT / ".github" / "workflows" / "live-model-eval.yml",
        ROOT / ".github" / "workflows" / "live-model-release-gate.yml",
    ]

    for path in live_workflows:
        raw = path.read_text(encoding="utf-8")
        assert "npm install --global" not in raw
        assert "npm ci --prefix evals/live --ignore-scripts --no-audit --no-fund" in raw
        assert "evals/live/node_modules/opencode-linux-x64/bin/opencode --version" in raw

    package = (ROOT / "evals" / "live" / "package.json").read_text(encoding="utf-8")
    lockfile = (ROOT / "evals" / "live" / "package-lock.json").read_text(encoding="utf-8")
    assert '"opencode-linux-x64": "1.18.10"' in package
    assert '"opencode-ai"' not in package
    assert '"lockfileVersion": 3' in lockfile


def test_live_model_workflows_expose_locked_opencode_binary_on_path() -> None:
    live_workflows = [
        ROOT / ".github" / "workflows" / "live-model-assurance.yml",
        ROOT / ".github" / "workflows" / "live-model-eval.yml",
        ROOT / ".github" / "workflows" / "live-model-release-gate.yml",
    ]
    expected = (
        'echo "$GITHUB_WORKSPACE/evals/live/node_modules/opencode-linux-x64/bin" >> "$GITHUB_PATH"'
    )

    for path in live_workflows:
        raw = path.read_text(encoding="utf-8")
        install_count = raw.count(
            "npm ci --prefix evals/live --ignore-scripts --no-audit --no-fund"
        )
        assert install_count > 0
        assert raw.count(expected) == install_count


def test_docs_only_skip_steps_use_bash_on_cross_platform_matrix_jobs() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )

    for job_name in ("mcp-server", "mcp-npm"):
        steps = workflow["jobs"][job_name]["steps"]
        skip_step = next(
            step for step in steps if step.get("name") == "Skip heavy CI for docs-only PR"
        )
        assert skip_step["shell"] == "bash"


def test_ci_fails_fast_on_public_metadata_drift_before_heavy_jobs() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]

    metadata_gate = jobs["release-metadata"]
    metadata_commands = "\n".join(
        str(step.get("run", "")) for step in metadata_gate["steps"] if isinstance(step, dict)
    )
    assert "scripts/sync_mcp_metadata.py --check" in metadata_commands

    gated_jobs = {
        "mcp-server",
        "coverage",
        "mcp-2026-compat",
        "mcp-npm",
        "chatgpt-app",
        "protocol-schemas",
        "workflow-policy",
        "security",
    }
    for job_name in gated_jobs:
        job = jobs[job_name]
        needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
        assert "release-metadata" in needs
        assert "needs.release-metadata.result == 'success'" in job["if"]

    required_gate_needs = jobs["required-pr-gate"]["needs"]
    assert "release-metadata" in required_gate_needs
    required_gate_script = jobs["required-pr-gate"]["steps"][0]["run"]
    assert '[release-metadata]="${{ needs.release-metadata.result }}"' in required_gate_script


def test_generated_package_test_output_is_not_repository_source() -> None:
    properties = _sonar_properties()
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "**/dist-test/**" in properties["sonar.exclusions"]
    assert "packages/protocol-schemas/dist-test/" in gitignore
