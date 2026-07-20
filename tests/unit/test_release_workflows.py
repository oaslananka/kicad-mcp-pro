from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _read_json(path: str) -> dict[str, object]:
    return json.loads(_read(path))


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
    assert workflow.count("pypi-attestations verify pypi") == 1
    assert "--staging" not in workflow
    assert workflow.count("--repository https://github.com/oaslananka/kicad-mcp-pro") == 1
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
    assert "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b" in workflow
    assert "id-token: write" not in workflow


def test_publish_workflows_are_idempotent_for_existing_versions() -> None:
    python_workflow = _read(".github/workflows/publish-python.yml")
    npm_workflow = _read(".github/workflows/publish-npm.yml")

    assert python_workflow.count("Check if version already published") == 2
    assert python_workflow.count("steps.check-published.outputs.already_published != 'true'") == 2
    assert "Check if version already published" in npm_workflow
    assert "steps.check-published.outputs.already_published != 'true'" in npm_workflow


def test_container_publish_resolves_version_for_release_and_manual_runs() -> None:
    workflow = _read(".github/workflows/publish-mcp-container.yml")

    assert "Resolve image version" in workflow
    assert "RELEASE_TAG: ${{ github.event.release.tag_name }}" in workflow
    assert "type=raw,value=${{ steps.version.outputs.version }}" in workflow
    assert "type=match,pattern=mcp-server-v(.*),group=1" not in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.publish == true" in workflow
    assert "KICAD_MCP_VERSION=${{ steps.version.outputs.version }}" in workflow
    assert "VCS_REF=${{ github.sha }}" in workflow
