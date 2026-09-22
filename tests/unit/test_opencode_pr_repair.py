from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import scripts.opencode_publish as opencode_publish

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "opencode.yml"


def _workflow() -> dict[str, Any]:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_opencode_repair_workflow_is_hardened() -> None:
    parsed = _workflow()
    assert parsed["permissions"] == {"contents": "read"}

    repair = parsed["jobs"]["repair"]
    publish = parsed["jobs"]["publish"]
    assert repair["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert publish["permissions"] == {"contents": "write", "issues": "write"}
    assert publish["needs"] == "repair"
    assert repair["runs-on"] == "ubuntu-24.04"
    assert publish["runs-on"] == "ubuntu-24.04"

    steps = [*repair["steps"], *publish["steps"]]
    checkout_steps = [
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert len(checkout_steps) == 3
    for step in checkout_steps:
        assert step["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        assert step["with"]["persist-credentials"] is False

    upload = next(step for step in repair["steps"] if step["name"] == "Upload repair bundle")
    download = next(step for step in publish["steps"] if step["name"] == "Download repair bundle")
    assert upload["uses"] == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert download["uses"] == "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"

    install = next(
        step for step in repair["steps"] if step["name"] == "Install pinned OpenCode CLI"
    )
    assert "v${OPENCODE_VERSION}/opencode-linux-x64.tar.gz" in install["run"]
    assert "sha256sum --check -" in install["run"]
    assert repair["env"]["OPENCODE_VERSION"] == "1.18.32"
    assert (
        repair["env"]["OPENCODE_ASSET_SHA256"]
        == "3046e0404fdc60fb80307e7a47824ba07477364178a4d09baa8548496dd6d43b"
    )

    run_agent = next(
        step for step in repair["steps"] if step["name"] == "Run isolated OpenCode repair agent"
    )
    assert run_agent["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert run_agent["env"]["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    assert "GITHUB_TOKEN" not in run_agent.get("env", {})
    assert "GH_TOKEN" not in run_agent.get("env", {})
    assert "opencode --pure run" in run_agent["run"]
    assert "--agent pr-repair" in run_agent["run"]

    publish_step = next(
        step for step in publish["steps"] if step["name"] == "Publish repaired bundle"
    )
    assert 'python3 -I "$RUNNER_TEMP/opencode_publish.py" publish' in publish_step["run"]
    assert "GITHUB_TOKEN" in publish_step["env"]


def test_opencode_trigger_requires_exact_command_prefix() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.comment.body == '/oc'" in workflow
    assert "startsWith(github.event.comment.body, '/oc ')" in workflow
    assert "github.event.comment.body == '/opencode'" in workflow
    assert "startsWith(github.event.comment.body, '/opencode ')" in workflow


def test_opencode_agent_denies_credential_and_publish_surfaces() -> None:
    agent = (ROOT / ".opencode" / "agents" / "pr-repair.md").read_text(encoding="utf-8")
    assert '".git/**": deny' in agent
    assert "webfetch: deny" in agent
    assert "websearch: deny" in agent
    assert "external_directory: deny" in agent
    assert '"git commit*"' not in agent
    assert '"git push*"' not in agent
    assert '"repo-repair": allow' in agent
    assert "Do not broaden scope" in agent

    skill = (ROOT / ".opencode" / "skills" / "repo-repair" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: repo-repair" in skill
    assert "task workflows:policy" in skill
    assert "Do not commit or push" in skill


def test_opencode_workflow_permissions_are_recorded_in_policy() -> None:
    policy = json.loads((ROOT / ".github" / "actions-policy.json").read_text(encoding="utf-8"))
    assert policy["workflow_write_permissions"]["opencode.yml"] == {
        "publish": ["contents", "issues"]
    }


def test_opencode_publisher_scrubs_token_from_git_subprocesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(
        command: list[str],
        *,
        check: bool,
        stdout: int,
        stderr: int,
        env: dict[str, str],
    ) -> Completed:
        captured.update(
            command=command,
            check=check,
            stdout=stdout,
            stderr=stderr,
            env=env,
        )
        return Completed()

    monkeypatch.setenv("GITHUB_TOKEN", "write-secret")
    monkeypatch.setenv("GH_TOKEN", "gh-secret")
    monkeypatch.setattr(opencode_publish.subprocess, "run", fake_run)

    opencode_publish._git("status", "--porcelain")

    env = captured["env"]
    assert isinstance(env, dict)
    assert "GITHUB_TOKEN" not in env
    assert "GH_TOKEN" not in env
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_SYSTEM"] == "/dev/null"
    command = captured["command"]
    assert isinstance(command, list)
    assert "core.hooksPath=/dev/null" in command


def test_opencode_publisher_has_bounded_cross_job_bundle_contract() -> None:
    assert opencode_publish.MAX_CHANGED_FILES == 100
    assert opencode_publish.MAX_FILE_BYTES == 4 * 1024 * 1024
    assert opencode_publish.MAX_TOTAL_BYTES == 10 * 1024 * 1024
    source = (ROOT / "scripts" / "opencode_publish.py").read_text(encoding="utf-8")
    assert 'if sys.argv[1] == "prepare"' in source
    assert "publish_bundle(bundle_dir)" in source
    assert "hashlib.sha256(data).hexdigest()" in source
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Checkout original pull request head" not in workflow
