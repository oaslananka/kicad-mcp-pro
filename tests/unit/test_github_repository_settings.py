"""Live GitHub repository settings policy tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_github_repository_settings import (
    emit_drift_errors,
    expected_selected_patterns,
    validate_live_state,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / ".github/actions-policy.json").read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _expected_payloads() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    actions = {
        "enabled": True,
        "allowed_actions": "selected",
        "sha_pinning_required": True,
    }
    selected = {
        "github_owned_allowed": True,
        "verified_allowed": True,
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
    actions["sha_pinning_required"] = False
    workflow["default_workflow_permissions"] = "write"
    workflow["can_approve_pull_request_reviews"] = True
    selected["patterns_allowed"] = ["actions/checkout@*"]

    errors = validate_live_state(POLICY, actions, selected, workflow)

    assert any("sha_pinning_required" in error for error in errors)
    assert any("default_workflow_permissions" in error for error in errors)
    assert any("can_approve_pull_request_reviews" in error for error in errors)
    assert any("patterns_allowed" in error for error in errors)


def test_live_state_skips_selected_details_when_actions_are_not_selected() -> None:
    actions, selected, workflow = _expected_payloads()
    actions["allowed_actions"] = "all"

    errors = validate_live_state(POLICY, actions, {}, workflow)

    assert errors == ["actions.allowed_actions drift: actual='all' expected='selected'"]


def test_emit_drift_errors_adds_github_annotations(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    emit_drift_errors(["actions.allowed_actions drift: actual='all' expected='selected'"])

    captured = capsys.readouterr()
    assert "- actions.allowed_actions drift" in captured.err
    assert (
        "::error file=.github/actions-policy.json,line=1,title=Repository settings drift::"
        "actions.allowed_actions drift: actual='all' expected='selected'"
    ) in captured.err


def test_emit_ruleset_drift_points_to_ruleset_policy(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    emit_drift_errors(["ruleset.release-tags missing from live repository"])

    captured = capsys.readouterr()
    assert (
        "::error file=.github/rulesets/release-tags.json,line=1,"
        "title=Repository settings drift::ruleset.release-tags missing from live repository"
    ) in captured.err


def test_repository_settings_audit_workflow_is_default_branch_only_and_read_only() -> None:
    workflow = (ROOT / ".github/workflows/repository-settings-audit.yml").read_text(
        encoding="utf-8"
    )

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    _require("secrets.RELEASE_PLEASE_TOKEN" not in workflow, "audit must not use release PAT")
    _require("steps.audit-app-token.outputs.token" in workflow, "audit must use app token")
    _require("permission-actions: read" in workflow, "audit token must request Actions read")
    _require(
        "permission-administration: read" in workflow,
        "audit token must request Administration read",
    )
    assert "check_github_repository_settings.py" in workflow
    assert "persist-credentials: false" in workflow


def _publish_environment(name: str) -> dict[str, object]:
    return {"name": name, "protection_rules": []}


def test_repository_settings_audit_covers_all_protected_publish_environments() -> None:
    source = (ROOT / "scripts" / "check_github_repository_settings.py").read_text(encoding="utf-8")

    for environment in POLICY["protected_publish_environments"]:
        _require(f'"environment:{environment}"' in source, "test contract failed")
        _require(
            f'"{environment}": _github_api("environment:{environment}", token)' in source,
            "test contract failed",
        )


def test_publish_environment_protection_matches_policy_and_reports_drift() -> None:
    from scripts.check_github_repository_settings import validate_environment_protection

    environments = {
        "npm": _publish_environment("npm"),
        "mcp-registry": _publish_environment("mcp-registry"),
        "ghcr": _publish_environment("ghcr"),
    }
    assert validate_environment_protection(POLICY, environments) == []
    environments["npm"] = {
        "name": "npm",
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [{"type": "User", "reviewer": {"login": "oaslananka"}}],
            }
        ],
    }

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
    for value in (
        "--help",
        "oaslananka/repo;echo",
        "oaslananka/repo/extra",
        "owner/../repo",
        "someone/other-repo",
    ):
        with pytest.raises(ValueError, match="owner/repository"):
            validate_repository_name(value)


def test_ruleset_desired_state_matches_live_shape_and_reports_drift() -> None:
    from scripts.check_github_repository_settings import (
        load_ruleset_policies,
        validate_ruleset_state,
    )

    expected = load_ruleset_policies()
    live = {
        name: {
            **payload,
            "id": index,
            "source": "oaslananka/kicad-mcp-pro",
            "source_type": "Repository",
            "current_user_can_bypass": "never",
        }
        for index, (name, payload) in enumerate(expected.items(), start=1)
    }

    assert validate_ruleset_state(expected, live) == []

    live["main-standard"] = json.loads(json.dumps(live["main-standard"]))
    pull_request_rule = next(
        rule for rule in live["main-standard"]["rules"] if rule["type"] == "pull_request"
    )
    pull_request_rule["parameters"]["allowed_merge_methods"] = ["merge", "squash"]

    errors = validate_ruleset_state(expected, live)
    assert any("ruleset.main-standard drift" in error for error in errors)


def test_ruleset_desired_state_requires_main_and_release_tag_policies() -> None:
    from scripts.check_github_repository_settings import load_ruleset_policies

    policies = load_ruleset_policies()

    assert set(policies) == {"main-standard", "release-tags"}
    assert policies["main-standard"]["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert policies["release-tags"]["rules"] == [{"type": "deletion"}, {"type": "update"}]


def test_ruleset_validation_reports_missing_live_ruleset() -> None:
    from scripts.check_github_repository_settings import (
        load_ruleset_policies,
        validate_ruleset_state,
    )

    expected = load_ruleset_policies()
    errors = validate_ruleset_state(expected, {"main-standard": expected["main-standard"]})

    assert errors == ["ruleset.release-tags missing from live repository"]


def test_repository_settings_audit_queries_live_rulesets() -> None:
    source = (ROOT / "scripts" / "check_github_repository_settings.py").read_text(encoding="utf-8")

    assert '"/repos/oaslananka/kicad-mcp-pro/rulesets"' in source
    assert "_github_rulesets(token)" in source
    assert "validate_ruleset_state(expected_rulesets, live_rulesets)" in source
