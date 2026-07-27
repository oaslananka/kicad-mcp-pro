from __future__ import annotations

from pathlib import Path

import yaml

from kicad_mcp.web.dashboard import DASHBOARD_HTML

ROOT = Path(__file__).resolve().parents[2]
GITHUB_SPONSORS = "https://github.com/sponsors/oaslananka"
BUY_ME_A_COFFEE = "https://www.buymeacoffee.com/oaslananka"


def test_support_destinations_match_repository_funding_metadata() -> None:
    funding = yaml.safe_load((ROOT / ".github" / "FUNDING.yml").read_text(encoding="utf-8"))

    assert funding["github"] == ["oaslananka"]
    assert funding["buy_me_a_coffee"] == "oaslananka"


def test_docs_header_assets_expose_support_actions() -> None:
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    script = (ROOT / "docs" / "assets" / "support-links.js").read_text(encoding="utf-8")
    styles = (ROOT / "docs" / "assets" / "support-links.css").read_text(encoding="utf-8")

    assert "assets/support-links.css" in mkdocs
    assert "assets/support-links.js" in mkdocs
    assert GITHUB_SPONSORS in script
    assert BUY_ME_A_COFFEE in script
    assert "noopener noreferrer" in script
    assert ".kmcp-support-links" in styles


def test_dashboard_navigation_exposes_support_actions() -> None:
    assert GITHUB_SPONSORS in DASHBOARD_HTML
    assert BUY_ME_A_COFFEE in DASHBOARD_HTML
    assert "GitHub Sponsors" in DASHBOARD_HTML
    assert "Buy me a coffee" in DASHBOARD_HTML
    assert DASHBOARD_HTML.count('rel="noopener noreferrer"') >= 4


def test_tauri_bootstrap_screen_exposes_support_actions() -> None:
    html = (ROOT / "src-tauri" / "frontend" / "index.html").read_text(encoding="utf-8")

    assert GITHUB_SPONSORS in html
    assert BUY_ME_A_COFFEE in html
    assert "GitHub Sponsors" in html
    assert "Buy me a coffee" in html
    assert html.count('rel="noopener noreferrer"') >= 2
