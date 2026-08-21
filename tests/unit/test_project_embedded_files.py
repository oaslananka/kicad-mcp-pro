"""Unit tests for embedded file tools (FAZ 9).
Tools: project_list_embedded_files, project_extract_embedded_file,
project_remove_embedded_file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kicad_mcp.server import create_server
from kicad_mcp.tools.embedded_files import _load_project_payload
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_load_project_payload_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj_file = tmp_path / "test.kicad_pro"
    proj_file.write_text(json.dumps({"embedded_files": []}), encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.tools.embedded_files._project_file", lambda: proj_file)
    payload = _load_project_payload()
    assert payload["embedded_files"] == []


@pytest.mark.anyio
async def test_load_project_payload_rejects_bad_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj_file = tmp_path / "bad.kicad_pro"
    proj_file.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.tools.embedded_files._project_file", lambda: proj_file)
    with pytest.raises(ValueError, match="valid JSON"):
        _load_project_payload()


@pytest.mark.anyio
async def test_embed_rejects_large_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file > 1 MB should be rejected."""
    large = tmp_path / "large.bin"
    large.write_bytes(b"x" * 1_000_001)
    (tmp_path / "test.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "test.kicad_pcb").write_text("", encoding="utf-8")
    (tmp_path / "test.kicad_sch").write_text("", encoding="utf-8")

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(tmp_path)})
    result = await call_tool_text(server, "project_embed_file", {"source_path": str(large)})
    assert "too large" in result.lower() or "1 mb" in result.lower()


async def _configured_project_server(
    workspace: Path,
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    project.mkdir(parents=True, exist_ok=True)
    (project / "test.kicad_pro").write_text("{}", encoding="utf-8")
    (project / "test.kicad_pcb").write_text("", encoding="utf-8")
    (project / "test.kicad_sch").write_text("", encoding="utf-8")
    monkeypatch.setenv("KICAD_MCP_WORKSPACE_ROOT", str(workspace))

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(project)})
    return server


@pytest.mark.anyio
async def test_embed_accepts_relative_source_inside_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    source = project / "docs" / "note.txt"
    source.parent.mkdir(parents=True)
    source.write_text("safe", encoding="utf-8")
    server = await _configured_project_server(workspace, project, monkeypatch)

    result = await call_tool_text(server, "project_embed_file", {"source_path": "docs/note.txt"})

    assert "embedded into project" in result


@pytest.mark.anyio
async def test_embed_accepts_absolute_source_inside_explicit_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    source = workspace / "shared" / "approved.txt"
    source.parent.mkdir(parents=True)
    source.write_text("safe", encoding="utf-8")
    server = await _configured_project_server(workspace, project, monkeypatch)

    result = await call_tool_text(server, "project_embed_file", {"source_path": str(source)})

    assert "embedded into project" in result


@pytest.mark.anyio
async def test_embed_rejects_absolute_source_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    server = await _configured_project_server(workspace, project, monkeypatch)

    result = await call_tool_text(server, "project_embed_file", {"source_path": str(outside)})

    assert "escapes workspace root" in result


@pytest.mark.anyio
async def test_embed_rejects_absolute_symlink_escape_from_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "linked.txt"
    workspace.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    server = await _configured_project_server(workspace, project, monkeypatch)

    result = await call_tool_text(server, "project_embed_file", {"source_path": str(link)})

    assert "escapes workspace root" in result


@pytest.mark.anyio
async def test_embed_rejects_parent_traversal_from_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    outside = workspace / "outside.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("secret", encoding="utf-8")
    server = await _configured_project_server(workspace, project, monkeypatch)

    result = await call_tool_text(server, "project_embed_file", {"source_path": "../outside.txt"})

    assert "escapes" in result.lower()


@pytest.mark.anyio
async def test_embed_rejects_foreign_windows_absolute_source_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("Foreign Windows path rejection is POSIX-specific.")
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    server = await _configured_project_server(workspace, project, monkeypatch)

    result = await call_tool_text(
        server,
        "project_embed_file",
        {"source_path": r"C:\\Users\\outside\\secret.txt"},
    )

    assert "Windows drive or UNC paths are not valid" in result
