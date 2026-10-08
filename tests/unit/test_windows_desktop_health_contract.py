"""Windows desktop regression checks for version discovery, tray and dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from kicad_mcp import discovery
from kicad_mcp.web.dashboard import DASHBOARD_HTML

ROOT = Path(__file__).resolve().parents[2]


def test_windows_discovery_prefers_installed_stable_release(monkeypatch, tmp_path: Path) -> None:
    stable = tmp_path / "KiCad" / "10.0" / "bin" / "kicad-cli.exe"
    future = tmp_path / "KiCad" / "11.0" / "bin" / "kicad-cli.exe"
    stable.parent.mkdir(parents=True)
    future.parent.mkdir(parents=True)
    stable.touch()
    future.touch()
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    monkeypatch.setattr(discovery.shutil, "which", lambda _name: None)
    monkeypatch.setattr(discovery, "_candidate_cli_paths", lambda: [stable, future])
    assert discovery.discover_kicad_cli() == stable
    stable.unlink()
    assert discovery.discover_kicad_cli() == future


def test_windows_without_kicad_does_not_claim_future_install(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "KiCad" / "11.0" / "bin" / "kicad-cli.exe"
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    monkeypatch.setattr(discovery.shutil, "which", lambda _name: None)
    monkeypatch.setattr(discovery, "_candidate_cli_paths", lambda: [missing])
    assert discovery.discover_kicad_cli() == Path("kicad-cli")


def test_missing_auto_detected_cli_reports_installation_not_fictional_version() -> None:
    from kicad_mcp.diagnostics import _missing_cli_message

    message = _missing_cli_message(Path("kicad-cli"))
    assert "10.x" in message
    assert "11.0" not in message
    assert "Settings" in message
    explicitly_bad = Path("C:/custom/KiCad/kicad-cli.exe")
    assert str(explicitly_bad) in _missing_cli_message(explicitly_bad)


def test_windows_candidate_list_prefers_supported_stable_branch(monkeypatch) -> None:
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    candidates = [str(path) for path in discovery._candidate_cli_paths()]
    assert "KiCad\\10.0\\bin\\kicad-cli.exe" in candidates[0]
    assert "KiCad\\11.0\\bin\\kicad-cli.exe" in candidates[-1]


def test_desktop_creates_one_tray_and_restores_click_and_single_instance() -> None:
    config = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    source = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
    cargo = (ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8")
    assert "trayIcon" not in config["app"]
    assert source.count("TrayIconBuilder::new()") == 1
    assert "tauri_plugin_single_instance::init" in source
    assert "tauri-plugin-single-instance" in cargo
    assert source.index("tauri_plugin_single_instance::init") < source.index(
        ".plugin(tauri_plugin_shell::init())"
    )
    assert ".on_tray_icon_event" in source
    assert "MouseButton::Left" in source
    assert "MouseButtonState::Up" in source
    assert "show_main_window(tray.app_handle())" in source
    assert '"show" => show_main_window(app)' in source


def test_dashboard_health_long_windows_path_is_wrappable() -> None:
    assert "#health-checks .row { display: block;" in DASHBOARD_HTML
    assert "overflow-wrap: anywhere" in DASHBOARD_HTML
    assert "#health-checks .row .value" in DASHBOARD_HTML
    assert ":focus-visible" in DASHBOARD_HTML
    assert "grid-template-columns: minmax(0, 1fr)" in DASHBOARD_HTML
    assert '<button type="button" class="nav-item' in DASHBOARD_HTML
    assert 'data-view="settings"' in DASHBOARD_HTML
