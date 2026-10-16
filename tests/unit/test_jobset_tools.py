"""Unit tests for jobset tools (FAZ 2.1)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import create_server
from kicad_mcp.tools.jobset import _format_size
from tests.conftest import call_tool_text


def test_format_size() -> None:
    assert _format_size(500) == "500.0 B"
    assert _format_size(1024) == "1.0 KB"
    assert _format_size(1024 * 1024) == "1.0 MB"
    assert _format_size(1024 * 1024 * 1024) == "1.0 GB"
    assert _format_size(1024 * 1024 * 1024 * 1024) == "1.0 TB"


@pytest.mark.anyio
async def test_jobset_list_templates() -> None:
    server = create_server()
    result = await call_tool_text(server, "jobset_list_templates", {})
    assert result is not None


@pytest.mark.anyio
async def test_jobset_list_templates_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli_variants",
        lambda variants: (1, "", "kicad-cli error"),
    )
    server = create_server()
    result = await call_tool_text(server, "jobset_list_templates", {})
    assert "Failed to list jobset templates: kicad-cli error" in result


@pytest.mark.anyio
async def test_jobset_list_templates_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli_variants",
        lambda variants: (0, "Plain text templates", ""),
    )
    server = create_server()
    result = await call_tool_text(server, "jobset_list_templates", {})
    assert "Plain text templates" in result


@pytest.mark.anyio
async def test_jobset_list_templates_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli_variants",
        lambda variants: (0, "[]", ""),
    )
    server = create_server()
    result = await call_tool_text(server, "jobset_list_templates", {})
    assert "No jobset templates found." in result


@pytest.mark.anyio
async def test_jobset_list_templates_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = [
        {"name": "Standard Release", "description": "Gerbers, drill, and BOM"},
        {"title": "Fabrication Only"},
    ]
    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli_variants",
        lambda variants: (0, json.dumps(sample), ""),
    )
    server = create_server()
    result = await call_tool_text(server, "jobset_list_templates", {})
    assert "# Available Jobset Templates (2)" in result
    assert "Standard Release" in result
    assert "Fabrication Only" in result


@pytest.mark.anyio
async def test_jobset_list_templates_dict_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli_variants",
        lambda variants: (0, '{"custom": "output"}', ""),
    )
    server = create_server()
    result = await call_tool_text(server, "jobset_list_templates", {})
    assert '{"custom": "output"}' in result


@pytest.mark.anyio
async def test_jobset_export_missing_file() -> None:
    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_export",
        {"output_name": "nonexistent"},
    )
    assert "PCB" in result or "jobset" in result.lower()


@pytest.mark.anyio
async def test_jobset_export_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    cfg.pcb_file = tmp_path / "board.kicad_pcb"
    cfg.pcb_file.touch()
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)
    monkeypatch.setattr("kicad_mcp.tools.jobset._ensure_output_dir", lambda name: tmp_path / "out")
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    (out_dir / "board.zip").write_bytes(b"x" * 2048)

    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli_variants",
        lambda variants: (0, "", ""),
    )
    server = create_server()
    result = await call_tool_text(server, "jobset_export", {"output_name": "custom"})
    assert "Jobset export completed" in result
    assert "board.zip" in result


@pytest.mark.anyio
async def test_jobset_export_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    cfg.pcb_file = tmp_path / "board.kicad_pcb"
    cfg.pcb_file.touch()
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)
    monkeypatch.setattr("kicad_mcp.tools.jobset._ensure_output_dir", lambda name: tmp_path / "out")
    (tmp_path / "out").mkdir(parents=True)

    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli_variants",
        lambda variants: (1, "", "Failed command"),
    )
    server = create_server()
    result = await call_tool_text(server, "jobset_export", {})
    assert "Jobset export failed: Failed command" in result


@pytest.mark.anyio
async def test_jobset_run_missing_jobset_file() -> None:
    server = create_server()
    result = await call_tool_text(server, "jobset_run", {"jobset_file": ""})
    assert "jobset_file parameter is required" in result


@pytest.mark.anyio
async def test_jobset_run_missing_project() -> None:
    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_run",
        {"jobset_file": "my.kicad_jobset", "project_file": "missing.kicad_pro"},
    )
    assert "No KiCad project file configured or found" in result


@pytest.mark.anyio
async def test_jobset_run_file_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = tmp_path / "proj.kicad_pro"
    proj.touch()
    cfg = MagicMock()
    cfg.project_dir = tmp_path
    cfg.project_file = proj
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_run",
        {"jobset_file": "nonexistent.kicad_jobset"},
    )
    assert "Jobset file not found: nonexistent.kicad_jobset" in result


@pytest.mark.anyio
async def test_jobset_run_unsafe_jobset_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "proj.kicad_pro"
    proj.touch()
    cfg = MagicMock()
    cfg.project_dir = tmp_path
    cfg.project_file = proj
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_run",
        {"jobset_file": "../../etc/passwd"},
    )
    assert "Unsafe jobset path" in result


@pytest.mark.anyio
async def test_jobset_run_unsafe_output_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "proj.kicad_pro"
    proj.touch()
    jobset = tmp_path / "test.kicad_jobset"
    jobset.touch()

    cfg = MagicMock()
    cfg.project_dir = tmp_path
    cfg.project_file = proj
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_run",
        {"jobset_file": "test.kicad_jobset", "output": "../../outside"},
    )
    assert "Unsafe output path" in result


@pytest.mark.anyio
async def test_jobset_run_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = tmp_path / "proj.kicad_pro"
    proj.touch()
    jobset = tmp_path / "test.kicad_jobset"
    jobset.touch()

    cfg = MagicMock()
    cfg.project_dir = tmp_path
    cfg.project_file = proj
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)
    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli",
        lambda *cmd: (0, "Batch output generated", ""),
    )

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_run",
        {"jobset_file": "test.kicad_jobset", "output": "dist", "stop_on_error": True},
    )
    assert "Jobset executed successfully:" in result
    assert "Batch output generated" in result


@pytest.mark.anyio
async def test_jobset_run_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = tmp_path / "proj.kicad_pro"
    proj.touch()
    jobset = tmp_path / "test.kicad_jobset"
    jobset.touch()

    cfg = MagicMock()
    cfg.project_dir = tmp_path
    cfg.project_file = proj
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)
    monkeypatch.setattr(
        "kicad_mcp.tools.jobset._run_cli",
        lambda *cmd: (1, "", "Execution error in job 2"),
    )

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_run",
        {"jobset_file": "test.kicad_jobset"},
    )
    assert "Jobset run failed: Execution error in job 2" in result


@pytest.mark.anyio
async def test_jobset_validate_missing_parameter() -> None:
    server = create_server()
    result = await call_tool_text(server, "jobset_validate", {"jobset_file": ""})
    assert "Error: jobset_file parameter is required" in result


@pytest.mark.anyio
async def test_jobset_validate_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    cfg.project_dir = tmp_path
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_validate",
        {"jobset_file": "nonexistent.kicad_jobset"},
    )
    assert "Jobset file not found: nonexistent.kicad_jobset" in result


@pytest.mark.anyio
async def test_jobset_validate_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobset = tmp_path / "bad.kicad_jobset"
    jobset.write_text("invalid json {", encoding="utf-8")

    cfg = MagicMock()
    cfg.project_dir = tmp_path
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_validate",
        {"jobset_file": "bad.kicad_jobset"},
    )
    assert "Validation failed: Invalid JSON format:" in result


@pytest.mark.anyio
async def test_jobset_validate_missing_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobset = tmp_path / "no_jobs.kicad_jobset"
    jobset.write_text('{"name": "test"}', encoding="utf-8")

    cfg = MagicMock()
    cfg.project_dir = tmp_path
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_validate",
        {"jobset_file": "no_jobs.kicad_jobset"},
    )
    assert "Validation failed: Missing required 'jobs' array key." in result


@pytest.mark.anyio
async def test_jobset_validate_non_list_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobset = tmp_path / "string_jobs.kicad_jobset"
    jobset.write_text('{"jobs": "not a list"}', encoding="utf-8")

    cfg = MagicMock()
    cfg.project_dir = tmp_path
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_validate",
        {"jobset_file": "string_jobs.kicad_jobset"},
    )
    assert "Validation failed: 'jobs' must be a list." in result


@pytest.mark.anyio
async def test_jobset_validate_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobset = tmp_path / "valid.kicad_jobset"
    jobset.write_text('{"jobs": [{"type": "gerber"}, {"type": "drill"}]}', encoding="utf-8")

    cfg = MagicMock()
    cfg.project_dir = tmp_path
    monkeypatch.setattr("kicad_mcp.tools.jobset.get_config", lambda: cfg)

    server = create_server()
    result = await call_tool_text(
        server,
        "jobset_validate",
        {"jobset_file": "valid.kicad_jobset"},
    )
    assert "Jobset file is valid. Found 2 jobs defined." in result
