"""Integration tests for KiCad file-format upgrade tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_sch_upgrade_dry_run_without_input_uses_sch_file(sample_project: Path) -> None:
    """sch_upgrade dry_run should use configured schematic file when input omitted."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "sch_upgrade", {"dry_run": True})
    assert "Dry run: Would upgrade schematic file" in result
    assert "force=False" in result


@pytest.mark.anyio
async def test_sch_upgrade_dry_run_with_force(sample_project: Path) -> None:
    """sch_upgrade dry_run should report force flag."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "sch_upgrade", {"dry_run": True, "force": True})
    assert "force=True" in result


@pytest.mark.anyio
async def test_sch_upgrade_fails_without_project_or_input() -> None:
    """sch_upgrade should fail when no project or input file is available."""
    server = build_server("full")

    result = await call_tool_text(server, "sch_upgrade", {})
    assert "No input file provided and no schematic configured" in result


@pytest.mark.anyio
async def test_sch_upgrade_runs_cli(sample_project: Path, monkeypatch) -> None:
    """sch_upgrade should invoke kicad-cli and report success."""
    invoked: list[list[str]] = []

    def fake_run_cli(*cmd: str) -> tuple[int, str, str]:
        invoked.append(list(cmd))
        return (0, "", "")

    monkeypatch.setattr("kicad_mcp.tools.upgrade._run_cli", fake_run_cli)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server, "sch_upgrade", {"input_file": "demo.kicad_sch", "force": True, "dry_run": False}
    )
    assert "Schematic upgraded and saved" in result
    assert "--force" in invoked[0]


@pytest.mark.anyio
async def test_sch_upgrade_reports_cli_failure(sample_project: Path, monkeypatch) -> None:
    """sch_upgrade should report CLI failure."""

    def fake_run_cli(*cmd: str) -> tuple[int, str, str]:
        return (1, "", "upgrade error")

    monkeypatch.setattr("kicad_mcp.tools.upgrade._run_cli", fake_run_cli)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server, "sch_upgrade", {"input_file": "demo.kicad_sch", "dry_run": False}
    )
    assert "Schematic upgrade failed" in result
    assert "upgrade error" in result


@pytest.mark.anyio
async def test_sch_upgrade_with_output_file(sample_project: Path) -> None:
    """sch_upgrade should use custom output path when provided."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "sch_upgrade",
        {
            "input_file": "demo.kicad_sch",
            "output_file": "upgraded.kicad_sch",
            "dry_run": True,
        },
    )
    assert "upgraded.kicad_sch" in result


@pytest.mark.anyio
async def test_pcb_upgrade_dry_run_without_input_uses_pcb_file(sample_project: Path) -> None:
    """pcb_upgrade dry_run should use configured PCB file when input omitted."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "pcb_upgrade", {"dry_run": True})
    assert "Dry run: Would upgrade PCB file" in result
    assert "force=False" in result


@pytest.mark.anyio
async def test_pcb_upgrade_dry_run_with_force(sample_project: Path) -> None:
    """pcb_upgrade dry_run should report force flag."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "pcb_upgrade", {"dry_run": True, "force": True})
    assert "force=True" in result


@pytest.mark.anyio
async def test_pcb_upgrade_fails_without_project_or_input() -> None:
    """pcb_upgrade should fail when no project or input file is available."""
    server = build_server("full")

    result = await call_tool_text(server, "pcb_upgrade", {})
    assert "No input file provided and no PCB configured" in result


@pytest.mark.anyio
async def test_pcb_upgrade_runs_cli(sample_project: Path, monkeypatch) -> None:
    """pcb_upgrade should invoke kicad-cli and report success."""

    def fake_run_cli(*cmd: str) -> tuple[int, str, str]:
        return (0, "", "")

    monkeypatch.setattr("kicad_mcp.tools.upgrade._run_cli", fake_run_cli)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server, "pcb_upgrade", {"input_file": "demo.kicad_pcb", "dry_run": False}
    )
    assert "PCB upgraded and saved" in result


@pytest.mark.anyio
async def test_pcb_upgrade_reports_cli_failure(sample_project: Path, monkeypatch) -> None:
    """pcb_upgrade should report CLI failure."""

    def fake_run_cli(*cmd: str) -> tuple[int, str, str]:
        return (1, "", "upgrade error")

    monkeypatch.setattr("kicad_mcp.tools.upgrade._run_cli", fake_run_cli)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server, "pcb_upgrade", {"input_file": "demo.kicad_pcb", "dry_run": False}
    )
    assert "PCB upgrade failed" in result
    assert "upgrade error" in result


@pytest.mark.anyio
async def test_pcb_upgrade_with_output_file(sample_project: Path) -> None:
    """pcb_upgrade should use custom output path when provided."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "pcb_upgrade",
        {
            "input_file": "demo.kicad_pcb",
            "output_file": "upgraded.kicad_pcb",
            "dry_run": True,
        },
    )
    assert "upgraded.kicad_pcb" in result


@pytest.mark.anyio
async def test_sch_upgrade_unsafe_input_path(sample_project: Path, monkeypatch) -> None:
    """sch_upgrade should reject unsafe input paths."""
    from kicad_mcp import path_safety

    original_resolve = path_safety.resolve_under

    def raising_resolve(*args: object, **kwargs: object) -> Path:
        raise ValueError("unsafe path")

    monkeypatch.setattr(path_safety, "resolve_under", raising_resolve)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "sch_upgrade", {"input_file": "../unsafe.kicad_sch"})
    assert "Unsafe input path" in result

    monkeypatch.setattr(path_safety, "resolve_under", original_resolve)


@pytest.mark.anyio
async def test_pcb_upgrade_unsafe_output_path(sample_project: Path, monkeypatch) -> None:
    """pcb_upgrade should reject unsafe output paths."""
    from kicad_mcp import path_safety

    original_resolve = path_safety.resolve_under

    call_count = 0

    def selective_resolve(*args: object, **kwargs: object) -> Path:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise ValueError("unsafe path")
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(path_safety, "resolve_under", selective_resolve)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "pcb_upgrade",
        {"input_file": "demo.kicad_pcb", "output_file": "../unsafe.kicad_pcb"},
    )
    assert "Unsafe output path" in result

    monkeypatch.setattr(path_safety, "resolve_under", original_resolve)
