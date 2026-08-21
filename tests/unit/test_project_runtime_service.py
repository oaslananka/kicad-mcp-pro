from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kicad_mcp.project.runtime import ProjectRuntimeProbeResult, ProjectRuntimeService


def test_version_info_renders_cli_and_ipc_runtime_details() -> None:
    cli_path = Path("/opt/kicad/bin/kicad-cli")
    service = ProjectRuntimeService(
        server_version="3.32.0",
        get_config=lambda: SimpleNamespace(kicad_cli=cli_path),
        find_kicad_version=lambda path: "10.0.5" if path == cli_path else None,
        probe_ipc=lambda: ProjectRuntimeProbeResult(
            version="10.0.5",
            pcb_documents=2,
            schematic_documents=1,
        ),
    )

    assert service.version_info() == "\n".join(
        [
            "# KiCad MCP Pro Server v3.32.0",
            f"CLI path: {cli_path}",
            "CLI version: 10.0.5",
            "IPC version: 10.0.5",
            "Open PCB documents: 2",
            "Open schematic documents: 1",
            "",
            "Use `kicad_set_project()` to configure an active project.",
        ]
    )


def test_version_info_preserves_partial_document_availability() -> None:
    service = ProjectRuntimeService(
        server_version="3.32.0",
        get_config=lambda: SimpleNamespace(kicad_cli=Path("/missing/kicad-cli")),
        find_kicad_version=lambda _path: None,
        probe_ipc=lambda: ProjectRuntimeProbeResult(
            version="10.0.0-mock",
            pcb_documents=None,
            schematic_documents=2,
        ),
    )

    output = service.version_info()

    assert "CLI version: unavailable" in output
    assert "IPC version: 10.0.0-mock" in output
    assert "Open PCB documents: unavailable" in output
    assert "Open schematic documents: 2" in output


def test_version_info_preserves_connection_unavailable_detail() -> None:
    service = ProjectRuntimeService(
        server_version="3.32.0",
        get_config=lambda: SimpleNamespace(kicad_cli=Path("/missing/kicad-cli")),
        find_kicad_version=lambda _path: None,
        probe_ipc=lambda: ProjectRuntimeProbeResult(
            unavailable="unavailable (KiCad is not running)",
        ),
    )

    output = service.version_info()

    assert "IPC connection: unavailable (KiCad is not running)" in output
    assert "IPC version:" not in output
