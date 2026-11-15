"""Checks for GitHub Pages artifact publishing and a usable documentation landing page."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_docs_publish_uses_native_pages_artifact_and_least_privilege() -> None:
    source = (ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(source)
    events = workflow.get("on", workflow.get(True))

    assert "push" in events and "pull_request" in events and "workflow_dispatch" in events
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["build"]["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["deploy"]["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
    assert workflow["jobs"]["deploy"]["environment"]["name"] == "github-pages"
    assert "github.event_name != 'pull_request'" in workflow["jobs"]["deploy"]["if"]
    assert "uv run properdocs build -f mkdocs.yml --strict" in source
    assert "gh-pages" not in source
    assert "peaceiris/" not in source
    assert "force_orphan" not in source
    names = [
        step["uses"].split("@")[0]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "uses" in step
    ]
    for required in (
        "actions/configure-pages",
        "actions/upload-pages-artifact",
        "actions/deploy-pages",
    ):
        assert names.count(required) == 1
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[0-9a-f]{40}", step["uses"].split("@", 1)[1])


def test_home_helps_new_users_start_without_an_account() -> None:
    home = (ROOT / "docs/index.md").read_text(encoding="utf-8")
    mkdocs = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    styles = (ROOT / "docs/assets/site.css").read_text(encoding="utf-8")

    assert "navigation.sections" not in mkdocs["theme"]["features"]
    assert "navigation.top" in mkdocs["theme"]["features"]
    assert "toc.follow" in mkdocs["theme"]["features"]
    assert "hide:\n  - toc" in home
    for text in (
        "Install locally",
        "Connect an AI client",
        "Optional Cloud access",
        "uv tool install kicad-mcp-pro",
        "kicad-mcp-pro setup",
        "kicad-mcp-pro doctor",
        "without signing in",
        "start read-only",
    ):
        assert text.casefold() in home.casefold(), text
    for url in (
        "installation/",
        "client-configuration/",
        "workflows/first-pcb/",
        "troubleshooting/",
        "tools-reference/",
    ):
        assert f'href="{url}"' in home
    assert "Project identity" not in home
    assert "Documentation map" not in home
    assert ".kmcp-home-grid" in styles
    assert "prefers-reduced-motion" in styles


def test_non_support_assets_are_standard_mkdocs_theme_responsibility() -> None:
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "extra_javascript:" not in mkdocs
    assert not (ROOT / "docs/assets/support-links.js").exists()
    assert not (ROOT / "docs/assets/support-links.css").exists()
    assert "assets/site.css" in mkdocs
