from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.check_github_actions_policy import has_sha_pinned_action

ROOT = Path(__file__).resolve().parents[2]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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


def test_lefthook_is_pinned_and_lifecycle_is_explicitly_allowed() -> None:
    package = __import__("json").loads((ROOT / "package.json").read_text(encoding="utf-8"))
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))

    lefthook_version = package["devDependencies"]["lefthook"]
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", lefthook_version)
    assert package["scripts"]["hooks:install"] == "python scripts/install_git_hooks.py"
    assert package["scripts"]["hooks:pre-commit"] == "lefthook run pre-commit"
    assert package["scripts"]["hooks:pre-push"] == "lefthook run pre-push"
    assert workspace["allowBuilds"] == {"lefthook": True}


def test_lefthook_owns_fast_pre_commit_and_targeted_pre_push() -> None:
    config = yaml.safe_load((ROOT / "lefthook.yml").read_text(encoding="utf-8"))

    assert config["lefthook"] == "node_modules/.bin/lefthook"
    assert set(config) >= {"lefthook", "pre-commit", "pre-push"}

    pre_commit = config["pre-commit"]["commands"]
    assert set(pre_commit) == {"fast"}
    assert pre_commit["fast"]["run"] == (
        "python3 scripts/run_uv.py tool run pre-commit run "
        "--hook-stage pre-commit --files {staged_files}"
    )

    pre_push = config["pre-push"]["commands"]
    assert set(pre_push) == {"targeted"}
    assert pre_push["targeted"]["run"] == (
        "python3 scripts/run_uv.py run --all-extras python "
        "scripts/hook_pre_push.py --base origin/main"
    )


def test_pre_commit_catalog_contains_fast_checks_only() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))

    hook_ids = {hook["id"] for repo in config["repos"] for hook in repo["hooks"]}
    assert "gitleaks" in hook_ids
    assert "ruff-format" in hook_ids
    assert "ruff" in hook_ids
    assert "mixed-line-ending" in hook_ids

    for repo in config["repos"]:
        assert repo["repo"] != "local"
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
        "protocol-schemas, mcp-2026-compat, workflow-policy, security, release-readiness]"
        in workflow
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

    assert "pull_request_target" not in raw
    classify = workflow["jobs"]["classify"]
    assert "sonar-mode.outputs.run_analysis" in classify["outputs"]["run_analysis"]
    assert "sonar-mode.outputs.no_op_reason" in classify["outputs"]["no_op_reason"]

    mode_step = next(step for step in classify["steps"] if step.get("id") == "sonar-mode")
    mode_script = mode_step["run"]
    assert "PR_HEAD_REPO" in mode_script
    assert "PR_AUTHOR" in mode_script
    assert "dependabot[bot]" in mode_script
    assert "run_analysis=false" in mode_script

    sonar = workflow["jobs"]["sonarcloud"]
    assert "needs.classify.result == 'success'" in sonar["if"]
    steps = {step["name"]: step for step in sonar["steps"] if "name" in step}
    assert steps["Record intentional Sonar no-op"]["if"] == (
        "needs.classify.outputs.run_analysis != 'true'"
    )
    for step_name in ("Checkout code", "Run tests with coverage", "SonarCloud Scan"):
        assert steps[step_name]["if"] == "needs.classify.outputs.run_analysis == 'true'"


def test_sonar_skips_release_metadata_only_change_sets() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "sonarcloud.yml").read_text(encoding="utf-8")
    )

    classify = workflow["jobs"]["classify"]
    assert (
        "release-classifier.outputs.release_metadata_only"
        in classify["outputs"]["release_metadata_only"]
    )
    assert "sonar-mode.outputs.run_analysis" in classify["outputs"]["run_analysis"]

    mode_step = next(step for step in classify["steps"] if step.get("id") == "sonar-mode")
    assert "RELEASE_METADATA_ONLY" in mode_step["env"]
    assert "release-metadata-only change set" in mode_step["run"]

    sonar = workflow["jobs"]["sonarcloud"]
    assert sonar["needs"] == "classify"
    assert "always()" in sonar["if"]
    assert "needs.classify.result == 'success'" in sonar["if"]


def test_full_python_suite_setup_is_shared_without_cross_workflow_artifacts() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    sonar = (ROOT / ".github" / "workflows" / "sonarcloud.yml").read_text(encoding="utf-8")
    action = (ROOT / ".github" / "actions" / "python-full-suite" / "action.yml").read_text(
        encoding="utf-8"
    )

    local_action = "uses: ./.github/actions/python-full-suite"
    _require(local_action in ci, "CI coverage must use the shared full-suite action")
    _require(local_action in sonar, "Sonar must use the shared full-suite action")
    _require(
        "astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7" in action,
        "shared action must pin setup-uv",
    )
    _require(
        "uv sync --all-extras --frozen" in action,
        "shared action must sync the locked full environment",
    )
    _require(
        "uv run python scripts/run_pytest.py" in action,
        "shared action must own the full-suite command",
    )
    _require(
        "cross-workflow artifact reuse" in sonar,
        "Sonar must remain an independent full-suite execution",
    )


def test_gitleaks_binary_download_is_sha256_verified() -> None:
    workflow = (ROOT / ".github" / "workflows" / "gitleaks.yml").read_text(encoding="utf-8")

    _require("GITLEAKS_VERSION: v8.30.1" in workflow, "Gitleaks version must stay pinned")
    _require(
        (
            "GITLEAKS_LINUX_X64_SHA256: "
            "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
        )
        in workflow,
        "Gitleaks Linux x64 release checksum must be pinned",
    )
    _require(
        "sha256sum --check --strict" in workflow,
        "Gitleaks archive checksum must be verified before extraction",
    )
    _require(
        "gitleaks_${GITLEAKS_VERSION#v}_linux_x64.tar.gz" in workflow,
        "checksum must cover the downloaded Linux x64 archive",
    )


def test_live_model_workflows_install_opencode_from_lockfile() -> None:
    opencode_workflows = [
        ROOT / ".github" / "workflows" / "live-model-assurance.yml",
        ROOT / ".github" / "workflows" / "live-model-eval.yml",
    ]
    release_gate = ROOT / ".github" / "workflows" / "live-model-release-gate.yml"

    for path in opencode_workflows:
        raw = path.read_text(encoding="utf-8")
        assert "npm install --global" not in raw
        assert "npm ci --prefix evals/live --ignore-scripts --no-audit --no-fund" in raw
        assert "evals/live/node_modules/opencode-linux-x64/bin/opencode --version" in raw

    assert "npm install --global" not in release_gate.read_text(encoding="utf-8")
    assert "opencode-linux-x64" not in release_gate.read_text(encoding="utf-8")

    package = (ROOT / "evals" / "live" / "package.json").read_text(encoding="utf-8")
    lockfile = (ROOT / "evals" / "live" / "package-lock.json").read_text(encoding="utf-8")
    assert '"opencode-linux-x64": "1.18.10"' in package
    assert '"opencode-ai"' not in package
    assert '"lockfileVersion": 3' in lockfile


def test_live_model_workflows_expose_locked_opencode_binary_on_path() -> None:
    live_workflows = [
        ROOT / ".github" / "workflows" / "live-model-assurance.yml",
        ROOT / ".github" / "workflows" / "live-model-eval.yml",
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


def test_root_tooling_changes_trigger_repository_contract_suite() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    changes = workflow["jobs"]["changes"]
    path_filter = next(step for step in changes["steps"] if step.get("id") == "filter")
    filters = yaml.safe_load(path_filter["with"]["filters"])

    expected_inputs = {
        "package.json",
        "pnpm-workspace.yaml",
        "lefthook.yml",
        ".pre-commit-config.yaml",
        "Taskfile.yml",
        ".mergify.yml",
        ".github/dependabot.yml",
        ".github/rulesets/**",
        "sonar-project.properties",
        "AGENTS.md",
        "**/AGENTS.md",
    }
    assert expected_inputs <= set(filters["repo_tooling"])
    assert changes["outputs"]["repo_tooling"] == "${{ steps.filter.outputs.repo_tooling }}"

    server_skip = next(
        step
        for step in workflow["jobs"]["mcp-server"]["steps"]
        if step.get("name") == "Skip mcp-server when unaffected or redundant"
    )
    coverage_skip = next(
        step
        for step in workflow["jobs"]["coverage"]["steps"]
        if step.get("name") == "Skip full coverage when Python is unaffected"
    )
    for skip_step in (server_skip, coverage_skip):
        assert "needs.changes.outputs.repo_tooling != 'true'" in skip_step["if"]


def test_path_aware_skip_steps_use_bash_on_cross_platform_matrix_jobs() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )

    for job_name in ("mcp-server", "mcp-npm"):
        steps = workflow["jobs"][job_name]["steps"]
        skip_step = next(
            step
            for step in steps
            if step.get("name")
            in {
                "Skip mcp-server when unaffected or redundant",
                "Skip mcp-npm when unaffected or redundant",
            }
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
