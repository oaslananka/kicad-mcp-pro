"""Regression checks for KiCad's official macOS app-bundle symbol discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp import discovery


@pytest.mark.parametrize("via_symlink", [False, True])
def test_mounted_macos_app_bundle_beats_preinstalled_host_libraries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, via_symlink: bool
) -> None:
    """A verified DMG CLI must never inherit a different installed KiCad's pins."""
    app = tmp_path / "mounted official KiCad 10.0.7" / "KiCad.app"
    cli = app / "Contents" / "MacOS" / "kicad-cli"
    cli.parent.mkdir(parents=True)
    cli.write_text("executable")
    support = app / "Contents" / "SharedSupport"
    symbols = support / "symbols"
    footprints = support / "footprints"
    symbols.mkdir(parents=True)
    footprints.mkdir()
    (symbols / "Device.kicad_sym").write_text("(kicad_symbol_lib)")
    (symbols / "RF_Module.kicad_sym").write_text("(kicad_symbol_lib)")

    stale = tmp_path / "Applications" / "KiCad.app" / "Contents" / "SharedSupport"
    (stale / "symbols").mkdir(parents=True)
    (stale / "symbols" / "Device.kicad_sym").write_text("(stale)")
    monkeypatch.setattr(discovery.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(discovery, "_platform_library_roots", lambda _: [stale])

    candidate = cli
    if via_symlink:
        candidate = tmp_path / "bin" / "kicad-cli"
        candidate.parent.mkdir()
        try:
            candidate.symlink_to(cli)
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")

    found = discovery.discover_library_paths(candidate)
    assert found == {
        "root": support,
        "symbols": symbols,
        "footprints": footprints,
    }
    assert found["symbols"] != stale / "symbols"


def test_linux_symbol_path_discovery_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """macOS bundle lookup must not alter standard Linux distribution paths."""
    usr_share = tmp_path / "usr" / "share" / "kicad"
    (usr_share / "symbols").mkdir(parents=True)
    (usr_share / "footprints").mkdir()
    cli = tmp_path / "usr" / "bin" / "kicad-cli"
    cli.parent.mkdir(parents=True)
    cli.touch()
    monkeypatch.setattr(discovery.platform, "system", lambda: "Linux")
    monkeypatch.setattr(discovery, "_platform_library_roots", lambda _: [usr_share])

    assert discovery.discover_library_paths(cli) == {
        "root": usr_share,
        "symbols": usr_share / "symbols",
        "footprints": usr_share / "footprints",
    }
