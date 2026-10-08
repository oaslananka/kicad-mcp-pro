from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

from kicad_mcp import discovery


def test_candidate_cli_paths_cover_darwin_and_linux(monkeypatch) -> None:
    monkeypatch.setattr(discovery.platform, "system", lambda: "Darwin")
    darwin = discovery._candidate_cli_paths()
    assert darwin[0] == Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")

    monkeypatch.setattr(discovery.platform, "system", lambda: "Linux")
    linux = discovery._candidate_cli_paths()
    assert linux[0] == Path("/usr/bin/kicad-cli")
    assert Path("/flatpak/exports/bin/kicad-cli") in linux


def test_discover_via_kipy_import_error_and_success(monkeypatch, tmp_path: Path) -> None:
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "kipy.kicad":
            raise ImportError("missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert discovery._discover_via_kipy() is None
    monkeypatch.setattr(builtins, "__import__", original_import)

    cli = tmp_path / "kicad-cli"
    cli.write_text("", encoding="utf-8")

    fake_pkg = types.ModuleType("kipy")
    fake_module = types.ModuleType("kipy.kicad")
    closed: list[str] = []

    class FakeKiCad:
        def __init__(self, *, headless: bool = False, timeout_ms: int = 0) -> None:
            assert headless is True
            assert timeout_ms == 1000

        def get_kicad_binary_path(self, name: str) -> str:
            assert name == "kicad-cli"
            return str(cli)

        def close(self) -> None:
            closed.append("closed")

    fake_module.KiCad = FakeKiCad
    monkeypatch.setitem(sys.modules, "kipy", fake_pkg)
    monkeypatch.setitem(sys.modules, "kipy.kicad", fake_module)

    assert discovery._discover_via_kipy() == cli
    assert closed == ["closed"]


def test_discover_via_kipy_handles_runtime_and_close_failures(monkeypatch) -> None:
    fake_pkg = types.ModuleType("kipy")
    fake_module = types.ModuleType("kipy.kicad")
    debug_events: list[str] = []

    class FakeKiCad:
        def __init__(self, *, headless: bool = False, timeout_ms: int = 0) -> None:
            _ = (headless, timeout_ms)

        def get_kicad_binary_path(self, _name: str) -> str:
            raise RuntimeError("broken")

        def close(self) -> None:
            raise RuntimeError("close failed")

    fake_module.KiCad = FakeKiCad
    monkeypatch.setitem(sys.modules, "kipy", fake_pkg)
    monkeypatch.setitem(sys.modules, "kipy.kicad", fake_module)
    monkeypatch.setattr(
        discovery.logger,
        "debug",
        lambda event, **kwargs: debug_events.append(event),
    )

    assert discovery._discover_via_kipy() is None
    assert debug_events == ["kipy_cli_discovery_failed", "kipy_headless_close_failed"]


def test_discover_kicad_cli_prefers_kipy_path_and_candidates(monkeypatch, tmp_path: Path) -> None:
    kipy_cli = tmp_path / "from-kipy"
    path_cli = tmp_path / "from-path"
    candidate_cli = tmp_path / "candidate"
    kipy_cli.write_text("", encoding="utf-8")
    path_cli.write_text("", encoding="utf-8")
    candidate_cli.write_text("", encoding="utf-8")

    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: kipy_cli)
    monkeypatch.setattr(discovery.shutil, "which", lambda _name: str(path_cli))
    monkeypatch.setattr(discovery, "_candidate_cli_paths", lambda: [candidate_cli])
    assert discovery.discover_kicad_cli() == kipy_cli

    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    assert discovery.discover_kicad_cli() == path_cli

    monkeypatch.setattr(discovery.shutil, "which", lambda _name: None)
    assert discovery.discover_kicad_cli() == candidate_cli

    missing_candidate = tmp_path / "missing-candidate"
    monkeypatch.setattr(discovery, "_candidate_cli_paths", lambda: [missing_candidate])
    # The fallback is platform-specific, not dependent on the CI host OS.
    monkeypatch.setattr(discovery.platform, "system", lambda: "Linux")
    assert discovery.discover_kicad_cli() == missing_candidate

    # Windows must not claim an installation path for a missing CLI.
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    assert discovery.discover_kicad_cli() == Path("kicad-cli")


def test_get_cli_capabilities_and_recent_projects_cover_fallbacks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    missing_cli = tmp_path / "missing-kicad-cli"
    discovery.get_cli_capabilities.cache_clear()
    monkeypatch.setattr(discovery, "find_kicad_version", lambda _cli: "KiCad 10.0.1")
    assert discovery.get_cli_capabilities(missing_cli).version == "KiCad 10.0.1"

    monkeypatch.setattr(discovery.platform, "system", lambda: "Darwin")
    # Substitute the platform install locations: the host may genuinely have
    # KiCad under /Applications, which would otherwise make this assertion
    # depend on the developer's machine rather than on the code.
    monkeypatch.setattr(discovery, "_platform_library_roots", lambda _system: [])
    assert discovery.discover_library_paths(tmp_path / "cli") == {
        "root": None,
        "symbols": None,
        "footprints": None,
    }

    home = tmp_path / "home"
    config_dir = home / "Library" / "Preferences" / "kicad" / "10.0"
    config_dir.mkdir(parents=True)
    (config_dir / "kicad_common.json").write_text("{invalid json", encoding="utf-8")
    monkeypatch.setattr(discovery.Path, "home", lambda: home)
    assert discovery.find_recent_projects() == []

    assert discovery.scan_project_dir(tmp_path / "does-not-exist") == {
        "project": None,
        "pcb": None,
        "schematic": None,
    }


def test_discover_library_paths_returns_none_when_nothing_is_installed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A host with no KiCad library anywhere yields an all-None mapping."""
    monkeypatch.setattr(discovery, "_platform_library_roots", lambda _system: [])

    assert discovery.discover_library_paths(tmp_path / "missing-kicad-cli") == {
        "root": None,
        "symbols": None,
        "footprints": None,
    }


def test_platform_library_roots_cover_every_supported_platform() -> None:
    """Each platform reports its own conventional install roots."""
    windows = discovery._platform_library_roots("Windows")
    macos = discovery._platform_library_roots("Darwin")
    linux = discovery._platform_library_roots("Linux")

    assert all(str(path).startswith("C:\\") for path in windows)
    assert any("KiCad.app" in str(path) for path in macos)
    assert linux == [Path("/usr/share/kicad"), Path("/usr/local/share/kicad")]
    # An unrecognised platform must fall back to the POSIX locations, never to
    # an empty list that would silently disable discovery.
    assert discovery._platform_library_roots("FreeBSD") == linux


def _fake_kipy(monkeypatch, reported_path: Path) -> None:
    """Install a fake kipy that reports ``reported_path`` as the kicad-cli location."""
    fake_pkg = types.ModuleType("kipy")
    fake_module = types.ModuleType("kipy.kicad")

    class FakeKiCad:
        def __init__(self, timeout_ms: int = 0) -> None:
            self.timeout_ms = timeout_ms

        def get_kicad_binary_path(self, name: str) -> str:
            return str(reported_path)

        def close(self) -> None:
            return None

    fake_module.KiCad = FakeKiCad  # type: ignore[attr-defined]
    fake_pkg.kicad = fake_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kipy", fake_pkg)
    monkeypatch.setitem(sys.modules, "kipy.kicad", fake_module)


def test_discover_via_kipy_returns_none_when_reported_cli_missing(
    monkeypatch, tmp_path: Path
) -> None:
    """A kipy-reported path that no longer exists (stale cache, closed KiCad) is rejected."""
    missing = tmp_path / "kicad-cli"
    _fake_kipy(monkeypatch, missing)
    assert discovery._discover_via_kipy() is None


def test_is_ephemeral_cli_path_flags_appimage_mounts(tmp_path: Path) -> None:
    ephemeral = "/tmp/.mount_kicadAbC123/usr/bin/kicad-cli"  # noqa: S108 - test data, not created
    assert discovery._is_ephemeral_cli_path(Path(ephemeral))
    assert discovery._is_ephemeral_cli_path(Path("/run/user/1000/.mount_x/usr/bin/kicad-cli"))
    assert not discovery._is_ephemeral_cli_path(Path("/usr/bin/kicad-cli"))
    assert not discovery._is_ephemeral_cli_path(tmp_path / "kicad-cli")


def test_is_ephemeral_cli_path_flags_appimage_mount_under_custom_runtime_dir() -> None:
    cli = Path("/home/user/.runtime/.mount_KiCadXYZ/usr/bin/kicad-cli")
    assert discovery._is_ephemeral_cli_path(cli)


def test_discover_via_kipy_rejects_ephemeral_appimage_mount(monkeypatch, tmp_path: Path) -> None:
    """A running AppImage reports its own FUSE mount, which dies when KiCad exits."""
    mount = tmp_path / ".mount_kicadZz9" / "usr" / "bin"
    mount.mkdir(parents=True)
    cli = mount / "kicad-cli"
    cli.write_text("", encoding="utf-8")

    _fake_kipy(monkeypatch, cli)
    debug_events: list[str] = []
    monkeypatch.setattr(discovery.logger, "debug", lambda event, **kw: debug_events.append(event))

    assert discovery._discover_via_kipy() is None
    assert "kipy_cli_discovery_ephemeral" in debug_events


def test_discover_kicad_cli_falls_through_to_path_when_kipy_is_ephemeral(
    monkeypatch, tmp_path: Path
) -> None:
    """The stable kicad-cli on PATH must win over a path inside a transient mount."""
    stable = tmp_path / "stable" / "kicad-cli"
    stable.parent.mkdir(parents=True)
    stable.write_text("", encoding="utf-8")

    mount = tmp_path / ".mount_kicadZz9" / "usr" / "bin"
    mount.mkdir(parents=True)
    ephemeral = mount / "kicad-cli"
    ephemeral.write_text("", encoding="utf-8")

    _fake_kipy(monkeypatch, ephemeral)
    monkeypatch.setattr(discovery.shutil, "which", lambda name: str(stable))

    assert discovery.discover_kicad_cli() == stable
