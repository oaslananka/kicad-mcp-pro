"""Doc contract for the release asset immutability inventory (upstream issue #1179)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "development" / "release-asset-immutability.md"
DOC_NAV_PATH = "development/release-asset-immutability.md"


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_is_listed_in_mkdocs_nav() -> None:
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert f": {DOC_NAV_PATH}" in mkdocs


@pytest.mark.parametrize(
    "linking_doc",
    ["docs/development/release-process.md", "docs/security/release-integrity.md"],
)
def test_release_docs_link_to_inventory(linking_doc: str) -> None:
    text = (ROOT / linking_doc).read_text(encoding="utf-8")

    assert "release-asset-immutability.md" in text


def test_doc_names_every_release_family_tag_prefix() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    prefixes = [package["tag-prefix"] for package in config["packages"].values()]

    text = _doc()

    assert prefixes
    for prefix in prefixes:
        assert f"`{prefix}`" in text


@pytest.mark.parametrize(
    "workflow",
    [
        "publish-release.yml",
        "publish-python.yml",
        "publish-npm.yml",
        "publish-mcpb.yml",
        "publish-protocol-schemas.yml",
        "publish-kicad-pcm.yml",
        "publish-mcp-container.yml",
        "publish-mcp-registry.yml",
        "gui-release.yml",
        "release.yml",
    ],
)
def test_doc_names_every_release_workflow(workflow: str) -> None:
    assert workflow in _doc()


@pytest.mark.parametrize(
    "phrase",
    [
        "#1179",
        "draft",
        "--clobber",
        "scripts/check_release_asset_mutations.py",
        "release_asset_mutations",
        "repository immutability setting is not changed",
        "release-creation mutation remains allowlisted",
        "force-tag-creation",
        "literal tag",
    ],
)
def test_doc_mentions_required_concepts(phrase: str) -> None:
    assert phrase in _doc()


def test_doc_lists_every_allowlisted_step() -> None:
    policy = json.loads((ROOT / ".github" / "actions-policy.json").read_text(encoding="utf-8"))
    text = _doc()

    for entry in policy["release_asset_mutations"]:
        assert entry["step"] in text, entry
