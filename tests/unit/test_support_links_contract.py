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


def test_tauri_bootstrap_screen_exposes_support_actions() -> None:
    html = (ROOT / "src-tauri" / "frontend" / "index.html").read_text(encoding="utf-8")

    assert GITHUB_SPONSORS in html
    assert BUY_ME_A_COFFEE in html
    assert "GitHub Sponsors" in html
    assert "Buy me a coffee" in html
    assert html.count('rel="noopener noreferrer"') >= 2


def test_native_browser_bridge_preserves_browser_security_boundary() -> None:
    rust = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    html = (ROOT / "src-tauri" / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "fn allowed_external_link(url: &str) -> bool" in rust
    assert "fn open_external_link(" in rust
    assert "app.shell().open(url, None)" in rust
    assert "open_external_link," in rust
    for url in [GITHUB_SPONSORS, BUY_ME_A_COFFEE]:
        assert url in rust
        assert url in html
    assert "await invoke('open_external_link', {url: link.href})" in html
    assert "await invoke('open_external_link', {url: link.href})" in DASHBOARD_HTML
    assert "typeof invoke !== 'function'" in DASHBOARD_HTML
    assert "Could not open the system browser" in DASHBOARD_HTML
    assert "https://kicad-mcp-pro.oaslananka.dev/sign-in" in rust
