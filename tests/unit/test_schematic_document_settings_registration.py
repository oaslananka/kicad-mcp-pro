# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_document_settings import (
    SchematicDocumentSettingsDependencies,
    register,
)


class FakeDocumentSettingsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def set_title_block_info(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
        title: str | None = None,
        rev: str | None = None,
        date: str | None = None,
        company: str | None = None,
        comment1: str | None = None,
        comment2: str | None = None,
        comment3: str | None = None,
        comment4: str | None = None,
        dry_run: bool = False,
    ) -> str:
        self.calls.append(
            (
                "set_title_block_info",
                (
                    sheet,
                    sheet_file,
                    title,
                    rev,
                    date,
                    company,
                    comment1,
                    comment2,
                    comment3,
                    comment4,
                    dry_run,
                ),
            )
        )
        return "title"

    def set_sheet_size(self, paper: str = "A3") -> str:
        self.calls.append(("set_sheet_size", (paper,)))
        return "size"

    def auto_resize_sheet(self) -> str:
        self.calls.append(("auto_resize_sheet", ()))
        return "auto"


def _registered() -> tuple[FastMCP, FakeDocumentSettingsService]:
    server = FastMCP("schematic-document-settings-test")
    service = FakeDocumentSettingsService()
    register(server, SchematicDocumentSettingsDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_schema_defaults() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_set_title_block_info",
        "sch_set_sheet_size",
        "sch_auto_resize_sheet",
    }
    assert tools["sch_set_title_block_info"].description == (
        "Set schematic title block fields on the root sheet or a child sheet.\n\n"
        "Unspecified fields are preserved. Use ``sheet`` for a named child sheet\n"
        "or ``sheet_file`` for a specific ``.kicad_sch`` file; omit both to target\n"
        "the active root schematic.\n"
    )
    assert tools["sch_set_sheet_size"].description == (
        "Change the schematic sheet (paper) size.\n\n"
        "Use this when the current sheet is too small to fit all symbols — for\n"
        "example after ``sch_auto_place_functional`` warns that symbols were\n"
        "placed outside the sheet boundary, or when you receive a screenshot\n"
        "showing components outside the red sheet border.\n\n"
        "Supported sizes (landscape): A4, A3, A2, A1, A0, A (letter), B, C, D, E,\n"
        "USLetter, USLegal.\n\n"
        "After resizing you should call ``sch_auto_place_functional`` again so\n"
        "that symbols are re-distributed across the larger sheet.\n\n"
        "Args:\n"
        '    paper: Target paper size keyword (default "A3").\n\n'
        "Returns:\n"
        "    Confirmation with old and new dimensions.\n"
    )
    assert tools["sch_auto_resize_sheet"].description == (
        "Automatically grow the sheet to fit all currently placed symbols.\n\n"
        "Reads the bounding box of all placed symbols and selects the smallest\n"
        "standard paper size (A4 → A3 → A2 → A1) that contains them with the\n"
        "configured margin.  If the current sheet already fits, reports that no\n"
        "change is needed.\n\n"
        "Returns:\n"
        "    The chosen paper size and new dimensions, or a message if the\n"
        "    current size is already sufficient.\n"
    )

    title_schema = tools["sch_set_title_block_info"].parameters
    assert title_schema.get("required") is None
    assert list(title_schema["properties"]) == [
        "sheet",
        "sheet_file",
        "title",
        "rev",
        "date",
        "company",
        "comment1",
        "comment2",
        "comment3",
        "comment4",
        "dry_run",
    ]
    for field in [
        "sheet",
        "sheet_file",
        "title",
        "rev",
        "date",
        "company",
        "comment1",
        "comment2",
        "comment3",
        "comment4",
    ]:
        assert title_schema["properties"][field]["default"] is None
    assert title_schema["properties"]["dry_run"]["default"] is False

    size_schema = tools["sch_set_sheet_size"].parameters
    assert size_schema.get("required") is None
    assert size_schema["properties"]["paper"]["default"] == "A3"
    assert tools["sch_auto_resize_sheet"].parameters == {
        "properties": {},
        "title": "sch_auto_resize_sheetArguments",
        "type": "object",
    }


def test_registration_preserves_headless_metadata_and_direct_annotations() -> None:
    server, _service = _registered()

    for tool in server._tool_manager.list_tools():
        metadata = get_tool_metadata(tool.name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False
        assert tool.annotations is None


def test_registration_delegates_defaults_and_explicit_arguments() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_set_title_block_info"].fn() == "title"
    assert tools["sch_set_sheet_size"].fn() == "size"
    assert tools["sch_auto_resize_sheet"].fn() == "auto"
    assert (
        tools["sch_set_title_block_info"].fn(
            sheet="power",
            sheet_file=None,
            title="Power",
            rev="B",
            date="2026-07-23",
            company="Acme",
            comment1="One",
            comment2="Two",
            comment3="Three",
            comment4="Four",
            dry_run=True,
        )
        == "title"
    )
    assert tools["sch_set_sheet_size"].fn(paper="A2") == "size"

    assert service.calls == [
        (
            "set_title_block_info",
            (None, None, None, None, None, None, None, None, None, None, False),
        ),
        ("set_sheet_size", ("A3",)),
        ("auto_resize_sheet", ()),
        (
            "set_title_block_info",
            (
                "power",
                None,
                "Power",
                "B",
                "2026-07-23",
                "Acme",
                "One",
                "Two",
                "Three",
                "Four",
                True,
            ),
        ),
        ("set_sheet_size", ("A2",)),
    ]
