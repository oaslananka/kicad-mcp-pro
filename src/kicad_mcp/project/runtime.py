"""Project runtime diagnostics behavior independent of FastMCP and KiCad bindings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ProjectRuntimeConfigProtocol(Protocol):
    @property
    def kicad_cli(self) -> Path: ...


def _document_count_text(value: int | None) -> str:
    return str(value) if value is not None else "unavailable"


@dataclass(frozen=True, slots=True)
class ProjectRuntimeProbeResult:
    """Sanitized KiCad IPC runtime details used by project diagnostics."""

    version: object | None = None
    pcb_documents: int | None = None
    schematic_documents: int | None = None
    unavailable: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectRuntimeService:
    """Render server, CLI, and IPC runtime details without depending on FastMCP."""

    server_version: str
    get_config: Callable[[], ProjectRuntimeConfigProtocol]
    find_kicad_version: Callable[[Path], str | None]
    probe_ipc: Callable[[], ProjectRuntimeProbeResult]

    def version_info(self) -> str:
        cfg = self.get_config()
        lines = [f"# KiCad MCP Pro Server v{self.server_version}", f"CLI path: {cfg.kicad_cli}"]

        cli_version = self.find_kicad_version(cfg.kicad_cli)
        lines.append(f"CLI version: {cli_version or 'unavailable'}")

        runtime = self.probe_ipc()
        if runtime.unavailable is not None:
            lines.append(f"IPC connection: {runtime.unavailable}")
        else:
            lines.append(f"IPC version: {runtime.version}")
            lines.append(f"Open PCB documents: {_document_count_text(runtime.pcb_documents)}")
            lines.append(
                f"Open schematic documents: {_document_count_text(runtime.schematic_documents)}"
            )

        lines.extend(["", "Use `kicad_set_project()` to configure an active project."])
        return "\n".join(lines)
