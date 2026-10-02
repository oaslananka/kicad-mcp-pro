from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata

IMPORT_TOOL_NAMES = [
    "mfg_check_import_support",
    "pcb_import_board",
    "mfg_import_allegro",
    "mfg_import_pads",
    "mfg_import_geda",
    "mfg_import_specctra",
]


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.manufacturing_imports")
    assert spec is not None, "Manufacturing import adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.manufacturing_imports")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def _call(self, name: str, *args: object, **kwargs: object) -> str:
        self.calls.append((name, args, kwargs))
        return f"result::{name}"

    def check_import_support(self, format: str) -> str:
        return self._call("check", format)

    def import_board(self, **kwargs: object) -> str:
        return self._call("board", **kwargs)

    def import_allegro(self, path: str, output_dir: str = "") -> str:
        return self._call("allegro", path, output_dir)

    def import_pads(self, path: str, output_dir: str = "") -> str:
        return self._call("pads", path, output_dir)

    def import_geda(self, path: str, output_dir: str = "") -> str:
        return self._call("geda", path, output_dir)

    def import_specctra(self, path: str, output_dir: str = "") -> str:
        return self._call("specctra", path, output_dir)


def test_registration_preserves_import_tool_order_and_headless_metadata() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-import-registration")
    service = FakeService()

    adapter.register(server, adapter.ManufacturingImportDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == IMPORT_TOOL_NAMES
    for name in IMPORT_TOOL_NAMES:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_registration_delegates_board_and_legacy_import_arguments() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-import-delegation")
    service = FakeService()
    adapter.register(server, adapter.ManufacturingImportDependencies(service=service))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    board = tools["pcb_import_board"].fn(
        input_file="legacy.brd",
        output_file="board.kicad_pcb",
        format="pads",
        report_format="json",
        report_file="report.json",
    )
    pads = tools["mfg_import_pads"].fn(pads_pcb_path="legacy.brd", output_dir="imports")

    assert board == "result::board"
    assert pads == "result::pads"
    assert service.calls == [
        (
            "board",
            (),
            {
                "input_file": "legacy.brd",
                "output_file": "board.kicad_pcb",
                "format": "pads",
                "report_format": "json",
                "report_file": "report.json",
            },
        ),
        ("pads", ("legacy.brd", "imports"), {}),
    ]
