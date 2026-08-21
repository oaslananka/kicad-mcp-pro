"""KiCad IPC runtime probe for project diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Sized
from typing import Protocol, cast

import structlog

from ..connection import KiCadConnectionError, get_kicad
from ..project.runtime import ProjectRuntimeProbeResult

logger = structlog.get_logger(__name__)


class ProjectRuntimeClientProtocol(Protocol):
    def get_version(self) -> object: ...

    def get_open_documents(self, document_type: object) -> Sized: ...


def _document_types() -> tuple[object, object]:
    from kipy.proto.common.types.base_types_pb2 import DocumentType

    return DocumentType.DOCTYPE_PCB, DocumentType.DOCTYPE_SCHEMATIC


def _open_document_count(client: ProjectRuntimeClientProtocol, document_type: object) -> int | None:
    try:
        return len(client.get_open_documents(document_type))
    except Exception:
        return None


def probe_project_runtime(
    *,
    client_factory: Callable[[], object] = get_kicad,
    document_types: Callable[[], tuple[object, object]] = _document_types,
) -> ProjectRuntimeProbeResult:
    """Probe KiCad IPC while preserving partial document availability semantics."""
    try:
        pcb_type, schematic_type = document_types()
        client = cast(ProjectRuntimeClientProtocol, client_factory())
        return ProjectRuntimeProbeResult(
            version=client.get_version(),
            pcb_documents=_open_document_count(client, pcb_type),
            schematic_documents=_open_document_count(client, schematic_type),
        )
    except KiCadConnectionError as exc:
        return ProjectRuntimeProbeResult(unavailable=f"unavailable ({exc})")
    except Exception as exc:
        logger.debug("kicad_version_ipc_probe_failed", error=str(exc))
        return ProjectRuntimeProbeResult(unavailable="unavailable")
