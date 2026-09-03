"""Live GitHub repository settings policy tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_github_repository_settings import expected_selected_patterns, validate_live_state

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / ".github/actions-policy.json").read_text(encoding="utf-8"))


def _expected_payloads() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    actions = {
        "enabled": True,
        "allowed_actions": "selected",
        "sha_pinning_required": True,
    }
    selected = {
        "github_owned_allowed": True,
        "verified_allowed": False,
        "patterns_allowed": expected_selected_patterns(POLICY),
    }
    workflow = {
        "default_workflow_permissions": "read",
        "can_approve_pull_request_reviews": False,
    }
    return actions, selected, workflow


def test_expected_live_state_matches_hardened_policy() -> None:
    actions, selected, workflow = _expected_payloads()

    assert validate_live_state(POLICY, actions, selected, workflow) == []
    assert "aquasecurity/setup-trivy@*" in selected["patterns_allowed"]
    assert "SonarSource/sonarqube-scan-action@*" in selected["patterns_allowed"]


def test_live_state_reports_security_regressions() -> None:
    actions, selected, workflow = _expected_payloads()
    actions["allowed_actions"] = "all"
    actions["sha_pinning_required"] = False
    workflow["default_workflow_permissions"] = "write"
    workflow["can_approve_pull_request_reviews"] = True
    selected["patterns_allowed"] = ["actions/checkout@*"]

    errors = validate_live_state(POLICY, actions, selected, workflow)

    assert any("allowed_actions" in error for error in errors)
    assert any("sha_pinning_required" in error for error in errors)
    assert any("default_workflow_permissions" in error for error in errors)
    assert any("can_approve_pull_request_reviews" in error for error in errors)
    assert any("patterns_allowed" in error for error in errors)


def test_repository_settings_audit_workflow_is_default_branch_only_and_read_only() -> None:
    workflow = (ROOT / ".github/workflows/repository-settings-audit.yml").read_text(
        encoding="utf-8"
    )

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "secrets.RELEASE_PLEASE_TOKEN" in workflow
    assert "check_github_repository_settings.py" in workflow
    assert "persist-credentials: false" in workflow


def _protected_environment(name: str) -> dict[str, object]:
    return {
        "name": name,
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [{"type": "User", "reviewer": {"login": "oaslananka"}}],
            }
        ],
    }


def test_publish_environment_protection_matches_policy_and_reports_drift() -> None:
    from scripts.check_github_repository_settings import validate_environment_protection

    environments = {
        "npm": _protected_environment("npm"),
        "mcp-registry": _protected_environment("mcp-registry"),
    }
    assert validate_environment_protection(POLICY, environments) == []
    environments["npm"] = {"name": "npm", "protection_rules": []}

    errors = validate_environment_protection(POLICY, environments)
    assert any("npm.required_reviewers" in error for error in errors)


def test_repository_settings_audit_restricts_secret_to_main_ref() -> None:
    workflow = (ROOT / ".github/workflows/repository-settings-audit.yml").read_text(
        encoding="utf-8"
    )

    assert "github.ref == 'refs/heads/main'" in workflow


def test_repository_name_validation_rejects_command_like_input() -> None:
    from scripts.check_github_repository_settings import validate_repository_name

    assert validate_repository_name("oaslananka/kicad-mcp-pro") == "oaslananka/kicad-mcp-pro"
    for value in ("--help", "oaslananka/repo;echo", "oaslananka/repo/extra", "owner/../repo"):
        with pytest.raises(ValueError, match="owner/repository"):
            validate_repository_name(value)
