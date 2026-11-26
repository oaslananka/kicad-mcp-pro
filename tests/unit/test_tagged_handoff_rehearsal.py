"""End-to-end synthetic tagged handoff contract, with no production authority."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from scripts import rehearse_tagged_handoff as rehearsal

SHA = "a" * 40
OWNER = 101
CHILD = 202
TAG = f"handoff-rehearsal-{SHA}"
REPO = "oaslananka/kicad-mcp-pro"


def run_data(run_id: int, *, owner: bool, status: str = "in_progress") -> dict[str, Any]:
    actor = (
        {"login": "oaslananka", "id": 285490571}
        if owner
        else {"login": "github-actions[bot]", "id": 41898282}
    )
    repository = {"full_name": REPO, "id": 1255527274}
    return {
        "id": run_id,
        "run_attempt": 1,
        "url": f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}",
        "repository": repository,
        "head_repository": repository,
        "actor": actor,
        "triggering_actor": actor.copy(),
        "event": "workflow_dispatch",
        "path": rehearsal.OWNER_PATH if owner else rehearsal.WORKER_PATH,
        "head_branch": "main" if owner else TAG,
        "head_sha": SHA,
        "status": status,
        "conclusion": "success" if status == "completed" else None,
    }


class Client:
    def __init__(self) -> None:
        self.owner = run_data(OWNER, owner=True)
        self.child = run_data(CHILD, owner=False)
        self.tag_sha = SHA
        self.items: dict[int, dict[str, Any]] = {}
        self.listed: dict[int, list[dict[str, Any]]] = {OWNER: [], CHILD: []}

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        assert repo == REPO
        return self.owner if run_id == OWNER else self.child

    def tag_commit(self, repo: str, tag: str) -> str:
        assert repo == REPO
        assert tag == TAG
        return self.tag_sha

    def workflow_artifacts(self, repo: str, run_id: int) -> dict[str, Any]:
        return {"total_count": len(self.listed[run_id]), "artifacts": self.listed[run_id]}

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]:
        return self.items[artifact_id]

    def store(self, run_id: int, artifact_id: int, name: str, data: bytes) -> None:
        item = {
            "id": artifact_id,
            "name": name,
            "expired": False,
            "size_in_bytes": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}",
            "archive_download_url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip",
            "workflow_run": {
                "id": run_id,
                "repository_id": 1255527274,
                "head_repository_id": 1255527274,
                "head_branch": "main" if run_id == OWNER else TAG,
                "head_sha": SHA,
            },
        }
        self.items[artifact_id] = item
        self.listed[run_id].append(item)


def archive_bytes(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return stream.getvalue()


class Signature:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.invocation = f"https://github.com/{REPO}/actions/runs/{OWNER}/attempts/1"

    def verify(
        self, *, path: Path, repo: str, sha: str, signer: str, source_ref: str
    ) -> list[dict[str, Any]]:
        assert repo == REPO
        assert sha == SHA
        assert signer == rehearsal.OWNER_PATH
        assert source_ref == "refs/heads/main"
        self.calls.append(path.name)
        return [
            {
                "verificationResult": {
                    "statement": {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [
                            {
                                "name": path.name,
                                "digest": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                            }
                        ],
                        "predicate": {
                            "runDetails": {"metadata": {"invocationId": self.invocation}}
                        },
                    },
                    "signature": {"certificate": {"runInvocationURI": self.invocation}},
                }
            }
        ]


@pytest.fixture
def evidence(
    tmp_path: Path,
) -> tuple[Client, Signature, rehearsal.Identity, Path, dict[str, bytes]]:
    identity = rehearsal.Identity(SHA, OWNER, CHILD)
    client = Client()
    files = rehearsal.records(identity)
    request = archive_bytes(files)
    client.store(OWNER, 303, rehearsal.request_name(identity), request)
    path = tmp_path / "request.zip"
    path.write_bytes(request)
    return client, Signature(), identity, path, files


def test_complete_signed_request_and_receipt(evidence, tmp_path: Path) -> None:
    client, signature, identity, request, files = evidence
    result = rehearsal.verify_request(client, signature, identity, 303, request)
    assert sorted(signature.calls) == sorted(files)
    receipt = json.loads(result)
    assert receipt["publicationAuthorized"] is False
    assert receipt["rehearsal"] is True
    assert receipt["workerRunId"] == CHILD
    assert receipt["tag"] == TAG
    assert receipt["requestArchiveSha256"] == hashlib.sha256(request.read_bytes()).hexdigest()
    client.child = run_data(CHILD, owner=False, status="completed")
    data = archive_bytes({rehearsal.RECEIPT: result})
    path = tmp_path / "receipt.zip"
    path.write_bytes(data)
    client.store(CHILD, 404, rehearsal.receipt_name(identity), data)
    assert rehearsal.verify_receipt(client, identity, 404, path) == result


@pytest.mark.parametrize(
    "mutation", ["owner", "child", "tag", "attempt", "artifact", "archive", "signature", "extra"]
)
def test_request_rejects_wrong_evidence(evidence, mutation: str) -> None:
    client, signature, identity, request, files = evidence
    if mutation == "owner":
        client.owner["path"] = ".github/workflows/publish-release.yml"
    elif mutation == "child":
        client.child["head_branch"] = "main"
    elif mutation == "tag":
        client.tag_sha = "b" * 40
    elif mutation == "attempt":
        client.child["run_attempt"] = 2
    elif mutation == "artifact":
        client.items[303]["workflow_run"]["repository_id"] = 1
    elif mutation == "archive":
        request.write_bytes(b"wrong")
    elif mutation == "signature":
        signature.invocation = "wrong"
    else:
        data = archive_bytes({**files, "extra": b"unexpected"})
        client.listed[OWNER].clear()
        client.store(OWNER, 303, rehearsal.request_name(identity), data)
        request.write_bytes(data)
    with pytest.raises(ValueError):
        rehearsal.verify_request(client, signature, identity, 303, request)


def test_rejects_production_or_ambiguous_identity() -> None:
    with pytest.raises(ValueError):
        rehearsal.Identity("refs/tags/mcp-server-v4.0.0", OWNER, CHILD)
    with pytest.raises(ValueError):
        rehearsal.Identity(SHA, OWNER, OWNER)
    with pytest.raises(ValueError):
        rehearsal.Identity(SHA, True, CHILD)


def test_pending_artifact_only_retry(evidence, monkeypatch) -> None:
    client, _, identity, _, _ = evidence
    item = client.listed[OWNER].pop()
    pauses = []

    def pause(seconds: int) -> None:
        pauses.append(seconds)
        client.listed[OWNER].append(item)

    monkeypatch.setattr(rehearsal.time, "sleep", pause)
    assert rehearsal.wait_request(client, identity)["id"] == 303
    assert pauses == [5]


def test_duplicate_artifact_fails_without_retry(evidence, monkeypatch) -> None:
    client, _, identity, _, _ = evidence
    client.listed[OWNER].append(client.items[303])
    pauses = []
    monkeypatch.setattr(rehearsal.time, "sleep", pauses.append)
    with pytest.raises(ValueError):
        rehearsal.wait_request(client, identity)
    assert pauses == []


def test_workflows_isolate_dispatch_signing_and_receipt() -> None:
    import yaml

    root = Path(__file__).resolve().parents[2]
    owner = yaml.safe_load((root / rehearsal.OWNER_PATH).read_text(encoding="utf-8"))
    worker = yaml.safe_load((root / rehearsal.WORKER_PATH).read_text(encoding="utf-8"))
    assert owner[True] == {"workflow_dispatch": None}
    assert set(worker[True]) == {"workflow_dispatch"}
    assert owner["permissions"] == {"contents": "read"}
    assert worker["permissions"] == {"contents": "read", "actions": "read", "attestations": "read"}
    assert owner["concurrency"]["cancel-in-progress"] is False
    jobs = owner["jobs"]
    assert jobs["dispatch"]["permissions"] == {"contents": "read", "actions": "write"}
    assert jobs["sign"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    assert jobs["receipt"]["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["sign"]["needs"] == "dispatch"
    assert jobs["receipt"]["needs"] == ["dispatch", "sign"]
    assert "github.actor_id == '285490571'" in jobs["dispatch"]["if"]
    assert "github.run_attempt == '1'" in jobs["dispatch"]["if"]
    worker_job = worker["jobs"]["verify"]
    assert "github.actor_id == '41898282'" in worker_job["if"]
    assert "github.run_attempt == '1'" in worker_job["if"]
    assert "handoff-rehearsal-" in worker_job["if"]
    assert not worker.get("concurrency")
    for job in [*jobs.values(), worker_job]:
        assert "environment" not in job
        assert job["timeout-minutes"] <= 10
        assert any(
            step.get("with", {}).get("persist-credentials") is False for step in job["steps"]
        )
    policy = json.loads((root / ".github/actions-policy.json").read_text())
    assert policy["workflow_write_permissions"]["tagged-handoff-rehearsal.yml"] == {
        "dispatch": ["actions"],
        "sign": ["artifact-metadata", "attestations", "id-token"],
    }
    dispatch = next(
        step["run"] for step in jobs["dispatch"]["steps"] if step.get("id") == "dispatch"
    )
    assert "2026-03-10" in dispatch
    assert ".workflow_run_id" in dispatch
    assert "tagged-handoff-worker.yml/dispatches" in dispatch
    assert "handoff-rehearsal-$GITHUB_SHA" in dispatch
    assert "check-owner" in dispatch
    assert '--arg owner "$GITHUB_RUN_ID"' in dispatch
    assert "inputs:{owner_run_id:$owner}" in dispatch
    assert worker[True]["workflow_dispatch"]["inputs"] == {
        "owner_run_id": {
            "description": "Untrusted owner run selector (verified by the worker)",
            "required": True,
            "type": "string",
        }
    }
    verify_step = next(step for step in worker_job["steps"] if "run" in step)
    assert verify_step["env"]["REHEARSAL_OWNER_RUN_ID"] == "${{ inputs.owner_run_id }}"
    assert "inputs.owner_run_id" not in verify_step["run"]
    for job in (jobs["receipt"], worker_job):
        steps = "\n".join(step.get("run", "") for step in job["steps"])
        assert "head -c 65537" in steps
        assert "set -euo pipefail" in steps
        assert "/artifacts/$artifact/zip" in steps
        assert "gh release" not in steps
        assert "npm publish" not in steps
    assert "tagged-handoff-receipt.json" in str(worker_job["steps"])


@pytest.mark.parametrize("mutation", ["wrong-receipt", "wrong-branch", "failed-child", "duplicate"])
def test_owner_refuses_untrusted_completed_receipt(evidence, tmp_path: Path, mutation: str) -> None:
    client, signature, identity, request, _ = evidence
    result = rehearsal.verify_request(client, signature, identity, 303, request)
    client.child = run_data(CHILD, owner=False, status="completed")
    if mutation == "wrong-receipt":
        result = result.replace(b'"publicationAuthorized": false', b'"publicationAuthorized": true')
    data = archive_bytes({rehearsal.RECEIPT: result})
    path = tmp_path / "receipt.zip"
    path.write_bytes(data)
    client.store(CHILD, 404, rehearsal.receipt_name(identity), data)
    if mutation == "wrong-branch":
        client.items[404]["workflow_run"]["head_branch"] = "main"
    elif mutation == "failed-child":
        client.child["conclusion"] = "failure"
    elif mutation == "duplicate":
        client.listed[CHILD].append(client.items[404])
    with pytest.raises(ValueError):
        rehearsal.verify_receipt(client, identity, 404, path)


def test_rejects_owner_change_during_final_metadata_read(evidence, monkeypatch) -> None:
    client, signature, identity, request, _ = evidence
    original = client.artifact
    calls = []

    def detail(repo: str, artifact_id: int) -> dict[str, Any]:
        calls.append(artifact_id)
        if len(calls) == 2:
            client.owner["status"] = "completed"
            client.owner["conclusion"] = "success"
        return original(repo, artifact_id)

    monkeypatch.setattr(client, "artifact", detail)
    with pytest.raises(ValueError, match="not active"):
        rehearsal.verify_request(client, signature, identity, 303, request)


def test_poll_budget_and_fail_closed(evidence, monkeypatch) -> None:
    client, _, identity, _, _ = evidence
    client.listed[OWNER].clear()
    pauses = []
    monkeypatch.setattr(rehearsal.time, "sleep", pauses.append)
    with pytest.raises(ValueError, match="timed out"):
        rehearsal.wait_request(client, identity)
    assert pauses == [5] * 29


@pytest.mark.parametrize("mutation", ["ref", "event", "attempt", "repo", "id", "unicode-id"])
def test_runtime_rejects_untrusted_context(monkeypatch, mutation: str) -> None:
    env = {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": str(CHILD),
        "GITHUB_REF": f"refs/tags/{TAG}",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if mutation == "ref":
        # Operation-level ref check must stop before invoking any network method.
        monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
        monkeypatch.setattr("sys.argv", ["rehearse_tagged_handoff", "wait-request"])
        with pytest.raises(SystemExit) as result:
            rehearsal.main()
        assert result.value.code == 2
        return
    bad = {
        "event": ("GITHUB_EVENT_NAME", "release"),
        "attempt": ("GITHUB_RUN_ATTEMPT", "2"),
        "repo": ("GITHUB_REPOSITORY", "other/repo"),
        "id": ("GITHUB_RUN_ID", "01"),
        "unicode-id": ("GITHUB_RUN_ID", "1\u0662"),
    }
    key, value = bad[mutation]
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="runtime"):
        rehearsal._runtime()


def test_rehearsal_record_is_not_production_dispatch(evidence, tmp_path: Path) -> None:
    from scripts.check_signed_python_dispatch_binding import (
        DispatchIdentity,
        verify_dispatch_binding,
    )
    from scripts.check_signed_python_handoff import HandoffIdentity

    client, signature, identity, _, files = evidence
    path = tmp_path / "python-worker-dispatch.json"
    path.write_bytes(files[rehearsal.BINDING])
    handoff = HandoffIdentity("mcp-server-v0.0.0", SHA, 1, OWNER, 1, 9, 1, 10)
    production = DispatchIdentity(
        handoff, hashlib.sha256(files[rehearsal.MANIFEST]).hexdigest(), CHILD, 1
    )
    with pytest.raises(ValueError, match="bytes"):
        verify_dispatch_binding(
            client,
            signature,
            identity=production,
            binding=path,
            runtime_ref="refs/tags/mcp-server-v0.0.0",
            runtime_sha=identity.source,
            runtime_run_id=CHILD,
            runtime_attempt=1,
        )
    assert not signature.calls


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("check-owner", ["--child", str(CHILD)]),
        ("prepare", ["--child", str(CHILD), "--artifact-id", "303"]),
        ("wait-request", ["--archive", "ignored.zip"]),
        ("wait-receipt", ["--child", str(CHILD), "--output", "ignored"]),
        (
            "verify-request",
            ["--artifact-id", "303", "--archive", "request.zip", "--output", "ignored"],
        ),
        ("verify-receipt", ["--child", str(CHILD)]),
    ],
)
def test_cli_rejects_irrelevant_or_missing_arguments_before_api(
    monkeypatch, operation, arguments
) -> None:
    worker = operation in ("wait-request", "verify-request")
    env = {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": str(CHILD if worker else OWNER),
        "GITHUB_REF": f"refs/tags/{TAG}" if worker else "refs/heads/main",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.argv", ["rehearse_tagged_handoff", operation, *arguments])

    def forbidden() -> None:
        pytest.fail("invalid command must not access the API")

    monkeypatch.setattr(rehearsal, "DeliveryGitHubCLI", forbidden)
    with pytest.raises(SystemExit) as error:
        rehearsal.main()
    assert error.value.code == 2


@pytest.mark.parametrize("value", ["", "0", "01", "-1", "1.2", "1\u0662", "1" * 16, "202", "101\n"])
def test_worker_rejects_invalid_owner_selector_before_api(monkeypatch, value: str) -> None:
    monkeypatch.setenv("REHEARSAL_OWNER_RUN_ID", value)
    with pytest.raises(ValueError, match="owner selector"):
        rehearsal._owner_selector(CHILD)


def test_worker_reads_exact_owner_selector(monkeypatch) -> None:
    monkeypatch.setenv("REHEARSAL_OWNER_RUN_ID", str(OWNER))
    assert rehearsal._owner_selector(CHILD) == OWNER


def test_worker_cli_uses_exact_owner_without_listing(evidence, monkeypatch, capsys) -> None:
    client, _, _, _, _ = evidence
    monkeypatch.setattr(rehearsal, "DeliveryGitHubCLI", lambda: client)
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": str(CHILD),
        "GITHUB_REF": f"refs/tags/{TAG}",
        "REHEARSAL_OWNER_RUN_ID": str(OWNER),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.argv", ["rehearse_tagged_handoff", "wait-request"])
    assert rehearsal.main() == 0
    assert capsys.readouterr().out == "303\n"


@pytest.mark.parametrize("mutation", ["wrong-id", "wrong-actor", "completed-owner", "wrong-tag"])
def test_selector_is_not_authority(evidence, monkeypatch, mutation: str) -> None:
    client, _, _, _, _ = evidence
    monkeypatch.setattr(rehearsal, "DeliveryGitHubCLI", lambda: client)
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": str(CHILD),
        "GITHUB_REF": f"refs/tags/{TAG}",
        "REHEARSAL_OWNER_RUN_ID": str(203 if mutation == "wrong-id" else OWNER),
    }.items():
        monkeypatch.setenv(key, value)
    if mutation == "wrong-actor":
        client.owner["actor"]["id"] = 123
    elif mutation == "completed-owner":
        client.owner = run_data(OWNER, owner=True, status="completed")
    elif mutation == "wrong-tag":
        client.tag_sha = "b" * 40
    monkeypatch.setattr("sys.argv", ["rehearse_tagged_handoff", "wait-request"])
    with pytest.raises(SystemExit) as result:
        rehearsal.main()
    assert result.value.code == 2
