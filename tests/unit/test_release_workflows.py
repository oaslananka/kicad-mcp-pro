from __future__ import annotations

import json
from pathlib import Path

from scripts.check_github_actions_policy import has_sha_pinned_action

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _read_json(path: str) -> dict[str, object]:
    return json.loads(_read(path))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_protocol_schema_release_contract_matches_existing_release_history() -> None:
    package = _read_json("packages/protocol-schemas/package.json")
    manifest = _read_json(".release-please-manifest.json")
    config = _read_json("release-please-config.json")
    workflow = _read(".github/workflows/publish-protocol-schemas.yml")

    protocol_config = config["packages"]["packages/protocol-schemas"]
    assert manifest["packages/protocol-schemas"] == package["version"]
    assert protocol_config["component"] == "protocol-schemas"
    assert protocol_config["tag-prefix"] == "protocol-schemas-v"
    assert "startsWith(github.event.release.tag_name, 'protocol-schemas-v')" in workflow


def test_python_trusted_publish_is_tag_gated_and_provenance_verified() -> None:
    workflow = _read(".github/workflows/publish-python.yml")

    assert 'tags:\n      - "mcp-server-v*"' in workflow
    assert "\n  release:" not in workflow
    assert "inputs.target == 'pypi'" not in workflow
    assert "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'" in workflow
    assert "startsWith(github.ref, 'refs/tags/mcp-server-v')" in workflow
    assert workflow.count("verify-pypi-provenance") == 2
    assert "pypi-attestations verify pypi" not in workflow
    assert "--staging" not in workflow
    assert "--publisher-environment testpypi \\\n            --artifacts dist" in workflow
    assert "--publisher-environment pypi \\\n            --artifacts dist" in workflow
    assert (
        workflow.count(
            "--group release python scripts/generate_release_evidence.py verify-pypi-provenance"
        )
        == 2
    )
    assert workflow.count("--publisher-repository oaslananka/kicad-mcp-pro") == 2
    assert "--publisher-environment pypi" in workflow
    assert "--publisher-environment testpypi" in workflow


def test_python_token_fallback_is_manual_approved_and_tokenized() -> None:
    workflow = _read(".github/workflows/publish-python-token.yml")

    assert "workflow_dispatch:" in workflow
    assert "\n  release:" not in workflow
    assert "password: ${{ secrets.PYPI_PUBLISH_TOKEN }}" in workflow
    assert "attestations: false" in workflow
    assert "Check if version already published" in workflow
    assert "steps.check-published.outputs.already_published != 'true'" in workflow
    assert "github.repository_owner == 'oaslananka'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "inputs.confirm_token_fallback == true" in workflow
    assert "incident_reference:" in workflow
    assert "Validate emergency authorization" in workflow
    assert "pypi-token" in workflow
    assert "testpypi-token" in workflow
    assert has_sha_pinned_action(workflow, "pypa/gh-action-pypi-publish")
    assert "id-token: write" not in workflow


def test_manual_production_publish_requires_existing_release_tags() -> None:
    npm_workflow = _read(".github/workflows/publish-npm.yml")
    registry_workflow = _read(".github/workflows/publish-mcp-registry.yml")

    for workflow, prefix in (
        (npm_workflow, "mcp-npm-v"),
        (registry_workflow, "mcp-server-v"),
    ):
        _require("release_tag:" in workflow, "test contract failed")
        _require(f"startsWith(inputs.release_tag, '{prefix}')" in workflow, "test contract failed")
        _require("Verify immutable release source" in workflow, "test contract failed")
        _require('gh release view "$RELEASE_TAG"' in workflow, "test contract failed")
        _require(
            'tag_sha="$(git rev-list -n1 "refs/tags/${RELEASE_TAG}")"' in workflow,
            "test contract failed",
        )
        _require('head_sha="$(git rev-parse HEAD)"' in workflow, "test contract failed")
        _require('test "$tag_sha" = "$head_sha"' in workflow, "test contract failed")


def test_publish_workflows_are_idempotent_for_existing_versions() -> None:
    python_workflow = _read(".github/workflows/publish-python.yml")
    npm_workflow = _read(".github/workflows/publish-npm.yml")

    assert python_workflow.count("Check if version already published") == 2
    assert python_workflow.count("steps.check-published.outputs.already_published != 'true'") == 2
    assert "Check if version already published" in npm_workflow
    assert "steps.check-published.outputs.already_published != 'true'" in npm_workflow


def test_npm_publishers_use_oidc_without_long_lived_tokens() -> None:
    for path in (".github/workflows/publish-npm.yml",):
        workflow = _read(path)
        _require("id-token: write" in workflow, f"{path} must request OIDC")
        _require("npm publish" in workflow, f"{path} must publish through npm CLI")
        _require("NPM_TOKEN" not in workflow, f"{path} must not use NPM_TOKEN")
        _require("NODE_AUTH_TOKEN" not in workflow, f"{path} must not inject NODE_AUTH_TOKEN")
        _require("environment: npm" in workflow, f"{path} must bind the npm environment")


def test_release_automation_uses_short_lived_github_app_token() -> None:
    release = _read(".github/workflows/release-please.yml")
    audit = _read(".github/workflows/repository-settings-audit.yml")
    action = "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1"

    for workflow in (release, audit):
        _require(action in workflow, "GitHub App token action must be SHA pinned")
        _require(
            "vars.OASLANANKA_OPS_APP_CLIENT_ID" in workflow,
            "GitHub App client ID must come from a repository variable",
        )
        _require(
            "secrets.OASLANANKA_OPS_APP_PRIVATE_KEY" in workflow,
            "GitHub App private key must come from a repository secret",
        )
        _require("RELEASE_PLEASE_TOKEN" not in workflow, "long-lived release PAT must be removed")

    _require(
        "permission-contents: write" in release and "permission-pull-requests: write" in release,
        "release installation token permissions must be explicit",
    )
    _require(
        "permission-actions: read" in audit and "permission-administration: read" in audit,
        "audit installation token permissions must be explicit",
    )


def test_container_publish_uses_immutable_release_tag_for_production() -> None:
    workflow = _read(".github/workflows/publish-mcp-container.yml")

    _require("Resolve image version" in workflow, "test contract failed")
    _require("Verify immutable release source" in workflow, "test contract failed")
    _require("startsWith(inputs.release_tag, 'mcp-server-v')" in workflow, "test contract failed")
    checkout_release_ref = (
        "ref: ${{ github.event_name == 'release' && "
        "github.event.release.tag_name || inputs.release_tag }}"
    )
    _require(checkout_release_ref in workflow, "test contract failed")
    _require('gh release view "$RELEASE_TAG"' in workflow, "test contract failed")
    _require(
        "type=raw,value=${{ steps.source.outputs.version }}" in workflow, "test contract failed"
    )
    _require(
        "KICAD_MCP_VERSION=${{ steps.source.outputs.version }}" in workflow, "test contract failed"
    )
    _require("VCS_REF=${{ steps.source.outputs.sha }}" in workflow, "test contract failed")
    _require("environment: ghcr" in workflow, "test contract failed")
    stable_latest_rule = (
        "type=raw,value=latest,enable=${{ github.event_name == 'release' && "
        "github.event.release.prerelease == false }}"
    )
    _require(stable_latest_rule in workflow, "test contract failed")
