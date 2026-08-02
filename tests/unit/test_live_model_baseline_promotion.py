"""Approved live-model baseline promotion tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path
from shutil import which

import pytest
import yaml

from kicad_mcp.evals.baseline_promotion import (
    BaselinePromotionError,
    generate_approved_baseline,
)

CONFIGS = ("alpha", "beta", "gamma")
REVISION = ""


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


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Baseline Test")
    _git(repo, "config", "user.email", "baseline@example.invalid")
    target = repo / "src/kicad_mcp/evals"
    target.mkdir(parents=True)
    (target / "selector.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--no-verify", "-m", "contract")
    return repo, _git(repo, "rev-parse", "HEAD")


def _policy(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "baseline_max_age_days": 30,
                "release_pull_request_head": "release-please--branches--main",
                "minimum_smoke_configurations": 2,
                "agent_contract_paths": ["src/kicad_mcp/evals/**"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _baseline(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "approved": False,
                "approved_at": None,
                "source_revision": None,
                "agent_contract_digest": None,
                "evidence": {"workflow_run_id": None, "aggregate_sha256": None},
                "minimum_repeats": 3,
                "required_configurations": list(CONFIGS),
                "configurations": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _aggregate(path: Path, revision: str) -> Path:
    observed = {
        config_id: {
            "host": "test-host",
            "model": f"model-{config_id}",
            "repeats": 3,
            "complete": True,
            "pass_rate": 1.0,
            "mean_recall": 1.0,
            "unnecessary_call_rate": 0.0,
            "instability_rate": 0.0,
            "p95_latency_ms": 100.0,
            "mean_tokens": 200.0,
            "token_coverage": 1.0,
            "cost_coverage": 0.0,
            "adapter_failures": 0,
            "selection_failures": 0,
            "safety_violations": 0,
            "forbidden_violations": 0,
        }
        for config_id in CONFIGS
    }
    payload = {
        "schema_version": 1,
        "passed": False,
        "source_revision": revision,
        "configurations": list(CONFIGS),
        "classifications": {
            "safety_failures": [],
            "quality_failures": ["approved baselines unavailable"],
            "infrastructure_failures": [],
            "telemetry_unavailable": [],
        },
        "comparisons": {},
        "per_case_failures": [],
        "observed": observed,
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_generate_approved_baseline_from_clean_full_gate_evidence(tmp_path: Path) -> None:
    repo, revision = _repo(tmp_path)
    policy = _policy(tmp_path / "policy.yaml")
    template = _baseline(tmp_path / "baseline.yaml")
    aggregate = _aggregate(tmp_path / "aggregate.json", revision)

    baseline = generate_approved_baseline(
        aggregate_report_path=aggregate,
        baseline_template_path=template,
        policy_path=policy,
        repo_root=repo,
        workflow_run_id=987654,
        approved_at=date(2026, 8, 2),
    )

    assert baseline["approved"] is True
    assert baseline["approved_at"] == "2026-08-02"
    assert baseline["source_revision"] == revision
    assert len(baseline["agent_contract_digest"]) == 64
    assert baseline["evidence"] == {
        "workflow_run_id": 987654,
        "aggregate_sha256": hashlib.sha256(aggregate.read_bytes()).hexdigest(),
    }
    assert baseline["required_configurations"] == list(CONFIGS)
    assert baseline["configurations"]["alpha"] == {
        "host": "test-host",
        "model": "model-alpha",
        "token_metrics_required": True,
        "metrics": {
            "pass_rate": 1.0,
            "mean_recall": 1.0,
            "unnecessary_call_rate": 0.0,
            "instability_rate": 0.0,
            "p95_latency_ms": 100.0,
            "mean_tokens": 200.0,
        },
    }


def test_generate_approved_baseline_rejects_safety_quality_or_infrastructure_failures(
    tmp_path: Path,
) -> None:
    repo, revision = _repo(tmp_path)
    policy = _policy(tmp_path / "policy.yaml")
    template = _baseline(tmp_path / "baseline.yaml")
    aggregate = _aggregate(tmp_path / "aggregate.json", revision)
    payload = json.loads(aggregate.read_text(encoding="utf-8"))
    payload["classifications"]["safety_failures"] = ["alpha: safety=1"]
    aggregate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BaselinePromotionError, match="safety"):
        generate_approved_baseline(
            aggregate_report_path=aggregate,
            baseline_template_path=template,
            policy_path=policy,
            repo_root=repo,
            workflow_run_id=987654,
            approved_at=date(2026, 8, 2),
        )

    payload["classifications"]["safety_failures"] = []
    payload["classifications"]["quality_failures"] = ["alpha: pass_rate regressed"]
    aggregate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselinePromotionError, match="quality"):
        generate_approved_baseline(
            aggregate_report_path=aggregate,
            baseline_template_path=template,
            policy_path=policy,
            repo_root=repo,
            workflow_run_id=987654,
            approved_at=date(2026, 8, 2),
        )

    payload["classifications"]["quality_failures"] = ["approved baselines unavailable"]
    payload["classifications"]["infrastructure_failures"] = ["beta: timeout"]
    aggregate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselinePromotionError, match="infrastructure"):
        generate_approved_baseline(
            aggregate_report_path=aggregate,
            baseline_template_path=template,
            policy_path=policy,
            repo_root=repo,
            workflow_run_id=987654,
            approved_at=date(2026, 8, 2),
        )


def test_generate_approved_baseline_rejects_missing_or_mismatched_configuration(
    tmp_path: Path,
) -> None:
    repo, revision = _repo(tmp_path)
    aggregate = _aggregate(tmp_path / "aggregate.json", revision)
    payload = json.loads(aggregate.read_text(encoding="utf-8"))
    del payload["observed"]["gamma"]
    aggregate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BaselinePromotionError, match="required configurations"):
        generate_approved_baseline(
            aggregate_report_path=aggregate,
            baseline_template_path=_baseline(tmp_path / "baseline.yaml"),
            policy_path=_policy(tmp_path / "policy.yaml"),
            repo_root=repo,
            workflow_run_id=987654,
            approved_at=date(2026, 8, 2),
        )
