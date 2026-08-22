from __future__ import annotations

from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.ipc.runtime_probe import probe_project_runtime


def test_probe_reports_version_and_open_document_counts() -> None:
    pcb_type = object()
    schematic_type = object()

    class FakeKiCad:
        def get_version(self) -> str:
            return "10.0.5"

        def get_open_documents(self, doc_type: object) -> list[str]:
            if doc_type is pcb_type:
                return ["a.kicad_pcb", "b.kicad_pcb"]
            if doc_type is schematic_type:
                return ["a.kicad_sch"]
            raise AssertionError("unexpected document type")

    result = probe_project_runtime(
        client_factory=FakeKiCad,
        document_types=lambda: (pcb_type, schematic_type),
    )

    assert result.version == "10.0.5"
    assert result.pcb_documents == 2
    assert result.schematic_documents == 1
    assert result.unavailable is None


def test_probe_preserves_partial_document_availability() -> None:
    pcb_type = object()
    schematic_type = object()

    class FakeKiCad:
        def get_version(self) -> str:
            return "10.0.0-mock"

        def get_open_documents(self, doc_type: object) -> list[str]:
            if doc_type is pcb_type:
                raise RuntimeError("PCB documents unavailable")
            if doc_type is schematic_type:
                return ["one", "two"]
            raise AssertionError("unexpected document type")

    result = probe_project_runtime(
        client_factory=FakeKiCad,
        document_types=lambda: (pcb_type, schematic_type),
    )

    assert result.version == "10.0.0-mock"
    assert result.pcb_documents is None
    assert result.schematic_documents == 2
    assert result.unavailable is None


def test_probe_preserves_connection_error_detail() -> None:
    def fail_connection() -> object:
        raise KiCadConnectionError("KiCad is not running")

    result = probe_project_runtime(
        client_factory=fail_connection,
        document_types=lambda: (object(), object()),
    )

    assert result.unavailable == "unavailable (KiCad is not running)"
    assert result.version is None


def test_probe_hides_unexpected_probe_error() -> None:
    def fail_types() -> tuple[object, object]:
        raise RuntimeError("sensitive provider detail")

    result = probe_project_runtime(
        client_factory=lambda: object(),
        document_types=fail_types,
    )

    assert result.unavailable == "unavailable"
