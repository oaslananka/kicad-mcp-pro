"""Risk-based live-model assurance policy tests."""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path
from shutil import which

import pytest
import yaml

from kicad_mcp.evals.release_policy import (
    ReleasePolicyError,
    contract_changed_between,
    evaluate_release_readiness,
    load_baseline_metadata,
    load_release_policy,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "evals/live/release-policy.yaml"
BASELINE_PATH = ROOT / "evals/live/baselines.yaml"


def _git(repo: Path, *args: str) -> str:
    git = which("git")
    if git is None:
        raise RuntimeError("git executable unavailable")
    environment = os.environ.copy()
    for variable in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    ):
        environment.pop(variable, None)
    result = subprocess.run(
        [git, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Policy Test")
    _git(repo, "config", "user.email", "policy@example.invalid")
    (repo / "src/kicad_mcp/evals").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "src/kicad_mcp/evals/selector.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "docs/notes.md").write_text("# Notes\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "initial")
    return repo


def _tag_server_release(repo: Path, version: str = "1.0.0") -> str:
    tag = f"mcp-server-v{version}"
    _git(repo, "tag", tag)
    return tag


def _commit_contract(repo: Path, value: int) -> str:
    (repo / "src/kicad_mcp/evals/selector.py").write_text(f"VALUE = {value}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", f"contract {value}")
    return _git(repo, "rev-parse", "HEAD")


def _commit_docs(repo: Path, text: str = "# candidate") -> str:
    (repo / "docs/notes.md").write_text(f"{text}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "docs candidate")
    return _git(repo, "rev-parse", "HEAD")


def _policy(path: Path, *, max_age_days: int = 30) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "baseline_max_age_days": max_age_days,
                "release_pull_request_head": "release-please--branches--main",
                "release_tag_pattern": "mcp-server-v*",
                "minimum_smoke_configurations": 2,
                "smoke_configurations": ["alpha", "beta"],
                "agent_contract_paths": ["src/kicad_mcp/evals/**"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _baseline(
    path: Path,
    *,
    approved: bool,
    approved_at: str | None = None,
    source_revision: str | None = None,
    agent_contract_digest: str | None = None,
) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "approved": approved,
                "approved_at": approved_at,
                "source_revision": source_revision,
                "agent_contract_digest": agent_contract_digest,
                "evidence": {
                    "workflow_run_id": 123 if approved else None,
                    "aggregate_sha256": "a" * 64 if approved else None,
                },
                "minimum_repeats": 3,
                "required_configurations": ["alpha", "beta", "gamma"],
                "configurations": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_release_policy_rejects_duplicate_required_configurations(tmp_path: Path) -> None:
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=False)
    baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    baseline["required_configurations"] = ["alpha", "alpha"]
    baseline_path.write_text(yaml.safe_dump(baseline, sort_keys=False), encoding="utf-8")

    with pytest.raises(ReleasePolicyError, match="duplicates"):
        load_baseline_metadata(baseline_path)


def test_release_policy_rejects_empty_required_configurations(tmp_path: Path) -> None:
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=False)
    baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    baseline["required_configurations"] = []
    baseline_path.write_text(yaml.safe_dump(baseline, sort_keys=False), encoding="utf-8")

    with pytest.raises(ReleasePolicyError, match="non-empty"):
        load_baseline_metadata(baseline_path)


def test_release_policy_accepts_one_required_full_configuration(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    _tag_server_release(repo)
    _commit_contract(repo, 2)
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=False)
    baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    baseline["required_configurations"] = ["alpha"]
    baseline_path.write_text(yaml.safe_dump(baseline, sort_keys=False), encoding="utf-8")

    decision = evaluate_release_readiness(
        repo_root=repo,
        policy_path=_policy(tmp_path / "policy.yaml"),
        baseline_path=baseline_path,
        ref="HEAD",
        today=date(2026, 8, 2),
    )

    assert decision.mode == "full"
    assert decision.required_configurations == ("alpha",)
    assert decision.smoke_configurations == ("alpha", "beta")


def test_release_policy_accepts_two_required_configurations(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    release_tag = _tag_server_release(repo)
    _commit_contract(repo, 2)
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=False)
    baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    baseline["required_configurations"] = ["alpha", "beta"]
    baseline_path.write_text(yaml.safe_dump(baseline, sort_keys=False), encoding="utf-8")

    decision = evaluate_release_readiness(
        repo_root=repo,
        policy_path=_policy(tmp_path / "policy.yaml"),
        baseline_path=baseline_path,
        ref="HEAD",
        today=date(2026, 8, 2),
    )

    assert decision.mode == "full"
    assert decision.reason == "baseline_unapproved"
    assert decision.release_base_ref == release_tag
    assert decision.required_configurations == ("alpha", "beta")
    assert decision.smoke_configurations == ("alpha", "beta")


def test_release_policy_requires_release_tag_pattern(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy-missing-release-tag.yaml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "baseline_max_age_days": 30,
                "release_pull_request_head": "release-please--branches--main",
                "minimum_smoke_configurations": 2,
                "smoke_configurations": ["alpha", "beta"],
                "agent_contract_paths": ["src/kicad_mcp/evals/**"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReleasePolicyError, match="release_tag_pattern"):
        load_release_policy(policy_path)


def test_release_policy_rejects_empty_release_tag_pattern(tmp_path: Path) -> None:
    policy_path = _policy(tmp_path / "policy.yaml")
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    raw["release_tag_pattern"] = "   "
    policy_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ReleasePolicyError, match="release_tag_pattern must be a non-empty string"):
        load_release_policy(policy_path)


def test_release_policy_loads_smoke_configurations(tmp_path: Path) -> None:
    policy = load_release_policy(_policy(tmp_path / "policy.yaml"))

    assert policy.smoke_configurations == ("alpha", "beta")


def test_release_policy_rejects_duplicate_smoke_configurations(tmp_path: Path) -> None:
    policy_path = _policy(tmp_path / "policy.yaml")
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    raw["smoke_configurations"] = ["alpha", "alpha"]
    policy_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ReleasePolicyError, match="smoke_configurations.*duplicates"):
        load_release_policy(policy_path)


def test_release_policy_rejects_minimum_above_smoke_configuration_count(
    tmp_path: Path,
) -> None:
    policy_path = _policy(tmp_path / "policy.yaml")
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    raw["minimum_smoke_configurations"] = 3
    policy_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(ReleasePolicyError, match="cannot exceed smoke_configurations"):
        load_release_policy(policy_path)


def test_previous_release_resolver_skips_current_tag_and_version_sorts(tmp_path: Path) -> None:
    from kicad_mcp.evals.release_policy import resolve_previous_release_ref

    repo = _repository(tmp_path)
    policy = load_release_policy(_policy(tmp_path / "policy.yaml"))
    _git(repo, "tag", "mcp-server-v1.2.9")
    (repo / "docs/notes.md").write_text("# release 1.10\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "release 1.10")
    _git(repo, "tag", "-a", "mcp-server-v1.10.0", "-m", "release 1.10.0")
    (repo / "docs/notes.md").write_text("# candidate\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "candidate")
    _git(repo, "tag", "mcp-server-v1.11.0")

    assert resolve_previous_release_ref(repo, policy, candidate_ref="HEAD") == "mcp-server-v1.10.0"


def test_previous_release_resolver_fails_closed_without_prior_release(tmp_path: Path) -> None:
    from kicad_mcp.evals.release_policy import resolve_previous_release_ref

    repo = _repository(tmp_path)
    policy = load_release_policy(_policy(tmp_path / "policy.yaml"))

    with pytest.raises(ReleasePolicyError, match="previous.*release"):
        resolve_previous_release_ref(repo, policy, candidate_ref="HEAD")


def test_release_policy_allows_unapproved_baseline_when_release_contract_is_unchanged(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    release_tag = _tag_server_release(repo)
    _commit_docs(repo)
    policy_path = _policy(tmp_path / "policy.yaml")
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=False)

    decision = evaluate_release_readiness(
        repo_root=repo,
        policy_path=policy_path,
        baseline_path=baseline_path,
        ref="HEAD",
        today=date(2026, 8, 2),
    )

    assert decision.mode == "none"
    assert decision.reason == "no_agent_contract_change_since_release"
    assert decision.release_base_ref == release_tag
    assert decision.release_contract_changed is False


def test_release_policy_allows_stale_baseline_when_release_contract_is_unchanged(
    tmp_path: Path,
) -> None:
    from kicad_mcp.evals.release_policy import compute_agent_contract_digest

    repo = _repository(tmp_path)
    source_revision = _git(repo, "rev-parse", "HEAD")
    release_tag = _tag_server_release(repo)
    _commit_docs(repo)
    policy_path = _policy(tmp_path / "policy.yaml", max_age_days=30)
    policy = load_release_policy(policy_path)
    digest = compute_agent_contract_digest(repo, policy, ref=source_revision)
    baseline_path = _baseline(
        tmp_path / "baseline.yaml",
        approved=True,
        approved_at="2026-06-01",
        source_revision=source_revision,
        agent_contract_digest=digest,
    )

    decision = evaluate_release_readiness(
        repo_root=repo,
        policy_path=policy_path,
        baseline_path=baseline_path,
        ref="HEAD",
        today=date(2026, 8, 2),
    )

    assert decision.mode == "none"
    assert decision.reason == "no_agent_contract_change_since_release"
    assert decision.release_base_ref == release_tag
    assert decision.release_contract_changed is False


def test_release_policy_requires_full_gate_for_unapproved_changed_contract(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    release_tag = _tag_server_release(repo)
    _commit_contract(repo, 2)
    policy_path = _policy(tmp_path / "policy.yaml")
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=False)

    decision = evaluate_release_readiness(
        repo_root=repo,
        policy_path=policy_path,
        baseline_path=baseline_path,
        ref="HEAD",
        today=date(2026, 8, 2),
    )

    assert decision.mode == "full"
    assert decision.reason == "baseline_unapproved"
    assert decision.release_base_ref == release_tag
    assert decision.release_contract_changed is True


def test_release_policy_requires_full_gate_for_stale_changed_contract(
    tmp_path: Path,
) -> None:
    from kicad_mcp.evals.release_policy import compute_agent_contract_digest

    repo = _repository(tmp_path)
    release_tag = _tag_server_release(repo)
    candidate = _commit_contract(repo, 2)
    policy_path = _policy(tmp_path / "policy.yaml", max_age_days=30)
    policy = load_release_policy(policy_path)
    digest = compute_agent_contract_digest(repo, policy, ref=candidate)
    baseline_path = _baseline(
        tmp_path / "baseline.yaml",
        approved=True,
        approved_at="2026-06-01",
        source_revision=candidate,
        agent_contract_digest=digest,
    )

    decision = evaluate_release_readiness(
        repo_root=repo,
        policy_path=policy_path,
        baseline_path=baseline_path,
        ref="HEAD",
        today=date(2026, 8, 2),
    )

    assert decision.mode == "full"
    assert decision.reason == "baseline_stale"
    assert decision.baseline_age_days == 62
    assert decision.release_base_ref == release_tag
    assert decision.release_contract_changed is True


def test_release_policy_allows_smoke_for_fresh_matching_baseline_after_contract_change(
    tmp_path: Path,
) -> None:
    from kicad_mcp.evals.release_policy import compute_agent_contract_digest

    repo = _repository(tmp_path)
    release_tag = _tag_server_release(repo)
    candidate = _commit_contract(repo, 2)
    policy_path = _policy(tmp_path / "policy.yaml")
    policy = load_release_policy(policy_path)
    digest = compute_agent_contract_digest(repo, policy, ref=candidate)
    baseline_path = _baseline(
        tmp_path / "baseline.yaml",
        approved=True,
        approved_at="2026-08-01",
        source_revision=candidate,
        agent_contract_digest=digest,
    )

    decision = evaluate_release_readiness(
        repo_root=repo,
        policy_path=policy_path,
        baseline_path=baseline_path,
        ref="HEAD",
        today=date(2026, 8, 2),
    )

    assert decision.mode == "smoke"
    assert decision.reason == "approved_baseline_reusable"
    assert decision.baseline_age_days == 1
    assert decision.current_contract_digest == digest
    assert decision.release_base_ref == release_tag
    assert decision.release_contract_changed is True


def test_contract_change_detection_ignores_non_agent_files(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    policy = load_release_policy(_policy(tmp_path / "policy.yaml"))
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "docs/notes.md").write_text("# Updated notes\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "docs only")
    docs_head = _git(repo, "rev-parse", "HEAD")

    assert contract_changed_between(repo, policy, base_ref=base, head_ref=docs_head) is False

    (repo / "src/kicad_mcp/evals/selector.py").write_text("VALUE = 3\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "agent contract")
    agent_head = _git(repo, "rev-parse", "HEAD")

    assert contract_changed_between(repo, policy, base_ref=docs_head, head_ref=agent_head) is True


def test_approved_baseline_requires_auditable_metadata(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    _tag_server_release(repo)
    _commit_contract(repo, 2)
    policy_path = _policy(tmp_path / "policy.yaml")
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=True)

    with pytest.raises(ReleasePolicyError, match="approved_at"):
        evaluate_release_readiness(
            repo_root=repo,
            policy_path=policy_path,
            baseline_path=baseline_path,
            ref="HEAD",
            today=date(2026, 8, 2),
        )


def test_committed_release_policy_tracks_model_facing_inputs_only() -> None:
    policy = load_release_policy(POLICY_PATH)

    assert policy.baseline_max_age_days == 30
    assert policy.release_pull_request_head == "release-please--branches--main"
    assert policy.release_tag_pattern == "mcp-server-v*"
    assert policy.minimum_smoke_configurations == 2
    assert policy.smoke_configurations == (
        "nvidia-nemotron-3-5-lightning-30b-a3b",
        "opencode-cli-mimo-v2-5-free",
    )
    assert "docs/tools-reference.generated.md" in policy.agent_contract_paths
    assert "evals/tool_selection/**" in policy.agent_contract_paths
    assert "evals/live/configurations.yaml" in policy.agent_contract_paths
    assert "src/kicad_mcp/evals/nvidia_nim_adapter.py" in policy.agent_contract_paths
    assert "src/kicad_mcp/evals/live_runner.py" in policy.agent_contract_paths
    assert "src/kicad_mcp/evals/release_policy.py" not in policy.agent_contract_paths
    assert "src/kicad_mcp/evals/smoke_assurance.py" not in policy.agent_contract_paths
    assert ".github/workflows/live-model-release-gate.yml" in policy.agent_contract_paths
    assert "evals/live/baselines.yaml" not in policy.agent_contract_paths

    baseline = yaml.safe_load(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["approved"] is True
    assert set(baseline["configurations"]) == set(baseline["required_configurations"])
    assert len(baseline["source_revision"]) == 40
    assert len(baseline["agent_contract_digest"]) == 64
    assert isinstance(baseline["evidence"]["workflow_run_id"], int)


def test_push_assurance_runs_smoke_only_for_agent_contract_changes(tmp_path: Path) -> None:
    from kicad_mcp.evals.release_policy import evaluate_push_assurance

    repo = _repository(tmp_path)
    policy_path = _policy(tmp_path / "policy.yaml")
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=False)
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "docs/notes.md").write_text("# docs only\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "docs")
    docs_head = _git(repo, "rev-parse", "HEAD")

    docs_decision = evaluate_push_assurance(
        repo_root=repo,
        policy_path=policy_path,
        baseline_path=baseline_path,
        base_ref=base,
        head_ref=docs_head,
    )
    assert docs_decision.mode == "none"
    assert docs_decision.reason == "no_agent_contract_change"
    assert docs_decision.release_base_ref is None
    assert docs_decision.release_contract_changed is None

    (repo / "src/kicad_mcp/evals/selector.py").write_text("VALUE = 4\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "agent-facing")
    agent_head = _git(repo, "rev-parse", "HEAD")

    agent_decision = evaluate_push_assurance(
        repo_root=repo,
        policy_path=policy_path,
        baseline_path=baseline_path,
        base_ref=docs_head,
        head_ref=agent_head,
    )
    assert agent_decision.mode == "smoke"
    assert agent_decision.reason == "agent_contract_changed_on_main"
    assert agent_decision.release_base_ref is None
    assert agent_decision.release_contract_changed is None


def test_noop_assurance_has_no_release_comparison_context(tmp_path: Path) -> None:
    from kicad_mcp.evals.release_policy import evaluate_noop_assurance

    repo = _repository(tmp_path)
    decision = evaluate_noop_assurance(
        repo_root=repo,
        policy_path=_policy(tmp_path / "policy.yaml"),
        baseline_path=_baseline(tmp_path / "baseline.yaml", approved=False),
    )

    assert decision.release_base_ref is None
    assert decision.release_contract_changed is None


def test_release_policy_cli_writes_machine_readable_outputs(tmp_path: Path) -> None:
    from scripts import check_live_model_release_policy as cli

    repo = _repository(tmp_path)
    _tag_server_release(repo)
    _commit_contract(repo, 2)
    policy_path = _policy(tmp_path / "policy.yaml")
    baseline_path = _baseline(tmp_path / "baseline.yaml", approved=False)
    output = tmp_path / "github-output.txt"

    exit_code = cli.main(
        [
            "--repo-root",
            str(repo),
            "--policy",
            str(policy_path),
            "--baseline",
            str(baseline_path),
            "--github-output",
            str(output),
            "release",
            "--ref",
            "HEAD",
            "--today",
            "2026-08-02",
        ]
    )

    assert exit_code == 0
    values = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert values["mode"] == "full"
    assert values["reason"] == "baseline_unapproved"
    assert values["required_configurations"] == '["alpha","beta","gamma"]'
    assert values["smoke_configurations"] == '["alpha","beta"]'
    assert values["release_base_ref"] == "mcp-server-v1.0.0"
    assert values["release_contract_changed"] == "true"
    assert len(values["current_contract_digest"]) == 64


def test_release_policy_cli_allows_unchanged_release_with_unapproved_baseline(
    tmp_path: Path,
) -> None:
    from scripts import check_live_model_release_policy as cli

    repo = _repository(tmp_path)
    release_tag = _tag_server_release(repo)
    _commit_docs(repo)
    output = tmp_path / "github-output.txt"

    exit_code = cli.main(
        [
            "--repo-root",
            str(repo),
            "--policy",
            str(_policy(tmp_path / "policy.yaml")),
            "--baseline",
            str(_baseline(tmp_path / "baseline.yaml", approved=False)),
            "--github-output",
            str(output),
            "--require-ready",
            "release",
            "--ref",
            "HEAD",
            "--today",
            "2026-08-02",
        ]
    )

    values = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert exit_code == 0
    assert values["mode"] == "none"
    assert values["reason"] == "no_agent_contract_change_since_release"
    assert values["release_base_ref"] == release_tag
    assert values["release_contract_changed"] == "false"


def test_smoke_assurance_cli_uses_policy_smoke_configurations() -> None:
    script = (ROOT / "scripts/evaluate_live_model_smoke_assurance.py").read_text(encoding="utf-8")

    assert "required_configurations=policy.smoke_configurations" in script
    assert "required_configurations=baseline.required_configurations" not in script


def test_live_model_assurance_workflow_is_risk_based_and_secret_safe() -> None:
    workflow = (ROOT / ".github/workflows/live-model-assurance.yml").read_text(encoding="utf-8")

    assert "push:\n    branches: [main]" in workflow
    assert "pull_request:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "release-please--branches--main" not in workflow
    assert "github.event.pull_request" not in workflow
    assert "check_live_model_release_policy.py" in workflow
    assert " push " in workflow or " push\n" in workflow
    assert " release " not in workflow
    assert " noop " not in workflow
    assert "environment: live-model-evals" in workflow
    assert "max-parallel: 1" in workflow
    assert "timeout-minutes: 17" in workflow
    assert "fail-fast: false" in workflow
    assert "--case-tag live-smoke" in workflow
    assert "--repeats 1" in workflow
    assert "timeout --signal=TERM --kill-after=30s 14m" in workflow
    assert '[ "$exit_code" -ne 124 ] && [ "$exit_code" -ne 137 ]' in workflow
    assert '"state": "running"' in workflow
    assert "smoke_configurations: ${{ steps.policy.outputs.smoke_configurations }}" in workflow
    assert "fromJSON(needs.classify.outputs.smoke_configurations)" in workflow
    assert "fromJSON(needs.classify.outputs.required_configurations)" not in workflow
    assert "evaluate_live_model_smoke_assurance.py" in workflow
    assert "name: Live Model Smoke Assurance" in workflow
    assert "name: Live Model Release Policy" in workflow
    assert "full protected live-model gate and baseline promotion are required" in workflow
    assert "name: Enforce smoke result" not in workflow
    assert 'test "$SMOKE_RESULT" = "success"' not in workflow
    assert "benchmark:" not in workflow
    assert "--repeats 3" not in workflow
    assert "NVIDIA_API_KEY: ${{ startsWith(matrix.configuration, 'nvidia-')" in workflow
    assert "OPENCODE_ZEN_API_KEY: ${{ startsWith(matrix.configuration, 'opencode-cli-')" in workflow
    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}" not in workflow
    assert "OPENCODE_ZEN_API_KEY: ${{ secrets.OPENCODE_ZEN_API_KEY }}" not in workflow
    assert "pull_request_target:" not in workflow
    assert "DOPPLER_TOKEN" not in workflow


def test_contract_digest_ignores_inherited_git_repository_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.evals.release_policy import compute_agent_contract_digest

    repo = _repository(tmp_path)
    policy = load_release_policy(_policy(tmp_path / "policy.yaml"))
    revision = _git(repo, "rev-parse", "HEAD")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    monkeypatch.setenv("GIT_DIR", str(foreign / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(foreign))
    monkeypatch.setenv("GIT_INDEX_FILE", str(foreign / "index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(foreign / "objects"))
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", str(foreign / "alternate"))

    digest = compute_agent_contract_digest(repo, policy, ref=revision)

    assert len(digest) == 64


def test_committed_release_policy_covers_provider_adapter_implementations() -> None:
    import fnmatch

    policy = load_release_policy(POLICY_PATH)

    def covered(relative_path: str) -> bool:
        return any(
            fnmatch.fnmatchcase(relative_path, pattern) for pattern in policy.agent_contract_paths
        )

    provider_modules = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/kicad_mcp/evals").glob("*_adapter.py")
    )
    provider_scripts = sorted(
        path.relative_to(ROOT).as_posix() for path in (ROOT / "scripts").glob("*_eval_adapter.py")
    )
    shared_harness = "src/kicad_mcp/evals/chat_eval_cli.py"
    uncovered = [
        path for path in [*provider_modules, *provider_scripts, shared_harness] if not covered(path)
    ]

    assert uncovered == []


def test_release_policy_cli_can_fail_closed_for_release_readiness(tmp_path: Path) -> None:
    from scripts import check_live_model_release_policy as cli

    repo = _repository(tmp_path)
    _tag_server_release(repo)
    _commit_contract(repo, 2)
    policy_path = _policy(tmp_path / "release-policy.yaml")
    baseline_path = _baseline(tmp_path / "baseline-unapproved.yaml", approved=False)

    exit_code = cli.main(
        [
            "--repo-root",
            str(repo),
            "--policy",
            str(policy_path),
            "--baseline",
            str(baseline_path),
            "--require-ready",
            "release",
            "--ref",
            "HEAD",
            "--today",
            "2026-08-02",
        ]
    )

    assert exit_code == 1


def test_release_validation_enforces_live_model_readiness_at_release_boundary() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "Enforce live-model release readiness" in workflow
    assert "check_live_model_release_policy.py --require-ready release" in workflow
    assert "startsWith(github.head_ref, 'release-please--')" in workflow


def test_required_pr_gate_blocks_unready_release_please_prs() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "release-readiness:" in workflow
    assert "startsWith(github.head_ref, 'release-please--')" in workflow
    assert "check_live_model_release_policy.py --require-ready release" in workflow
    expected_needs = (
        "needs: [changes, release-metadata, mcp-server, coverage, mcp-npm, chatgpt-app, "
        "protocol-schemas, mcp-2026-compat, workflow-policy, security, release-readiness]"
    )
    assert expected_needs in workflow
    assert '[release-readiness]="${{ needs.release-readiness.result }}"' in workflow


def _workflow_policy(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "baseline_max_age_days": 30,
                "release_pull_request_head": "release-please--branches--main",
                "release_tag_pattern": "mcp-server-v*",
                "minimum_smoke_configurations": 2,
                "smoke_configurations": ["alpha", "beta"],
                "agent_contract_paths": [".github/workflows/*.yml"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_agent_contract_digest_ignores_workflow_action_pin_bumps(tmp_path: Path) -> None:
    from kicad_mcp.evals.release_policy import compute_agent_contract_digest

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Policy Test")
    _git(repo, "config", "user.email", "policy@example.invalid")
    (repo / ".github/workflows").mkdir(parents=True)
    workflow_path = repo / ".github/workflows/live-model-eval.yml"

    workflow_path.write_text(
        f"jobs:\n  eval:\n    steps:\n      - uses: astral-sh/setup-uv@{'a' * 40}\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "initial")
    before = _git(repo, "rev-parse", "HEAD")

    workflow_path.write_text(
        f"jobs:\n  eval:\n    steps:\n      - uses: astral-sh/setup-uv@{'b' * 40}\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "pin bump")
    after_pin_bump = _git(repo, "rev-parse", "HEAD")

    policy = load_release_policy(_workflow_policy(tmp_path / "policy.yaml"))
    digest_before = compute_agent_contract_digest(repo, policy, ref=before)
    digest_after_pin_bump = compute_agent_contract_digest(repo, policy, ref=after_pin_bump)
    assert digest_before == digest_after_pin_bump

    workflow_path.write_text(
        "jobs:\n  eval:\n    steps:\n      - run: echo changed\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "real contract change")
    after_real_change = _git(repo, "rev-parse", "HEAD")
    digest_after_real_change = compute_agent_contract_digest(repo, policy, ref=after_real_change)
    assert digest_after_real_change != digest_after_pin_bump
