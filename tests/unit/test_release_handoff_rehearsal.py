"""A non-publishing, top-level workflow handoff must remain isolated."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_owner_only_dispatch_and_narrow_permissions() -> None:
    owner = workflow("release-handoff-rehearsal.yml")
    assert set(owner[True]) == {"workflow_dispatch"}
    assert owner["permissions"] == {"contents": "read"}
    assert owner["concurrency"]["cancel-in-progress"] is False
    job = owner["jobs"]["handoff"]
    assert job["permissions"] == {"contents": "read", "actions": "write"}
    for guard in (
        "refs/heads/main",
        "oaslananka/kicad-mcp-pro",
        "github.actor",
        "github.triggering_actor",
    ):
        assert guard in job["if"]
    assert job["timeout-minutes"] <= 10
    policy = json.loads((ROOT / ".github/actions-policy.json").read_text())
    assert policy["workflow_write_permissions"]["release-handoff-rehearsal.yml"] == {
        "handoff": ["actions"]
    }


def test_worker_has_no_publication_or_dispatch_authority() -> None:
    worker = workflow("release-handoff-worker.yml")
    assert worker[True] == {"workflow_dispatch": None}
    assert worker["permissions"] == {"contents": "read", "actions": "read"}
    job = worker["jobs"]["receipt"]
    assert "permissions" not in job
    assert "environment" not in job
    assert "github.actor_id == '41898282'" in job["if"]
    assert "refs/heads/main" in job["if"]
    assert job["timeout-minutes"] <= 5
    assert not worker.get("concurrency")
    steps = job["steps"]
    assert any(s.get("with", {}).get("persist-credentials") is False for s in steps)
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["path"] == "handoff-receipt.json"
    assert upload["with"]["retention-days"] == 3


def test_dispatch_contract_is_exact_run_not_search() -> None:
    script = (ROOT / "scripts/rehearse_release_handoff.sh").read_text()
    assert "X-GitHub-Api-Version: 2026-03-10" in script
    assert "/release-handoff-worker.yml/dispatches" in script
    assert ".workflow_run_id" in script
    assert "status=in_progress&head_sha=$GITHUB_SHA" in script
    assert ".total_count == 1 and (.workflow_runs|length) == 1" in script
    assert '{"ref":"main"}' in script
    assert '"$root/runs/$id"' in script
    assert "server.json" in script
    assert "sha256sum" in script
    assert "publicationAuthorized: false" in script
    assert "gh release" not in script
    assert "npm publish" not in script
    assert "id-token" not in script


def test_behavioral_rehearsal_runs_in_existing_workflow_gate() -> None:
    ci = workflow("ci.yml")
    steps = ci["jobs"]["workflow-policy"]["steps"]
    assert any(
        step.get("run") == "uv run --all-extras bash scripts/ci/test_release_handoff.sh"
        for step in steps
    )
