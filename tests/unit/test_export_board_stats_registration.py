from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.export_board_stats import ExportBoardStatsDependencies, register
from kicad_mcp.tools.metadata import get_tool_metadata


class FakeBoardStatsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_board_stats(self) -> str:
        self.calls.append(("get_board_stats", None))
        return "preview"

    def export_board_stats(self, output_name: str | None = None) -> str:
        self.calls.append(("export_board_stats", output_name))
        return "json"


def _registered() -> tuple[FastMCP, FakeBoardStatsService]:
    server = FastMCP("export-board-stats-test")
    service = FakeBoardStatsService()
    register(server, ExportBoardStatsDependencies(service=service))
    return server, service


def test_registration_preserves_exact_names_schemas_and_descriptions() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"get_board_stats", "pcb_export_stats"}
    assert tools["get_board_stats"].description == (
        "Export board statistics and return a readable preview."
    )
    assert tools["get_board_stats"].parameters == {
        "properties": {},
        "title": "get_board_statsArguments",
        "type": "object",
    }
    assert tools["pcb_export_stats"].description.startswith(
        "Export board statistics (net count, component count, layer count, etc.)"
    )
    assert tools["pcb_export_stats"].parameters == {
        "properties": {
            "output_name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Output Name",
            }
        },
        "title": "pcb_export_statsArguments",
        "type": "object",
    }


def test_registration_preserves_metadata_and_delegates() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["get_board_stats"].fn() == "preview"
    assert tools["pcb_export_stats"].fn("custom.json") == "json"
    assert service.calls == [
        ("get_board_stats", None),
        ("export_board_stats", "custom.json"),
    ]
    for name in ("get_board_stats", "pcb_export_stats"):
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_export_composition_root_preserves_board_stats_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]

    assert names[-3:] == [
        "get_board_stats",
        "export_manufacturing_package",
        "pcb_export_stats",
    ]
