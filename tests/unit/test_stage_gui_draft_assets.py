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


@pytest.mark.parametrize("fault", ["missing-root", "linked-root", "unexpected-role", "linked-role"])
def test_invalid_artifact_bundle_layout_rejected(tmp_path: Path, fault: str) -> None:
    src = _artifacts(tmp_path)
    if fault == "missing-root":
        src.rename(tmp_path / "renamed-artifacts")
    elif fault == "linked-root":
        source = tmp_path / "real-artifacts"
        src.rename(source)
        src.symlink_to(source, target_is_directory=True)
    elif fault == "unexpected-role":
        (src / "unapproved-platform").mkdir()
    elif fault == "linked-role":
        target = tmp_path / "stored-windows-bundle"
        (src / "gui-windows-tauri").rename(target)
        (src / "gui-windows-tauri").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        stage_gui_draft_assets(src, tmp_path / "output", TAG)
    assert not (tmp_path / "output").exists()


def test_duplicate_installer_detected_before_output(tmp_path: Path) -> None:
    src = _artifacts(tmp_path)
    installer = next((src / "gui-macos-tauri").rglob("*.dmg"))
    duplicate = src / "gui-macos-tauri" / "another-bundle" / installer.name
    duplicate.parent.mkdir()
    duplicate.write_bytes(installer.read_bytes())
    with pytest.raises(ValueError, match="duplicate GUI installer"):
        stage_gui_draft_assets(src, tmp_path / "output", TAG)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("kind", ["symlink", "file", "empty-dir"])
def test_preexisting_staging_destination_policy(tmp_path: Path, kind: str) -> None:
    src = _artifacts(tmp_path)
    destination = tmp_path / "staging"
    if kind == "symlink":
        target = tmp_path / "destination"
        target.mkdir()
        destination.symlink_to(target, target_is_directory=True)
    elif kind == "file":
        destination.write_bytes(b"keep")
    else:
        destination.mkdir()
    if kind == "empty-dir":
        names = stage_gui_draft_assets(src, destination, TAG)
        assert len(names) == 6
    else:
        with pytest.raises(ValueError, match="empty and not a symlink"):
            stage_gui_draft_assets(src, destination, TAG)


def test_staging_cannot_write_to_parent_of_artifact_directory(tmp_path: Path) -> None:
    src = _artifacts(tmp_path)
    with pytest.raises(ValueError, match="overlap"):
        stage_gui_draft_assets(src, tmp_path, TAG)


def test_cli_success_and_validation_failure_without_publication(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    _artifacts(tmp_path)
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "scripts/stage_gui_draft_assets.py"),
        "--release-tag",
        TAG,
    ]
    good = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert good.returncode == 0, good.stderr
    payload = json.loads(good.stdout)
    assert payload == {
        "preparedAssets": sorted(
            [
                f"{role.removeprefix('gui-').removesuffix('-tauri')}_{name}"
                for role, names in FILES.items()
                for name in names
            ]
        ),
        "published": False,
    }
    command[-1] = "mcp-server-v4.7.0"
    bad = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert bad.returncode == 2
    assert "GUI draft preparation: FAIL" in bad.stderr


def test_cli_main_reports_staged_assets_and_errors_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json
    import sys

    from scripts.stage_gui_draft_assets import main

    _artifacts(tmp_path)
    argv = ["stage_gui_draft_assets.py", "--release-tag", TAG]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 0
    assert len(json.loads(capsys.readouterr().out)["preparedAssets"]) == 6
    monkeypatch.setattr(sys, "argv", [*argv[:-1], "unknown-release"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "GUI draft preparation: FAIL" in capsys.readouterr().err


@pytest.mark.parametrize("target", ["unapproved-root", "parent-traversal", "linked-parent"])
def test_untrusted_cli_output_path_rejected_before_write(tmp_path: Path, target: str) -> None:
    src = _artifacts(tmp_path)
    if target == "unapproved-root":
        dest = Path("/etc") / "kicad-mcp-pro-unapproved-draft-assets"
    elif target == "parent-traversal":
        dest = tmp_path / ".." / "unapproved-draft-assets"
    else:
        link = tmp_path / "external-parent"
        link.symlink_to("/etc", target_is_directory=True)
        dest = link / "unapproved-draft-assets"
    with pytest.raises(ValueError):
        stage_gui_draft_assets(src, dest, TAG)
    assert not (tmp_path / "unapproved-draft-assets").exists()
    assert not (tmp_path.parent / "unapproved-draft-assets").exists()


def test_unapproved_cli_input_root_rejected(tmp_path: Path) -> None:
    dest = tmp_path / "output"
    with pytest.raises(ValueError):
        stage_gui_draft_assets(Path("/etc"), dest, TAG)
    assert not dest.exists()


def test_explicit_parent_navigation_in_input_rejected(tmp_path: Path) -> None:
    src = _artifacts(tmp_path)
    dest = tmp_path / "output"
    with pytest.raises(ValueError, match="parent traversal"):
        stage_gui_draft_assets(src / "bundle" / "..", dest, TAG)
    assert not dest.exists()


def test_cli_does_not_accept_user_selected_filesystem_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from scripts.stage_gui_draft_assets import main

    _artifacts(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["stage_gui_draft_assets.py", "--release-tag", TAG, "--output-dir", "/etc"],
    )
    with pytest.raises(SystemExit) as rejected:
        main()
    assert rejected.value.code == 2
    assert not (tmp_path / "release-assets").exists()
