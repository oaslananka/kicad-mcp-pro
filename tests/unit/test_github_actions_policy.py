from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import scripts.check_github_actions_policy as actions_policy
from scripts.check_github_actions_policy import load_policy, validate_repository

ROOT = Path(__file__).resolve().parents[2]


def _baseline_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "repository_settings": {
            "allowed_actions": "selected",
            "can_approve_pull_request_reviews": False,
            "default_workflow_permissions": "read",
            "github_owned_allowed": True,
            "sha_pinning_required": True,
            "verified_allowed": False,
        },
        "github_owned_action_owners": ["actions", "github"],
        "allowed_action_repositories": [],
        "workflow_write_permissions": {},
        "required_codeowner_rules": ["* @maintainer"],
    }


def _write_fixture(root: Path, workflow: str) -> None:
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "test.yml").write_text(workflow, encoding="utf-8")
    (root / ".github" / "CODEOWNERS").write_text("* @maintainer\n", encoding="utf-8")


def test_repository_actions_policy_is_current() -> None:
    assert validate_repository(ROOT, load_policy()) == []


def test_policy_rejects_workflow_level_write_permission(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """name: unsafe
on: push
permissions:
  contents: read
  issues: write
jobs:
  test:
    runs-on: ubuntu-latest
    steps: []
""",
    )

    errors = validate_repository(tmp_path, _baseline_policy())

    assert any("write permissions must be scoped to a job" in error for error in errors)


def test_policy_rejects_unpinned_action(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """name: unsafe
on: push
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""",
    )

    errors = validate_repository(tmp_path, _baseline_policy())

    assert any("not pinned to a 40-character SHA" in error for error in errors)


def test_sha_pinned_action_check_accepts_revision_changes_and_rejects_tags() -> None:
    first_sha = "a" * 40
    second_sha = "b" * 40
    workflow = f"""jobs:
  attest:
    steps:
      - uses: actions/attest@{first_sha}
      - name: second
        uses: actions/attest@{second_sha}
"""

    assert actions_policy.has_sha_pinned_action(workflow, "actions/attest")
    assert not actions_policy.has_sha_pinned_action(
        workflow.replace(f"actions/attest@{first_sha}", "actions/attest@v4").replace(
            f"actions/attest@{second_sha}", "actions/attest@main"
        ),
        "actions/attest",
    )
    assert not actions_policy.has_sha_pinned_action(workflow, "actions/attestation")


def test_sha_pinned_action_check_scans_concatenated_workflow_text() -> None:
    sha = "c" * 40
    workflows = f"""name: first
jobs:
  one:
    steps:
      - uses: dorny/paths-filter@{sha}
name: second
jobs:
  two:
    steps:
      - run: echo done
"""

    assert actions_policy.has_sha_pinned_action(workflows, "dorny/paths-filter")


def test_policy_rejects_unexpected_job_write_scope(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """name: unsafe
on: push
permissions:
  contents: read
jobs:
  test:
    permissions:
      contents: read
      issues: write
    runs-on: ubuntu-latest
    steps: []
""",
    )

    errors = validate_repository(tmp_path, _baseline_policy())

    assert any("write-permission matrix differs" in error for error in errors)


def test_load_policy_rejects_file_outside_repository(tmp_path: Path) -> None:
    external_policy = tmp_path / "actions-policy.json"
    external_policy.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the repository root"):
        load_policy(external_policy)


def test_load_policy_accepts_policy_inside_explicit_repository_root(tmp_path: Path) -> None:
    policy_dir = tmp_path / ".github"
    policy_dir.mkdir()
    policy_path = policy_dir / "actions-policy.json"
    policy_path.write_text("{}\n", encoding="utf-8")

    assert load_policy(Path(".github/actions-policy.json"), root=tmp_path) == {}


def test_load_policy_rejects_symlink_escape_from_repository_root(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    external_policy = tmp_path / "external-policy.json"
    external_policy.write_text("{}\n", encoding="utf-8")
    policy_link = repository / "policy.json"
    policy_link.symlink_to(external_policy)

    with pytest.raises(ValueError, match="inside the repository root"):
        load_policy(policy_link, root=repository)


def test_load_policy_rejects_relative_parent_traversal(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    external_policy = tmp_path / "external-policy.json"
    external_policy.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the repository root"):
        load_policy(Path("../external-policy.json"), root=repository)


def test_main_resolves_relative_policy_under_explicit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    (github_dir / "CODEOWNERS").write_text("* @maintainer\n", encoding="utf-8")
    (github_dir / "actions-policy.json").write_text(
        json.dumps(_baseline_policy()) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_github_actions_policy.py",
            "--root",
            str(tmp_path),
            "--policy",
            ".github/actions-policy.json",
        ],
    )

    actions_policy.main()

    assert "GitHub Actions policy passed for 0 workflows." in capsys.readouterr().out
