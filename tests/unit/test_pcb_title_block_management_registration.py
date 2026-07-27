# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_title_block_management import PcbTitleBlockDependencies, register


class FakeTitleBlockService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def set_title_block_info(
        self,
        title: str | None = None,
        date: str | None = None,
        revision: str | None = None,
        company: str | None = None,
        comment1: str | None = None,
        comment2: str | None = None,
        comment3: str | None = None,
        comment4: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "title": title,
                "date": date,
                "revision": revision,
                "company": company,
                "comment1": comment1,
                "comment2": comment2,
                "comment3": comment3,
                "comment4": comment4,
            }
        )
        return "updated"


def _registered() -> tuple[FastMCP, FakeTitleBlockService]:
    server = FastMCP("pcb-title-block-test")
    service = FakeTitleBlockService()
    register(server, PcbTitleBlockDependencies(service=service))
    return server, service


def _nullable_string(title: str) -> dict[str, object]:
    return {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": None,
        "title": title,
    }


def test_registration_preserves_exact_name_and_schema() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"pcb_set_title_block_info"}
    assert tools["pcb_set_title_block_info"].parameters == {
        "properties": {
            "title": _nullable_string("Title"),
            "date": _nullable_string("Date"),
            "revision": _nullable_string("Revision"),
            "company": _nullable_string("Company"),
            "comment1": _nullable_string("Comment1"),
            "comment2": _nullable_string("Comment2"),
            "comment3": _nullable_string("Comment3"),
            "comment4": _nullable_string("Comment4"),
        },
        "title": "pcb_set_title_block_infoArguments",
        "type": "object",
    }


def test_registration_preserves_description_metadata_and_forwarding() -> None:
    server, service = _registered()
    tool = next(
        tool
        for tool in server._tool_manager.list_tools()
        if tool.name == "pcb_set_title_block_info"
    )

    assert tool.description.startswith("Set board title block information (KiCad 10.0.1+).")
    assert tool.fn(title="Controller", revision="C", comment4="Approved") == "updated"
    assert service.calls == [
        {
            "title": "Controller",
            "date": None,
            "revision": "C",
            "company": None,
            "comment1": None,
            "comment2": None,
            "comment3": None,
            "comment4": "Approved",
        }
    ]
    metadata = get_tool_metadata("pcb_set_title_block_info")
    assert metadata is not None
    assert metadata.requires_kicad_running is True
    assert metadata.headless_compatible is False
