"""Fail-closed, side-effect-free staging for a future draft-first GUI release."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.stage_gui_draft_assets import stage_gui_draft_assets

TAG = "kicad-mcp-gui-v4.7.0"
FILES = {
    "gui-linux-tauri": (
        "KiCad-MCP-Pro_4.7.0_amd64.deb",
        "KiCad-MCP-Pro-4.7.0-1.x86_64.rpm",
        "KiCad-MCP-Pro_4.7.0_amd64.AppImage",
    ),
    "gui-macos-tauri": ("KiCad-MCP-Pro_4.7.0_aarch64.dmg",),
    "gui-windows-tauri": (
        "KiCad-MCP-Pro_4.7.0_x64_en-US.msi",
        "KiCad-MCP-Pro_4.7.0_x64-setup.exe",
    ),
}


def _artifacts(root: Path) -> Path:
    inp = root / "artifacts"
    for role, names in FILES.items():
        for name in names:
            path = inp / role / "bundle" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"validated fixture: {name}".encode())
    return inp


def test_stages_only_expected_platform_and_version_installers(tmp_path: Path) -> None:
    src = _artifacts(tmp_path)
    output = tmp_path / "output"
    names = stage_gui_draft_assets(src, output, TAG)
    assert len(names) == 6
    assert names == sorted(p.name for p in output.iterdir())
    assert "linux_KiCad-MCP-Pro_4.7.0_amd64.deb" in names
    assert "windows_KiCad-MCP-Pro_4.7.0_x64-setup.exe" in names
    for role, sources in FILES.items():
        for original in sources:
            p = next((src / role).rglob(original))
            expected = output / (role.split("-")[1].replace("macos", "macos") + "_" + original)
            assert p.read_bytes() == expected.read_bytes()


@pytest.mark.parametrize(
    "tag",
    [
        "kicad-mcp-gui-v4.7",
        "kicad-mcp-gui-v4.7.0-rc1",
        "mcp-server-v4.7.0",
        "kicad-mcp-gui-v4.7.0/../evil",
        "",
        "kicad-mcp-gui-v4.7.0\n",
    ],
)
def test_invalid_release_tags_rejected_before_reading(tmp_path: Path, tag: str) -> None:
    with pytest.raises(ValueError, match="stable GUI release tag"):
        stage_gui_draft_assets(tmp_path / "does-not-exist", tmp_path / "output", tag)


def test_missing_platform_artifact_rejected_without_output(tmp_path: Path) -> None:
    src = _artifacts(tmp_path)
    next((src / "gui-macos-tauri").rglob("*.dmg")).unlink()
    with pytest.raises(ValueError, match="missing required GUI installers"):
        stage_gui_draft_assets(src, tmp_path / "output", TAG)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("rogue", ["wrong-version", "extra-file", "unexpected-platform", "empty"])
def test_unexpected_or_empty_artifacts_fail_closed(tmp_path: Path, rogue: str) -> None:
    src = _artifacts(tmp_path)
    if rogue == "wrong-version":
        (src / "gui-windows-tauri" / "bundle" / "KiCad-MCP-Pro_4.7.1_x64-setup.exe").write_bytes(
            b"oops"
        )
    elif rogue == "extra-file":
        (src / "gui-linux-tauri" / "bundle" / "undeclared.txt").write_bytes(b"oops")
    elif rogue == "unexpected-platform":
        (src / "gui-linux-tauri" / "bundle" / "KiCad-MCP-Pro_4.7.0_x64_en-US.msi").write_bytes(
            b"oops"
        )
    elif rogue == "empty":
        next((src / "gui-linux-tauri").rglob("*.deb")).write_bytes(b"")
    with pytest.raises(ValueError):
        stage_gui_draft_assets(src, tmp_path / "output", TAG)
    assert not (tmp_path / "output").exists()


def test_symlink_escape_fails_closed(tmp_path: Path) -> None:
    src = _artifacts(tmp_path)
    target = next((src / "gui-linux-tauri").rglob("*.deb"))
    target.unlink()
    target.symlink_to(tmp_path / "not-our-file")
    with pytest.raises(ValueError):
        stage_gui_draft_assets(src, tmp_path / "output", TAG)


def test_cannot_replace_existing_or_write_within_input(tmp_path: Path) -> None:
    src = _artifacts(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    (output / "reserved.bin").write_bytes(b"must stay unchanged")
    with pytest.raises(ValueError, match="empty"):
        stage_gui_draft_assets(src, output, TAG)
    assert (output / "reserved.bin").read_bytes() == b"must stay unchanged"
    with pytest.raises(ValueError, match="overlap"):
        stage_gui_draft_assets(src, src / "gui-windows-tauri" / "output", TAG)
