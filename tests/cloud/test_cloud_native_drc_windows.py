"""Windows native DRC must inspect only owner-bound, isolated KiCad copies."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError, OperatorProject
from kicad_mcp.cloud_windows_project_path import copy_windows_drc_inputs

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows handle test only")

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def selected(tmp_path: Path) -> OperatorProject:
    source = tmp_path / "source"
    source.mkdir()
    (source / "LED.kicad_pcb").write_bytes(b"board contents")
    (source / "LED.kicad_pro").write_bytes(b"project settings")
    (source / "LED.kicad_dru").write_bytes(b"custom design rules")
    return OperatorProject(DEVICE, PROJECT, source, "LED")


def test_windows_copies_only_fixed_owner_bound_inputs(
    selected: OperatorProject, tmp_path: Path
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)
    assert {f.name for f in scratch.iterdir()} == {
        "LED.kicad_pcb",
        "LED.kicad_pro",
        "LED.kicad_dru",
    }
    for f in scratch.iterdir():
        assert f.read_bytes() == (selected.directory / f.name).read_bytes()
        assert f.resolve().parent == scratch


def test_windows_refuses_hardlinked_board(selected: OperatorProject, tmp_path: Path) -> None:
    board = selected.directory / "LED.kicad_pcb"
    os.link(board, tmp_path / "outside.kicad_pcb")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_refuses_linked_project(selected: OperatorProject, tmp_path: Path) -> None:
    project = selected.directory / "LED.kicad_pro"
    outside = tmp_path / "secret"
    outside.write_bytes(b"private")
    project.unlink()
    try:
        project.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Windows symlink privilege not enabled")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_refuses_missing_board(selected: OperatorProject, tmp_path: Path) -> None:
    (selected.directory / "LED.kicad_pcb").unlink()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_refuses_oversized_board(selected: OperatorProject, tmp_path: Path) -> None:
    board = selected.directory / "LED.kicad_pcb"
    with board.open("wb") as stream:
        stream.truncate(32 * 1024 * 1024 + 1)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_optional_project_file_can_be_missing(
    selected: OperatorProject, tmp_path: Path
) -> None:
    (selected.directory / "LED.kicad_pro").unlink()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)
    assert {f.name for f in scratch.iterdir()} == {"LED.kicad_pcb", "LED.kicad_dru"}


def test_native_windows_cli_drc_on_disposable_public_fixture(tmp_path: Path) -> None:
    from kicad_mcp.cloud_native_drc import summarize_native_pcb_drc
    from kicad_mcp.discovery import discover_kicad_cli

    cli = discover_kicad_cli()
    if not cli.is_file():
        pytest.skip("KiCad CLI unavailable on this Windows host")
    fixture = Path(__file__).resolve().parents[2] / (
        "packages/kicad-fixtures/fixtures/clean-led-kicad10"
    )
    source = tmp_path / "fixture"
    source.mkdir()
    originals = {}
    for item in fixture.iterdir():
        originals[item.name] = item.read_bytes()
        shutil.copyfile(item, source / item.name)
    project = OperatorProject(DEVICE, PROJECT, source, "clean-led-kicad10")
    summary = summarize_native_pcb_drc(project)
    assert summary.keys() == {"violations", "unconnectedItems"}
    assert summary["violations"] >= 0
    assert summary["unconnectedItems"] >= 0
    assert {f.name: f.read_bytes() for f in source.iterdir()} == originals
