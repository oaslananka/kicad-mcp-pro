from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

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
        def __init__(self, file_path: str) -> None:
            self.name = Path(file_path).name
            self._project_path = str(Path(file_path).with_suffix(".kicad_pro"))

        def get_project(self) -> object:
            return SimpleNamespace(path=self._project_path, name=Path(self._project_path).stem)

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
            self._file_path = file_path

        def get_version(self) -> str:
            return "11.0.0"

        def get_board(self) -> FakeBoard:
            return FakeBoard(self._file_path)

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
    cli.write_text("fake cli\n", encoding="utf-8")
    cli.chmod(0o755)
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    board.with_suffix(".kicad_pro").write_text('{"board": {}}\n', encoding="utf-8")
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


def test_canary_rejects_non_kicad_executable_before_runner(monkeypatch, tmp_path: Path) -> None:
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    fake_cli = tmp_path / "python"
    fake_cli.write_text("not kicad\n", encoding="utf-8")
    fake_cli.chmod(0o755)
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        _ = timeout
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="11.0.0\n", stderr="")

    monkeypatch.setattr(kicad11_headless_canary, "_run", fake_run)

    with pytest.raises(ValueError, match="KiCad CLI executable"):
        kicad11_headless_canary.run_canary(
            artifacts=tmp_path / "artifacts",
            kicad_cli=fake_cli,
            project_or_file=board,
            require_ready=True,
        )

    assert calls == []


def test_canary_rejects_non_kicad_input_before_runner(monkeypatch, tmp_path: Path) -> None:
    cli = tmp_path / "kicad-cli"
    cli.write_text("fake cli\n", encoding="utf-8")
    cli.chmod(0o755)
    payload = tmp_path / "notes.txt"
    payload.write_text("not a KiCad design\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        _ = timeout
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="11.0.0\n", stderr="")

    monkeypatch.setattr(kicad11_headless_canary, "_run", fake_run)

    with pytest.raises(ValueError, match="KiCad project or design file"):
        kicad11_headless_canary.run_canary(
            artifacts=tmp_path / "artifacts",
            kicad_cli=cli,
            project_or_file=payload,
            require_ready=True,
        )

    assert calls == []


def test_canary_appends_live_object_identity_to_preview_differential_report(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_fake_kipy(monkeypatch)
    _install_fake_runner(monkeypatch)
    monkeypatch.setattr(kicad11_headless_canary, "_source_sha", lambda: "a" * 40)
    cli = tmp_path / "kicad-cli"
    cli.write_text("fake cli\n", encoding="utf-8")
    cli.chmod(0o755)
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    board.with_suffix(".kicad_pro").write_text('{"board": {}}\n', encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    result = kicad11_headless_canary.run_canary(
        artifacts=artifacts,
        kicad_cli=cli,
        project_or_file=board,
        require_ready=True,
    )

    assert result == 0
    identity = json.loads(
        (artifacts / "differential" / "live-object-identity.json").read_text(encoding="utf-8")
    )
    summary = json.loads((artifacts / "differential" / "summary.json").read_text(encoding="utf-8"))
    assert identity["status"] == "match"
    assert identity["lane"] == "preview"
    assert identity["operation"] == "live-object.board-identity"
    assert summary["results_total"] == 1
    assert summary["match_count"] == 1
    assert summary["results"][0] == identity
    assert str(tmp_path) not in json.dumps(identity)


def test_canary_marks_live_identity_unavailable_when_headless_authority_is_absent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        _ = timeout
        if command[1:] == ["version"]:
            return subprocess.CompletedProcess(command, 0, stdout="10.99.0\n", stderr="")
        if command[1:] == ["api-server", "--help"]:
            return subprocess.CompletedProcess(command, 2, stdout="", stderr="unsupported")
        if command[1:4] == ["pcb", "export", "stats"]:
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("Board statistics\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="unsupported command")

    monkeypatch.setattr(kicad11_headless_canary, "_run", fake_run)
    monkeypatch.setattr(kicad11_headless_canary, "_source_sha", lambda: "a" * 40)
    cli = tmp_path / "kicad-cli"
    cli.write_text("fake cli\n", encoding="utf-8")
    cli.chmod(0o755)
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    board.with_suffix(".kicad_pro").write_text('{"board": {}}\n', encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    assert (
        kicad11_headless_canary.run_canary(
            artifacts=artifacts,
            kicad_cli=cli,
            project_or_file=board,
            require_ready=False,
        )
        == 0
    )

    identity = json.loads(
        (artifacts / "differential" / "live-object-identity.json").read_text(encoding="utf-8")
    )
    assert identity["status"] == "unavailable-authority"
    assert identity["lane"] == "preview"
    assert identity.get("native_result_hash") is None
    assert identity.get("custom_result_hash") is None
    assert "KiCad 11+ headless IPC is not ready" in identity["reason"]


def test_canary_appends_live_identity_to_existing_preview_differential_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from kicad_mcp.evals.semantic_differential import (
        aggregate_differential_results,
        classify_differential_result,
        render_differential_report_json,
    )

    _install_fake_kipy(monkeypatch)
    _install_fake_runner(monkeypatch)
    monkeypatch.setattr(kicad11_headless_canary, "_source_sha", lambda: "a" * 40)
    cli = tmp_path / "kicad-cli"
    cli.write_text("fake cli\n", encoding="utf-8")
    cli.chmod(0o755)
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    board.with_suffix(".kicad_pro").write_text('{"board": {}}\n', encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    differential = artifacts / "differential"
    differential.mkdir(parents=True)
    existing = classify_differential_result(
        source_sha="a" * 40,
        lane="preview",
        kicad_version="11.0.0",
        fixture_id="existing-preview",
        fixture_hash="sha256:" + "b" * 64,
        operation="drc.findings-and-severities",
        authority="kicad-cli:pcb-drc-json",
        comparison_method="fixture",
        native_result_hash="sha256:" + "c" * 64,
        custom_result_hash="sha256:" + "c" * 64,
    )
    (differential / "summary.json").write_text(
        render_differential_report_json(aggregate_differential_results([existing])),
        encoding="utf-8",
    )

    assert (
        kicad11_headless_canary.run_canary(
            artifacts=artifacts,
            kicad_cli=cli,
            project_or_file=board,
            require_ready=True,
        )
        == 0
    )

    summary = json.loads((differential / "summary.json").read_text(encoding="utf-8"))
    assert summary["results_total"] == 2
    assert summary["match_count"] == 2
    assert [record["operation"] for record in summary["results"]] == [
        "drc.findings-and-severities",
        "live-object.board-identity",
    ]
