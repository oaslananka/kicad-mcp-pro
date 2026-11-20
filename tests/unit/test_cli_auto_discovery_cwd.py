"""Local repository executables must never win automatic KiCad CLI discovery."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from kicad_mcp import discovery


@pytest.mark.parametrize("relative", [True, False])
def test_cli_discovery_skips_repository_candidates_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: bool
) -> None:
    checkout = tmp_path / "untrusted-checkout"
    local_bin = checkout / "bin"
    local_bin.mkdir(parents=True)
    local_cli = local_bin / "kicad-cli"
    local_cli.touch()
    trusted_cli = tmp_path / "trusted-kicad-cli"
    trusted_cli.touch()
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    monkeypatch.setattr(discovery, "_candidate_cli_paths", lambda: [trusted_cli])
    monkeypatch.setattr(
        discovery.shutil,
        "which",
        lambda command: str(Path("bin/kicad-cli") if relative else local_cli),
    )

    assert discovery.discover_kicad_cli() == trusted_cli


def test_cli_discovery_accepts_absolute_binary_outside_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "untrusted-checkout"
    checkout.mkdir()
    trusted_cli = tmp_path / "installed" / "kicad-cli"
    trusted_cli.parent.mkdir()
    trusted_cli.touch()
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    monkeypatch.setattr(discovery.shutil, "which", lambda command: str(trusted_cli))

    assert discovery.discover_kicad_cli() == trusted_cli


@pytest.mark.skipif(os.name == "nt", reason="unprivileged Windows symlinks are not guaranteed")
def test_cli_discovery_skips_symlink_into_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "untrusted-checkout"
    checkout.mkdir()
    local_cli = checkout / "kicad-cli"
    local_cli.touch()
    link = tmp_path / "apparently-trusted-cli"
    link.symlink_to(local_cli)
    trusted_cli = tmp_path / "installed" / "kicad-cli"
    trusted_cli.parent.mkdir()
    trusted_cli.touch()
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    monkeypatch.setattr(discovery, "_candidate_cli_paths", lambda: [trusted_cli])
    monkeypatch.setattr(discovery.shutil, "which", lambda command: str(link))

    assert discovery.discover_kicad_cli() == trusted_cli


@pytest.mark.skipif(os.name != "nt", reason="Windows current-directory executable lookup")
def test_windows_implicit_cwd_executable_does_not_become_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "untrusted-checkout"
    checkout.mkdir()
    # This is an empty data file; this test never launches an executable.
    (checkout / "kicad-cli.exe").touch()
    clean_path = tmp_path / "clean-bin"
    clean_path.mkdir()
    fallback = tmp_path / "installed" / "kicad-cli.exe"
    fallback.parent.mkdir()
    fallback.touch()
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("PATH", str(clean_path))
    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    monkeypatch.setattr(discovery, "_candidate_cli_paths", lambda: [fallback])
    # The OS may already disable the unsafe implicit CWD lookup.
    selected = shutil.which("kicad-cli")
    assert selected is None or Path(selected).resolve() == (checkout / "kicad-cli.exe")
    assert discovery.discover_kicad_cli() == fallback


def test_windows_missing_cli_is_never_a_cwd_executable_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "untrusted-checkout"
    checkout.mkdir()
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    monkeypatch.setattr(discovery.shutil, "which", lambda command: None)
    monkeypatch.setattr(
        discovery, "_candidate_cli_paths", lambda: [tmp_path / "missing-installed-kicad-cli"]
    )

    cli = discovery.discover_kicad_cli()
    assert cli.is_absolute()
    assert not cli.is_relative_to(checkout)
    assert cli.suffix.casefold() == ".exe"
    assert not cli.exists()


@pytest.mark.skipif(os.name == "nt", reason="unprivileged Windows symlinks are not guaranteed")
def test_discovery_fails_closed_on_cyclic_cli_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "untrusted-checkout"
    checkout.mkdir()
    cyclic = tmp_path / "apparently-installed-cli"
    cyclic.symlink_to(cyclic.name)
    trusted_fallback = tmp_path / "trusted-fallback"
    trusted_fallback.touch()
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(discovery, "_discover_via_kipy", lambda: None)
    monkeypatch.setattr(discovery, "_candidate_cli_paths", lambda: [trusted_fallback])
    monkeypatch.setattr(discovery.shutil, "which", lambda command: str(cyclic))

    assert discovery.discover_kicad_cli() == trusted_fallback
