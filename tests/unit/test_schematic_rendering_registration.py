# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from kicad_mcp.schematic.rendering import SchematicRenderingResponse
from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_rendering import (
    SchematicRenderingDependencies,
    register,
)


class FakeRenderingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: dict[str, SchematicRenderingResponse] = {
            "live_preview": SchematicRenderingResponse(text="live"),
            "render_png": SchematicRenderingResponse(text="png"),
            "render_visual_diff": SchematicRenderingResponse(text="diff"),
        }

    def live_preview(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
        include_child_sheets: bool = True,
        debounce_ms: int = 750,
        render: bool = True,
        reload: bool = False,
        force: bool = False,
        crop_to_content: bool = True,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> SchematicRenderingResponse:
        self.calls.append(
            (
                "live_preview",
                {
                    "sheet": sheet,
                    "sheet_file": sheet_file,
                    "include_child_sheets": include_child_sheets,
                    "debounce_ms": debounce_ms,
                    "render": render,
                    "reload": reload,
                    "force": force,
                    "crop_to_content": crop_to_content,
                    "dpi": dpi,
                    "include_title_block": include_title_block,
                    "output_file": output_file,
                },
            )
        )
        return self.responses["live_preview"]

    def render_png(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
        crop_to_content: bool = True,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> SchematicRenderingResponse:
        self.calls.append(
            (
                "render_png",
                {
                    "sheet": sheet,
                    "sheet_file": sheet_file,
                    "crop_to_content": crop_to_content,
                    "dpi": dpi,
                    "include_title_block": include_title_block,
                    "output_file": output_file,
                },
            )
        )
        return self.responses["render_png"]

    def render_visual_diff(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
        dpi: int = 200,
        include_title_block: bool = True,
        output_file: str | None = None,
    ) -> SchematicRenderingResponse:
        self.calls.append(
            (
                "render_visual_diff",
                {
                    "sheet": sheet,
                    "sheet_file": sheet_file,
                    "dpi": dpi,
                    "include_title_block": include_title_block,
                    "output_file": output_file,
                },
            )
        )
        return self.responses["render_visual_diff"]


def _registered() -> tuple[FastMCP, FakeRenderingService]:
    server = FastMCP("schematic-rendering-test")
    service = FakeRenderingService()
    register(server, SchematicRenderingDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_live_preview",
        "sch_render_png",
        "sch_render_visual_diff",
    }
    assert tools["sch_live_preview"].description == (
        "Poll a safe live schematic preview state and refresh rendered output on changes.\n\n"
        "This is an opt-in polling watcher for agents and companion-plugin flows. It\n"
        "records the current schematic file signature, debounces rapid writes, then\n"
        "refreshes a PNG preview when the watched files are stable. KiCad GUI reload\n"
        "is deliberately opt-in via ``reload=True`` because the tool cannot reliably\n"
        "prove that the user has no unsaved GUI edits.\n"
    )
    assert tools["sch_render_png"].description == (
        "Render a schematic sheet to PNG for visual self-checks.\n\n"
        "Uses headless ``kicad-cli sch export svg`` followed by SVG-to-PNG\n"
        "conversion. Empty sheets return ``status=empty_sheet`` instead of a\n"
        "misleading blank image.\n"
    )
    assert tools["sch_render_visual_diff"].description == (
        "Render the exact visual delta produced by the last schematic mutation.\n\n"
        "The red pixels are the aligned before/after image difference. Metadata lists\n"
        "every changed symbol, label/net, wire, bus, junction, or document object.\n"
    )

    live_properties = tools["sch_live_preview"].parameters["properties"]
    assert set(live_properties) == {
        "sheet",
        "sheet_file",
        "include_child_sheets",
        "debounce_ms",
        "render",
        "reload",
        "force",
        "crop_to_content",
        "dpi",
        "include_title_block",
        "output_file",
    }
    assert live_properties["debounce_ms"]["default"] == 750
    assert live_properties["dpi"]["default"] == 200
    assert tools["sch_live_preview"].parameters["title"] == "sch_live_previewArguments"

    png_properties = tools["sch_render_png"].parameters["properties"]
    assert set(png_properties) == {
        "sheet",
        "sheet_file",
        "crop_to_content",
        "dpi",
        "include_title_block",
        "output_file",
    }
    assert tools["sch_render_png"].parameters["title"] == "sch_render_pngArguments"

    diff_properties = tools["sch_render_visual_diff"].parameters["properties"]
    assert set(diff_properties) == {
        "sheet",
        "sheet_file",
        "dpi",
        "include_title_block",
        "output_file",
    }
    assert tools["sch_render_visual_diff"].parameters["title"] == "sch_render_visual_diffArguments"


def test_registration_preserves_headless_metadata() -> None:
    server, _service = _registered()

    for tool in server._tool_manager.list_tools():
        metadata = get_tool_metadata(tool.name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False
        assert tool.annotations is None


def test_registration_delegates_exact_arguments_and_text_response() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    result = tools["sch_live_preview"].fn(
        sheet="Power",
        sheet_file=None,
        include_child_sheets=False,
        debounce_ms=12,
        render=False,
        reload=True,
        force=True,
        crop_to_content=False,
        dpi=144,
        include_title_block=False,
        output_file="live.png",
    )

    assert service.calls == [
        (
            "live_preview",
            {
                "sheet": "Power",
                "sheet_file": None,
                "include_child_sheets": False,
                "debounce_ms": 12,
                "render": False,
                "reload": True,
                "force": True,
                "crop_to_content": False,
                "dpi": 144,
                "include_title_block": False,
                "output_file": "live.png",
            },
        )
    ]
    assert len(result.content) == 1
    text = result.content[0]
    assert isinstance(text, TextContent)
    assert text.text == "live"
    assert result.structuredContent is None


def test_registration_converts_image_response(tmp_path: Path) -> None:
    server, service = _registered()
    image = tmp_path / "render.png"
    image.write_bytes(b"png")
    service.responses["render_png"] = SchematicRenderingResponse(
        metadata={"status": "ok", "png_path": str(image)},
        image_path=image,
    )
    tool = {item.name: item for item in server._tool_manager.list_tools()}["sch_render_png"]

    result = tool.fn()

    assert service.calls == [
        (
            "render_png",
            {
                "sheet": None,
                "sheet_file": None,
                "crop_to_content": True,
                "dpi": 200,
                "include_title_block": True,
                "output_file": None,
            },
        )
    ]
    assert result.structuredContent == {"status": "ok", "png_path": str(image)}
    assert any(isinstance(item, TextContent) for item in result.content)
    assert any(isinstance(item, ImageContent) for item in result.content)
