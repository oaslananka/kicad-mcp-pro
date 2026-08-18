from __future__ import annotations

import json

import pytest

from kicad_mcp.server import create_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_kicad_get_version_partial_document_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # We want to test the case where get_open_documents throws an error
    # for DOCTYPE_PCB but succeeds for DOCTYPE_SCHEMATIC.
    # The output should say "unavailable" for PCB and report the count for Schematic.

    class MockKiCadPartial:
        def get_version(self) -> str:
            return "10.0.0-mock"

        def get_open_documents(self, doc_type: int) -> list[str]:
            from kipy.proto.common.types.base_types_pb2 import DocumentType

            if doc_type == DocumentType.DOCTYPE_PCB:
                raise RuntimeError("No handler for DOCTYPE_PCB")
            elif doc_type == DocumentType.DOCTYPE_SCHEMATIC:
                return ["sch1", "sch2"]
            return []

    # Mock get_kicad
    monkeypatch.setattr("kicad_mcp.tools.project.get_kicad", MockKiCadPartial)

    server = create_server()
    output = await call_tool_text(server, "kicad_get_version", {})

    assert "IPC version: 10.0.0-mock" in output
    assert "Open PCB documents: unavailable" in output
    assert "Open schematic documents: 2" in output


@pytest.mark.anyio
async def test_kicad_get_version_partial_document_availability_sch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same but error on schematic
    class MockKiCadPartialSch:
        def get_version(self) -> str:
            return "10.0.0-mock"

        def get_open_documents(self, doc_type: int) -> list[str]:
            from kipy.proto.common.types.base_types_pb2 import DocumentType

            if doc_type == DocumentType.DOCTYPE_SCHEMATIC:
                raise RuntimeError("No handler for DOCTYPE_SCHEMATIC")
            elif doc_type == DocumentType.DOCTYPE_PCB:
                return ["pcb1"]
            return []

    # Mock get_kicad
    monkeypatch.setattr("kicad_mcp.tools.project.get_kicad", MockKiCadPartialSch)

    server = create_server()
    output = await call_tool_text(server, "kicad_get_version", {})

    assert "IPC version: 10.0.0-mock" in output
    assert "Open PCB documents: 1" in output
    assert "Open schematic documents: unavailable" in output


@pytest.mark.anyio
async def test_create_new_project_uses_installed_kicad_template(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    share_root = tmp_path / "kicad-share"
    template_dir = share_root / "template"
    template_dir.mkdir(parents=True)
    template_payload = {
        "board": {"design_settings": {"rules": "template"}},
        "boards": ["template-board"],
        "libraries": {"pinned": True},
        "meta": {"filename": "kicad.kicad_pro", "version": 1},
        "net_settings": {"classes": ["Default"]},
        "pcbnew": {"last_paths": {}},
        "sheets": ["root"],
        "text_variables": {"COMPANY": "Example"},
    }
    (template_dir / "kicad.kicad_pro").write_text(json.dumps(template_payload), encoding="utf-8")

    import kicad_mcp.tools.project as project_tools

    monkeypatch.setattr(
        project_tools,
        "discover_library_paths",
        lambda _cli: {"root": share_root, "symbols": None, "footprints": None},
        raising=False,
    )

    server = create_server()
    output = await call_tool_text(
        server,
        "kicad_create_new_project",
        {"path": str(tmp_path), "name": "fresh"},
    )

    assert "Created project 'fresh'" in output
    payload = json.loads((tmp_path / "fresh" / "fresh.kicad_pro").read_text(encoding="utf-8"))
    assert payload["meta"]["filename"] == "fresh.kicad_pro"
    assert payload["libraries"] == {"pinned": True}
    assert payload["net_settings"] == {"classes": ["Default"]}
    assert sorted(payload) == sorted(template_payload)


@pytest.mark.anyio
async def test_create_new_project_migrates_generated_board_and_schematic(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kicad_mcp.tools.project as project_tools

    calls: list[tuple[str, str]] = []

    class Result:
        upgraded = True
        detail = ""

    def migrate(path, kind, _run_cli):
        calls.append((kind, path.name))
        return Result()

    monkeypatch.setattr(project_tools, "upgrade_generated_file", migrate, raising=False)

    server = create_server()
    output = await call_tool_text(
        server,
        "kicad_create_new_project",
        {"path": str(tmp_path), "name": "migrated"},
    )

    assert "Created project 'migrated'" in output
    assert calls == [
        ("pcb", "migrated.kicad_pcb"),
        ("sch", "migrated.kicad_sch"),
    ]
