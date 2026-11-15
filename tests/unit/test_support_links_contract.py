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


def test_docs_home_exposes_support_without_crowding_global_header() -> None:
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    home = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    styles = (ROOT / "docs" / "assets" / "site.css").read_text(encoding="utf-8")

    assert "assets/site.css" in mkdocs
    assert "assets/support-links.js" not in mkdocs
    assert GITHUB_SPONSORS in home
    assert BUY_ME_A_COFFEE in home
    assert 'rel="noopener noreferrer"' in home
    assert ".kmcp-home-support" in styles
    assert ":focus-visible" in styles


def test_dashboard_navigation_exposes_support_actions() -> None:
    assert GITHUB_SPONSORS in DASHBOARD_HTML
    assert BUY_ME_A_COFFEE in DASHBOARD_HTML
    assert "GitHub Sponsors" in DASHBOARD_HTML
    assert "Buy me a coffee" in DASHBOARD_HTML
    assert DASHBOARD_HTML.count('rel="noopener noreferrer"') >= 4


def test_local_dashboard_exposes_real_cloud_entry_without_forcing_authentication() -> None:
    assert 'class="local-workspace-intro"' in DASHBOARD_HTML
    assert 'href="https://kicad-mcp-pro.oaslananka.dev/sign-in"' in DASHBOARD_HTML
    assert 'data-view="setup-wizard"' in DASHBOARD_HTML
    assert "Work locally without an account" in DASHBOARD_HTML
    assert "Signing in never shares local files" in DASHBOARD_HTML
    assert "window.location.hash='#setup-wizard'" in DASHBOARD_HTML


def test_mobile_dashboard_does_not_hide_sponsor_links() -> None:
    assert ".nav-sep, .nav-label { display: none; }" in DASHBOARD_HTML
    assert ".nav-support-group { display: flex" in DASHBOARD_HTML
    assert ".nav-sep, .nav-label, .nav-support-group { display: none; }" not in DASHBOARD_HTML
