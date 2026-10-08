"""Regression checks for native fixture audit input and executable contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import audit_native_board_fixtures as audit


def test_source_inventory_keeps_board_and_schematic_suffixes(tmp_path: Path) -> None:
    (tmp_path / "fixture.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
    (tmp_path / "root.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")

    assert [path.name for path in audit._source_files(tmp_path)] == [
        "fixture.kicad_pcb",
        "root.kicad_sch",
    ]


def test_source_inventory_rejects_schematic_only_fixture(tmp_path: Path) -> None:
    (tmp_path / "root.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")

    with pytest.raises(ValueError, match="fixture must contain a KiCad PCB"):
        audit._source_files(tmp_path)


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected_status"),
    [(0, "", "clean"), (2, "Found 3 violations", "violations")],
)
def test_native_run_preserves_pinned_executable_and_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    returncode: int,
    stdout: str,
    expected_status: str,
) -> None:
    monkeypatch.setattr(audit, "_trusted_system_executable", lambda *_: audit.PINNED_KICAD_CLI)
    observed: list[str] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.extend(argv)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["timeout"] == 10.0
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(argv, returncode, stdout, "")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)

    code, status, elapsed_ms = audit._run_native(
        audit.PINNED_KICAD_CLI, ["pcb", "drc"], cwd=tmp_path, timeout=10.0
    )

    assert observed == ["/usr/bin/kicad-cli", "pcb", "drc"]
    assert code == returncode
    assert status == expected_status
    assert elapsed_ms >= 0


def test_native_run_rejects_other_trusted_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(audit, "_trusted_system_executable", lambda *_: "/usr/local/bin/kicad-cli")
    with pytest.raises(ValueError, match="pinned system KiCad CLI"):
        audit._run_native("kicad-cli", ["pcb", "drc"], cwd=tmp_path, timeout=10)
