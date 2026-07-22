from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from scripts import kicad11_headless_canary


def _install_fake_runner(monkeypatch) -> None:
    def fake_run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        _ = timeout
        if command[1:] == ["version"]:
            return subprocess.CompletedProcess(command, 0, stdout="11.0.0\n", stderr="")
        if command[1:] == ["api-server", "--help"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Run the KiCad IPC API server in headless mode\n",
                stderr="",
            )
        if command[1:4] == ["pcb", "export", "stats"]:
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("Board statistics\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="unsupported command")

    monkeypatch.setattr(kicad11_headless_canary, "_run", fake_run)


def _install_fake_kipy(monkeypatch) -> None:
    class FakeBoard:
        def begin_commit(self) -> None:
            return None

        def drop_commit(self) -> None:
            return None

    class FakeKiCad:
        def __init__(
            self,
            *,
            headless: bool,
            timeout_ms: int,
            kicad_cli_path: str,
            file_path: str,
        ) -> None:
            assert headless is True
            assert timeout_ms > 0
            assert kicad_cli_path
            assert file_path

        def get_version(self) -> str:
            return "11.0.0"

        def get_board(self) -> FakeBoard:
            return FakeBoard()

        def close(self) -> None:
            return None

    module = ModuleType("kipy")
    module.KiCad = FakeKiCad  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kipy", module)


def test_canary_reports_read_write_and_export_separately(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_fake_kipy(monkeypatch)
    _install_fake_runner(monkeypatch)
    cli = tmp_path / "kicad-cli"
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    result = kicad11_headless_canary.run_canary(
        artifacts=artifacts,
        kicad_cli=cli,
        project_or_file=board,
        require_ready=True,
    )

    assert result == 0
    for surface in ("read", "write", "export"):
        payload = json.loads((artifacts / surface / "summary.json").read_text(encoding="utf-8"))
        assert payload["surface"] == surface
        assert payload["status"] == "passed"
        assert payload["kicadVersion"] == "11.0.0"


def test_canary_writes_blocked_reports_when_nightly_is_unavailable(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"

    result = kicad11_headless_canary.run_canary(
        artifacts=artifacts,
        kicad_cli=None,
        project_or_file=None,
        require_ready=False,
        unavailable_reason="nightly package unavailable",
    )

    assert result == 0
    for surface in ("read", "write", "export"):
        payload = json.loads((artifacts / surface / "summary.json").read_text(encoding="utf-8"))
        assert payload["status"] == "blocked"
        assert "nightly package unavailable" in payload["reason"]
