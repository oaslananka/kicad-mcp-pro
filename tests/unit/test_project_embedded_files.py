"""Unit tests for embedded file tools (FAZ 9).
Tools: project_list_embedded_files, project_extract_embedded_file,
project_remove_embedded_file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import create_server
from kicad_mcp.tools.embedded_files import (
    _load_project_payload,
    _project_dir,
    _project_file,
)
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


def test_project_file_and_dir_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    cfg.project_file = None
    cfg.project_dir = None
    monkeypatch.setattr("kicad_mcp.tools.embedded_files.get_config", lambda: cfg)

    with pytest.raises(ValueError, match="No project file is configured"):
        _project_file()

    with pytest.raises(ValueError, match="No active project directory is configured"):
        _project_dir()


def test_load_project_payload_non_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj_file = tmp_path / "list.kicad_pro"
    proj_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.tools.embedded_files._project_file", lambda: proj_file)

    with pytest.raises(ValueError, match="Project file must contain a JSON object"):
        _load_project_payload()


@pytest.mark.anyio
async def test_project_list_embedded_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    server = await _configured_project_server(workspace, project, monkeypatch)

    # Empty case
    res1 = await call_tool_text(server, "project_list_embedded_files", {})
    data1 = json.loads(res1)
    assert data1["count"] == 0
    assert data1["embedded_files"] == []

    # Dict case
    pro_path = project / "test.kicad_pro"
    pro_path.write_text(
        json.dumps({"embedded_files": {"entry1": {"name": "schema.pdf"}}}),
        encoding="utf-8",
    )
    res2 = await call_tool_text(server, "project_list_embedded_files", {})
    data2 = json.loads(res2)
    assert data2["count"] == 1
    assert data2["embedded_files"][0]["name"] == "schema.pdf"


@pytest.mark.anyio
async def test_project_embed_file_validation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    server = await _configured_project_server(workspace, project, monkeypatch)

    # File does not exist
    res1 = await call_tool_text(server, "project_embed_file", {"source_path": "missing.txt"})
    assert "does not exist" in res1

    # Not a file (directory)
    sub = project / "subdir"
    sub.mkdir()
    res2 = await call_tool_text(server, "project_embed_file", {"source_path": "subdir"})
    assert "is not a file" in res2

    # Empty target name
    file_path = project / "file.txt"
    file_path.write_text("content", encoding="utf-8")
    res3 = await call_tool_text(
        server,
        "project_embed_file",
        {"source_path": "file.txt", "target_name": "   "},
    )
    assert "target_name must not be empty" in res3


@pytest.mark.anyio
async def test_project_embed_overwrite_and_extract_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    server = await _configured_project_server(workspace, project, monkeypatch)

    src = project / "original.txt"
    src.write_text("v1 content", encoding="utf-8")

    # Embed first version
    res_embed = await call_tool_text(
        server,
        "project_embed_file",
        {"source_path": "original.txt", "target_name": "stored.txt", "description": "version 1"},
    )
    assert "File 'stored.txt' embedded into project" in res_embed

    # Overwrite with second version
    src.write_text("v2 content updated", encoding="utf-8")
    res_embed2 = await call_tool_text(
        server,
        "project_embed_file",
        {"source_path": "original.txt", "target_name": "stored.txt", "description": "version 2"},
    )
    assert "File 'stored.txt' embedded into project" in res_embed2

    # Extract to custom relative path
    out_relative = "extracted/out.txt"
    res_extract = await call_tool_text(
        server,
        "project_extract_embedded_file",
        {"name": "stored.txt", "output_path": out_relative},
    )
    assert "extracted to" in res_extract
    extracted_file = project / "extracted" / "out.txt"
    assert extracted_file.read_text(encoding="utf-8") == "v2 content updated"

    # Extract default path (project / name)
    res_extract_default = await call_tool_text(
        server,
        "project_extract_embedded_file",
        {"name": "stored.txt"},
    )
    assert "extracted to" in res_extract_default
    default_extracted = project / "stored.txt"
    assert default_extracted.read_text(encoding="utf-8") == "v2 content updated"


@pytest.mark.anyio
async def test_project_extract_missing_and_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    server = await _configured_project_server(workspace, project, monkeypatch)

    # Missing file
    res1 = await call_tool_text(server, "project_extract_embedded_file", {"name": "ghost.bin"})
    assert "not found" in res1

    # Corrupt base64
    pro_path = project / "test.kicad_pro"
    pro_path.write_text(
        json.dumps(
            {
                "embedded_files": [
                    {
                        "name": "corrupt.bin",
                        "content": "not-valid-base64-!!!",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    res2 = await call_tool_text(server, "project_extract_embedded_file", {"name": "corrupt.bin"})
    assert "Failed to decode embedded file" in res2


@pytest.mark.anyio
async def test_project_extract_unsafe_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    server = await _configured_project_server(workspace, project, monkeypatch)

    src = project / "safe.txt"
    src.write_text("safe content", encoding="utf-8")
    await call_tool_text(server, "project_embed_file", {"source_path": "safe.txt"})

    res = await call_tool_text(
        server,
        "project_extract_embedded_file",
        {"name": "safe.txt", "output_path": "../../escaped.txt"},
    )
    assert "escapes" in res.lower()


@pytest.mark.anyio
async def test_project_remove_embedded_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    server = await _configured_project_server(workspace, project, monkeypatch)

    # Missing file
    res1 = await call_tool_text(server, "project_remove_embedded_file", {"name": "not_there"})
    assert "not found" in res1

    # Add and remove
    src = project / "temp.txt"
    src.write_text("to be deleted", encoding="utf-8")
    await call_tool_text(server, "project_embed_file", {"source_path": "temp.txt"})

    res2 = await call_tool_text(server, "project_remove_embedded_file", {"name": "temp.txt"})
    assert "Removed embedded file 'temp.txt' from the project (1 entry deleted)." in res2
