"""Fail-closed native DRC preview: local only, no Cloud operation capability."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.cloud_native_drc import summarize_native_pcb_drc
from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError, OperatorProject

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX-only file-descriptor walk")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def selected(tmp_path: Path) -> OperatorProject:
    folder = tmp_path / "approved"
    folder.mkdir()
    (folder / "TEST.kicad_pcb").write_text("PRIVATE BOARD", encoding="utf-8")
    (folder / "TEST.kicad_pro").write_text("PRIVATE PROJECT", encoding="utf-8")
    return OperatorProject(DEVICE, PROJECT, folder, "TEST")


def _fake_success(monkeypatch: pytest.MonkeyPatch, selected: OperatorProject) -> list[str]:
    original = (
        (selected.directory / "TEST.kicad_pcb").read_bytes()
        if (selected.directory / "TEST.kicad_pcb").is_file()
        else None
    )
    invoked: list[str] = []

    def native(argv: list[str], **kwargs: object) -> SimpleNamespace:
        assert argv[1:4] == ["pcb", "drc", "--format"]
        assert argv[4] == "json"
        assert argv[5] == "--output"
        assert kwargs["timeout"] == 40
        assert kwargs["check"] is False
        assert kwargs["cwd"] == Path(argv[6]).parent
        assert original is not None
        assert Path(argv[7]).read_bytes() == original
        assert Path(argv[7]) != selected.directory / "TEST.kicad_pcb"
        Path(argv[6]).write_text(
            json.dumps({"violations": [{}, {}], "unconnected_items": [{}]}),
            encoding="utf-8",
        )
        invoked.append("native")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        "kicad_mcp.cloud_native_drc.shutil.which", lambda name: "/usr/bin/kicad-cli"
    )
    monkeypatch.setattr("kicad_mcp.cloud_native_drc.subprocess.run", native)
    return invoked


def test_drc_returns_counts_only_on_private_copies(
    monkeypatch: pytest.MonkeyPatch, selected: OperatorProject
) -> None:
    calls = _fake_success(monkeypatch, selected)
    assert summarize_native_pcb_drc(selected) == {"violations": 2, "unconnectedItems": 1}
    assert calls == ["native"]
    assert (selected.directory / "TEST.kicad_pcb").read_text() == "PRIVATE BOARD"


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "missing"])
def test_never_execute_on_unsafe_board(
    monkeypatch: pytest.MonkeyPatch, selected: OperatorProject, unsafe: str, tmp_path: Path
) -> None:
    board = selected.directory / "TEST.kicad_pcb"
    board.unlink()
    if unsafe == "symlink":
        board.symlink_to(tmp_path / "unrelated")
    elif unsafe == "hardlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"SECRET")
        os.link(outside, board)
    calls = _fake_success(monkeypatch, selected)
    with pytest.raises(LocalReadDeniedError):
        summarize_native_pcb_drc(selected)
    assert calls == []


def test_project_symlink_denied(
    monkeypatch: pytest.MonkeyPatch, selected: OperatorProject, tmp_path: Path
) -> None:
    (selected.directory / "TEST.kicad_pro").unlink()
    (selected.directory / "TEST.kicad_pro").symlink_to(tmp_path / "private")
    calls = _fake_success(monkeypatch, selected)
    with pytest.raises(LocalReadDeniedError):
        summarize_native_pcb_drc(selected)
    assert calls == []


def test_missing_cli_denied(monkeypatch: pytest.MonkeyPatch, selected: OperatorProject) -> None:
    monkeypatch.setattr("kicad_mcp.cloud_native_drc.shutil.which", lambda _: None)
    with pytest.raises(LocalReadDeniedError):
        summarize_native_pcb_drc(selected)


@pytest.mark.parametrize("mode", ["timeout", "failure", "bad_json", "report_missing"])
def test_fail_closed_on_native_or_output_failure(
    monkeypatch: pytest.MonkeyPatch, selected: OperatorProject, mode: str
) -> None:
    _fake_success(monkeypatch, selected)

    def fail(argv: list[str], **kwargs: object) -> SimpleNamespace:
        if mode == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if mode == "bad_json":
            Path(argv[6]).write_text('{"violations":[]}', encoding="utf-8")
        if mode == "failure":
            return SimpleNamespace(returncode=9)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("kicad_mcp.cloud_native_drc.subprocess.run", fail)
    with pytest.raises(LocalReadDeniedError):
        summarize_native_pcb_drc(selected)
