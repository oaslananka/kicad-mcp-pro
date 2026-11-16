"""Regression gates for the dual-supported Node 24/26 LTS migration (#1643)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from scripts.dev_environment import load_toolchain_contract

ROOT = Path(__file__).resolve().parents[2]
NODE26 = "26.13.1"
NODE24_RANGE = ">=24.22.3 <25"
NODE26_RANGE = ">=26.13.1 <27"
DUAL_ENGINE = f"{NODE24_RANGE} || {NODE26_RANGE}"
COREPACK_WORKFLOWS = (
    "ci.yml",
    "prepare-protocol-schemas.yml",
    "publish-protocol-schemas.yml",
    "regression-zoo.yml",
    "release.yml",
)


def _package(path: str) -> dict:
    return json.loads((ROOT / path / "package.json").read_text(encoding="utf-8"))


def test_node26_bootstrap_is_exact_and_matches_verified_release_archives() -> None:
    contract = load_toolchain_contract(ROOT)
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == NODE26
    assert contract.node_version == NODE26
    expected = {
        "x86_64": (
            "linux-x64",
            "5c063e46bab0fbc1c17cc445d7ff129cbdcd0471be6ed83b6ab864f8143bc864",
        ),
        "aarch64": (
            "linux-arm64",
            "89e1853138db51e8b82d3e98ba9c0d3f2956a28e5e55ea1b7e12d25aae92d5dd",
        ),
    }
    for arch, (target, digest) in expected.items():
        artifact = contract.downloads[arch]["node"]
        assert artifact.url == f"https://nodejs.org/dist/v{NODE26}/node-v{NODE26}-{target}.tar.xz"
        assert artifact.sha256 == digest


@pytest.mark.parametrize(
    "location",
    (
        "",
        "packages/protocol-schemas",
        "packages/kicad-fixtures",
        "apps/cloud",
    ),
)
def test_node_engine_supports_patched_24_and_26_but_not_25(location: str) -> None:
    package = _package(location)
    assert package["engines"]["node"] == DUAL_ENGINE


def test_runtime_compatibility_metadata_matches_root_engine() -> None:
    matrix = yaml.safe_load((ROOT / "compatibility.yaml").read_text(encoding="utf-8"))
    assert matrix["node"]["range"] == DUAL_ENGINE
    assert matrix["node"]["primary"] == "26.x"
    assert "Node.js 26.13.1" in (ROOT / "docs/development/reproducible-bootstrap.md").read_text(
        encoding="utf-8"
    )


def test_root_package_scripts_do_not_require_bundled_corepack() -> None:
    scripts = _package("")["scripts"]
    for script_name, script in scripts.items():
        assert "corepack pnpm" not in script, script_name
    assert _package("")["packageManager"] == "pnpm@11.28.6"


@pytest.mark.parametrize("name", COREPACK_WORKFLOWS)
def test_ci_and_release_bootstrap_exact_pnpm_without_corepack(name: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))
    for job_name, job in workflow["jobs"].items():
        steps = job.get("steps", [])
        running_pnpm = [
            i
            for i, step in enumerate(steps)
            if re.search(r"\bpnpm\b", str(step.get("run", "")))
            and "npm install --global pnpm@" not in str(step.get("run", ""))
        ]
        if not running_pnpm:
            continue
        assert all("corepack" not in str(step.get("run", "")) for step in steps), (name, job_name)
        installed = [
            i
            for i, step in enumerate(steps)
            if "npm install --global pnpm@11.28.6" in str(step.get("run", ""))
        ]
        assert installed, (name, job_name)
        assert installed[0] < min(running_pnpm), (name, job_name)
        assert any("actions/setup-node@" in str(step.get("uses", "")) for step in steps), (
            name,
            job_name,
        )


def test_cloud_ci_uses_pinned_node26_and_preserves_postgres_contract() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/cloud-ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["cloud"]
    node_step = next(s for s in job["steps"] if "actions/setup-node@" in str(s.get("uses", "")))
    assert node_step["with"]["node-version-file"] == ".node-version"
    assert "postgres" in job["services"]


def test_cloud_oci_stages_share_node26_multiarchitecture_index() -> None:
    dockerfile = (ROOT / "apps/cloud/Dockerfile").read_text(encoding="utf-8")
    expected = (
        "node:26-trixie-slim@sha256:"
        "e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc"
    )
    assert f"FROM {expected} AS build" in dockerfile
    assert f"FROM {expected} AS runtime" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "USER node" in dockerfile


def test_cloud_ci_keeps_patched_node24_runtime_compatibility_lane() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/cloud-ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["node24-compat"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert "postgres" in job["services"]
    steps = job["steps"]
    node_step = next(step for step in steps if "actions/setup-node@" in str(step.get("uses", "")))
    assert node_step["with"]["node-version"] == "24.22.3"
    cloud = next(step for step in steps if step.get("working-directory") == "apps/cloud")
    assert "npm run check" in cloud["run"]
    sdk = next(
        step
        for step in steps
        if step.get("working-directory") == "integrations/chatgpt-app/apps-sdk"
    )
    assert "npm run test:smoke" in sdk["run"]


@pytest.mark.parametrize(
    "path",
    (
        "Taskfile.yml",
        "CONTRIBUTING.md",
        "apps/cloud/README.md",
        "compatibility.yaml",
        "docs/agents/mcpb.md",
        "docs/compatibility/kicad-10-0-4-feature-parity.md",
        "docs/compatibility/kicad-10-0-5-feature-parity.md",
        "docs/compatibility/kicad-10-0-6-feature-parity.md",
        "docs/compatibility/kicad-10-0-7-feature-parity.md",
        "docs/compatibility/kicad-10-to-11-migration.md",
        "docs/development/roadmap-2026.md",
        "docs/mcp/transport.md",
        "docs/openssf-best-practices.md",
        "docs/registry.md",
        "docs/release.md",
        "docs/security/github-actions-policy.md",
        "docs/submission/openai-mcp-registry.md",
        "docs/tutorials/getting-started.md",
        "docs/workflow-security.md",
        "packages/protocol-schemas/README.md",
    ),
)
def test_live_contributor_entrypoints_do_not_require_bundled_corepack(path: str) -> None:
    content = (ROOT / path).read_text(encoding="utf-8")
    assert "corepack pnpm" not in content
    assert "corepack enable" not in content


def test_contributing_setup_pins_supported_node_and_package_manager() -> None:
    contributor_guide = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Node.js 26.13.1" in contributor_guide
    assert "Node.js 24.22.3" in contributor_guide
    assert "npm install --global pnpm@11.28.6" in contributor_guide
    cloud_guide = (ROOT / "apps/cloud/README.md").read_text(encoding="utf-8")
    assert "Node.js 24 or newer" not in cloud_guide
    assert "Node.js 26.13.1" in cloud_guide
