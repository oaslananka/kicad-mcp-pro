"""A non-publishing, top-level workflow handoff must remain isolated."""

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
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
    assert set(worker[True]) == {"workflow_dispatch"}
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
    assert '"$root/runs/$id"' in script
    assert "server.json" in script
    assert "sha256sum" in script
    assert "publicationAuthorized: false" in script
    assert "gh release" not in script
    assert "npm publish" not in script
    assert "id-token" not in script


@pytest.fixture
def simulated_api(tmp_path: Path) -> tuple[Path, dict[str, str], Callable[[str, object], None]]:
    """Use the real shell entry points; replace only git and GitHub API transport."""
    if os.name != "posix" or not all(
        shutil.which(tool) for tool in ("bash", "jq", "unzip", "sha256sum")
    ):
        pytest.skip("rehearsal targets a Linux runner")
    api = tmp_path / "api"
    api.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sha = "a" * 40
    repo = "oaslananka/kicad-mcp-pro"
    manifest = b'{"version":"4.23.0"}\n'
    (tmp_path / "server.json").write_bytes(manifest)
    digest = hashlib.sha256(manifest).hexdigest()
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "FAKE_API": str(api),
        "GITHUB_REPOSITORY": repo,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_SHA": sha,
        "GITHUB_RUN_ID": "10",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_ACTOR": "oaslananka",
        "GITHUB_ACTOR_ID": "285490571",
        "GITHUB_TRIGGERING_ACTOR": "oaslananka",
        "OWNER_RUN_ID": "10",
        "OWNER_ATTEMPT": "1",
        "SOURCE_COMMIT": sha,
        "MANIFEST_DIGEST": digest,
    }

    def write(name, data):
        (api / name).write_text(json.dumps(data), encoding="utf-8")

    def run_record(run_id, actor, filename, status, conclusion):
        return {
            "id": run_id,
            "repository": {"full_name": repo, "id": 123},
            "head_repository": {"full_name": repo, "id": 123},
            "path": ".github/workflows/" + filename,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": sha,
            "run_attempt": 1,
            "actor": {"login": actor, "id": 285490571 if actor == "oaslananka" else 41898282},
            "triggering_actor": {
                "login": actor,
                "id": 285490571 if actor == "oaslananka" else 41898282,
            },
            "status": status,
            "conclusion": conclusion,
        }

    write(
        "owner.json",
        run_record(10, "oaslananka", "release-handoff-rehearsal.yml", "in_progress", None),
    )
    write(
        "worker.json",
        run_record(20, "github-actions[bot]", "release-handoff-worker.yml", "completed", "success"),
    )
    write("dispatch-response.json", {"workflow_run_id": 20})
    fake_git = bin_dir / "git"
    fake_git.write_text('#!/bin/sh\nprintf "%s\\n" "$GITHUB_SHA"\n')
    fake_git.chmod(0o700)
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        """#!/bin/sh
set -eu
test "$1" = api
shift
test "$1" = -H
test "$2" = 'X-GitHub-Api-Version: 2026-03-10'
shift 2
root=repos/oaslananka/kicad-mcp-pro/actions
case "$*" in
  "$root/runs/10") cat "$FAKE_API/owner.json";;
  "$root/runs/20") cat "$FAKE_API/worker.json";;
  "-X POST $root/workflows/release-handoff-worker.yml/dispatches --input -")
    test ! -e "$FAKE_API/dispatch.json"
    cat > "$FAKE_API/dispatch.json"
    cat "$FAKE_API/dispatch-response.json";;
  "$root/runs/20/artifacts?per_page=100") cat "$FAKE_API/artifacts.json";;
  "$root/artifacts/30/zip") cat "$FAKE_API/receipt.zip";;
  *) exit 97;;
esac
"""
    )
    fake_gh.chmod(0o700)
    return api, env, write


def invoke(tmp_path, env, role) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(
        [bash, str(ROOT / "scripts/rehearse_release_handoff.sh"), role],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "failed-worker",
        "stale-worker",
        "wrong-digest",
        "wrong-receipt",
        "duplicate",
        "ambiguous-dispatch",
    ],
)
def test_real_shell_handoff(simulated_api, tmp_path, fault) -> None:
    api, env, write = simulated_api
    worker_env = {
        **env,
        "GITHUB_RUN_ID": "20",
        "GITHUB_ACTOR": "github-actions[bot]",
        "GITHUB_ACTOR_ID": "41898282",
        "GITHUB_TRIGGERING_ACTOR": "github-actions[bot]",
    }
    record = json.loads((api / "worker.json").read_text())
    write("worker.json", {**record, "status": "in_progress", "conclusion": None})
    worker = invoke(tmp_path, worker_env, "worker")
    write("worker.json", record)
    assert worker.returncode == 0, worker.stderr
    receipt = (tmp_path / "handoff-receipt.json").read_bytes()
    if fault == "wrong-receipt":
        receipt = receipt.replace(
            b'"publicationAuthorized": false', b'"publicationAuthorized": true'
        )
    archive = api / "receipt.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("handoff-receipt.json", receipt)
    artifact = {
        "id": 30,
        "name": "handoff-receipt-1",
        "expired": False,
        "workflow_run": {"id": 20, "head_sha": env["GITHUB_SHA"], "head_branch": "main"},
        "size_in_bytes": archive.stat().st_size,
        "digest": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    if fault == "wrong-digest":
        artifact["digest"] = "sha256:" + "0" * 64
    artifacts = [artifact, artifact] if fault == "duplicate" else [artifact]
    write("artifacts.json", {"total_count": len(artifacts), "artifacts": artifacts})
    if fault in {"failed-worker", "stale-worker"}:
        record = json.loads((api / "worker.json").read_text())
        if fault == "failed-worker":
            record["conclusion"] = "failure"
        else:
            record["run_attempt"] = 2
        write("worker.json", record)
    if fault == "ambiguous-dispatch":
        write("dispatch-response.json", {})
    owner = invoke(tmp_path, env, "owner")
    assert (owner.returncode == 0) == (fault is None), owner.stderr
    assert json.loads((api / "dispatch.json").read_text()) == {
        "ref": "main",
        "inputs": {
            "owner_run_id": "10",
            "owner_attempt": "1",
            "source_commit": env["GITHUB_SHA"],
            "manifest_digest": env["MANIFEST_DIGEST"],
        },
    }
    assert ("Verified rehearsal receipt artifact 30" in owner.stdout) == (fault is None)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong-actor",
        "wrong-actor-id",
        "wrong-source",
        "wrong-manifest",
        "inactive-owner",
        "stale-owner",
        "rerun",
    ],
)
def test_worker_rejects_wrong_handoff(simulated_api, tmp_path, fault) -> None:
    api, env, write = simulated_api
    env.update(
        GITHUB_RUN_ID="20",
        GITHUB_ACTOR="github-actions[bot]",
        GITHUB_ACTOR_ID="41898282",
        GITHUB_TRIGGERING_ACTOR="github-actions[bot]",
    )
    if fault == "wrong-actor":
        env["GITHUB_ACTOR"] = "someone-else"
    elif fault == "wrong-actor-id":
        env["GITHUB_ACTOR_ID"] = "1"
    elif fault == "wrong-source":
        env["SOURCE_COMMIT"] = "b" * 40
    elif fault == "wrong-manifest":
        env["MANIFEST_DIGEST"] = "b" * 64
    elif fault == "rerun":
        env["GITHUB_RUN_ATTEMPT"] = "2"
    else:
        record = json.loads((api / "owner.json").read_text())
        if fault == "inactive-owner":
            record["status"] = "completed"
        else:
            record["run_attempt"] = 2
        write("owner.json", record)
    assert invoke(tmp_path, env, "worker").returncode != 0
    assert not (tmp_path / "handoff-receipt.json").exists()
    assert not (api / "dispatch.json").exists()
