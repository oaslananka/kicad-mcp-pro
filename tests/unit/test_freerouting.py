from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kicad_mcp.utils.freerouting import FreeRoutingRunner


def test_export_dsn_copies_existing_sibling_dsn(sample_project: Path) -> None:
    pcb_path = sample_project / "demo.kicad_pcb"
    source_dsn = sample_project / "demo.dsn"
    source_dsn.write_text("dsn", encoding="utf-8")

    runner = FreeRoutingRunner()
    staged = runner.export_dsn(pcb_path, Path("output/routing/board.dsn"))

    assert staged.exists()
    assert staged.read_text(encoding="utf-8") == "dsn"


def test_export_dsn_requires_manual_export_when_cli_lacks_specctra(sample_project: Path) -> None:
    runner = FreeRoutingRunner()

    with pytest.raises(RuntimeError) as exc_info:
        runner.export_dsn(sample_project / "demo.kicad_pcb", Path("output/routing/board.dsn"))

    assert "Export a .dsn file from KiCad's PCB Editor" in str(exc_info.value)


def test_run_freerouting_docker_builds_expected_command(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn_path = sample_project / "board.dsn"
    ses_path = sample_project / "board.ses"
    dsn_path.write_text("dsn", encoding="utf-8")
    observed: list[list[str]] = []

    def fake_run(cmd, capture_output, text, timeout, check):
        _ = (capture_output, text, timeout, check)
        observed.append(cmd)
        ses_path.write_text("ses", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("kicad_mcp.utils.freerouting.subprocess.run", fake_run)

    result = FreeRoutingRunner().run_freerouting(
        dsn_path,
        ses_path,
        max_passes=55,
        thread_count=6,
        use_docker=True,
        net_classes_to_ignore=["GND", "PWR"],
    )

    assert result.returncode == 0
    assert observed
    assert observed[0][:3] == ["docker", "run", "--rm"]
    assert "-de" in observed[0]
    assert "-do" in observed[0]
    assert "-inc" in observed[0]


def test_run_freerouting_jar_requires_jar_path(sample_project: Path) -> None:
    dsn_path = sample_project / "board.dsn"
    ses_path = sample_project / "board.ses"
    dsn_path.write_text("dsn", encoding="utf-8")

    with pytest.raises(RuntimeError) as exc_info:
        FreeRoutingRunner().run_freerouting(dsn_path, ses_path, use_docker=False)

    assert "FreeRouting JAR path is required" in str(exc_info.value)


def test_import_ses_stages_session(sample_project: Path, tmp_path: Path) -> None:
    ses_path = tmp_path / "board.ses"
    ses_path.write_text("ses", encoding="utf-8")

    staged = FreeRoutingRunner().import_ses(sample_project / "demo.kicad_pcb", ses_path)

    assert staged.exists()
    assert staged.read_text(encoding="utf-8") == "ses"
    assert staged.parent.name == "routing"
