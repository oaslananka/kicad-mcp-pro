"""Opt-in native KiCad PCB render regression for issue #1950."""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import struct
from pathlib import Path

import pytest
from mcp.types import CallToolResult, ImageContent

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.tools.export import LOW_LEVEL_EXPORT_NOTICE
from kicad_mcp.tools.export_support import _run_cli
from tests.conftest import tool_text

FIXTURE = Path(__file__).resolve().parents[2] / "packages/kicad-fixtures/fixtures/clean-led-kicad10"


@pytest.mark.anyio
async def test_native_render_boolean_combinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_cli = os.environ.get("KICAD_NATIVE_RENDER_CLI")
    if not configured_cli:
        pytest.skip("Explicit pinned native KiCad render executable required")
    cli = Path(configured_cli).resolve(strict=True)
    assert cli.is_file()
    project = tmp_path / "project"
    project.mkdir()
    sources = tuple(sorted(FIXTURE.glob("*.kicad_*")))
    assert sources
    original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    for source in sources:
        shutil.copy2(source, project / source.name)
    monkeypatch.setenv("KICAD_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("KICAD_DOCUMENTS_HOME", str(tmp_path / "documents"))
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", str(cli))
    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(project))
    monkeypatch.setenv("KICAD_MCP_WORKSPACE_ROOT", str(project))
    monkeypatch.setenv("KICAD_MCP_OUTPUT_DIR", str(project / "output"))
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "readonly")
    monkeypatch.setenv("KICAD_MCP_KICAD_SOCKET_PATH", str(tmp_path / "unbound.sock"))
    reset_config()
    version = _run_cli("version")
    assert version[0] == 0
    help_code, help_text, help_error = _run_cli("pcb", "render", "--help")
    assert help_code == 0
    assert "--floor" in help_text + help_error
    assert "--perspective" in help_text + help_error
    server = build_server("full")
    hashes = set()
    for floor, perspective in ((True, True), (True, False), (False, True), (False, False)):
        arguments = {
            "output_file": f"render-{int(floor)}-{int(perspective)}.png",
            "width": 320,
            "height": 240,
            "side": "top",
        }
        if not (floor and perspective):
            arguments.update(floor=floor, perspective=perspective)
        result = await server.call_tool("export_3d_render", arguments)
        assert isinstance(result, CallToolResult)
        assert not result.is_error, tool_text(result)
        assert tool_text(result).startswith(LOW_LEVEL_EXPORT_NOTICE)
        images = [block for block in result.content if isinstance(block, ImageContent)]
        assert len(images) == 1
        assert images[0].mime_type == "image/png"
        png = base64.b64decode(images[0].data, validate=True)
        assert png.startswith(bytes.fromhex("89504e470d0a1a0a"))
        # KiCad may align ray-traced dimensions to its native render tiles.
        # Compare against the pinned CLI rather than assuming exact requested pixels.
        native_output = project / f"native-{int(floor)}-{int(perspective)}.png"
        native_flags = (["--floor"] if floor else []) + (["--perspective"] if perspective else [])
        code, stdout, stderr = _run_cli(
            "pcb",
            "render",
            "--width",
            "320",
            "--height",
            "240",
            "--side",
            "top",
            "--zoom",
            "1.0",
            "--output",
            str(native_output),
            *native_flags,
            str(project / "clean-led-kicad10.kicad_pcb"),
        )
        assert code == 0, stderr or stdout
        native_png = native_output.read_bytes()
        assert native_png.startswith(bytes.fromhex("89504e470d0a1a0a"))
        dimensions = struct.unpack(">II", png[16:24])
        assert dimensions == struct.unpack(">II", native_png[16:24])
        assert all(dimensions)
        print(f"floor={floor} perspective={perspective}: native PNG {dimensions}")
        hashes.add(hashlib.sha256(png).hexdigest())
    assert len(hashes) == 4, "Native boolean options should affect the image"
    failed = await server.call_tool(
        "export_3d_render", {"output_file": "invalid.png", "side": "invalid-side"}
    )
    assert isinstance(failed, CallToolResult)
    assert failed.is_error
    diagnostic = tool_text(failed)
    assert "CLI_COMMAND_FAILED" in diagnostic
    assert "exit code" in diagnostic
    assert "unknown error" not in diagnostic.casefold()
    assert str(project) not in diagnostic
    assert str(cli) not in diagnostic
    assert not any(isinstance(block, ImageContent) for block in failed.content)
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources} == original
    copied = {name: hashlib.sha256((project / name).read_bytes()).hexdigest() for name in original}
    sidecars = sorted(p.name for p in project.glob("*.kicad_*") if p.name not in original)
    print(
        f"Native version: {version[1].strip()}; changed copied CAD files: "
        f"{[name for name in original if original[name] != copied[name]]}; "
        f"new sidecars: {sidecars}"
    )
    assert copied == original
