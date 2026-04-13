from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_route_autoroute_freerouting_smoke_handles_large_dsn(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nets = "\n".join(f"  (net NET{i})" for i in range(60))
    (sample_project / "demo.dsn").write_text(f"(pcb\n{nets}\n)\n", encoding="utf-8")

    def fake_run(cmd, capture_output, text, timeout, check):
        _ = (capture_output, text, timeout, check)
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="KiCad 10.0.1", stderr="")
        if "--help" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="gerbers positions ipc2581 svg dxf step render spice",
                stderr="",
            )
        ses_path = Path(cmd[cmd.index("-do") + 1])
        if "docker" in cmd[0]:
            ses_path = sample_project / "output" / "routing" / ses_path.name
        ses_path.parent.mkdir(parents=True, exist_ok=True)
        ses_path.write_text("ses", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("kicad_mcp.utils.freerouting.subprocess.run", fake_run)

    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "route_autoroute_freerouting",
        {
            "dsn_path": "output/routing/board.dsn",
            "ses_path": "output/routing/board.ses",
            "net_classes_to_ignore": ["GND"],
            "max_passes": 60,
            "thread_count": 8,
            "use_docker": True,
        },
    )

    assert "FreeRouting completed successfully" in result
    assert (sample_project / "output" / "routing" / "board.ses").exists()
    assert "Thread count advisory: 8" in result
