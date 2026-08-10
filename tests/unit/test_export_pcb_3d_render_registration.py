from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Protocol

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from kicad_mcp.tools.metadata import get_tool_metadata


class RenderResponse(Protocol):
    text: str | None
    image_path: Path | None
    summary: str | None


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_pcb_3d_render")
    assert spec is not None, "PCB 3D render adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_pcb_3d_render")


def _response_type():
    spec = importlib.util.find_spec("kicad_mcp.export.pcb_3d_render")
    assert spec is not None, "PCB 3D render service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.pcb_3d_render")
    return module.Pcb3dRenderResponse


class FakePcb3dRenderService:
    def __init__(self, response: RenderResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def render(self, **kwargs: object) -> RenderResponse:
        self.calls.append(kwargs)
        return self.response


def _registered(response: RenderResponse) -> tuple[FastMCP, FakePcb3dRenderService]:
    adapter = _adapter()
    server = FastMCP("export-pcb-3d-render-test")
    service = FakePcb3dRenderService(response)
    adapter.register(
        server,
        adapter.ExportPcb3dRenderDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_name_schema_description_and_metadata() -> None:
    response_type = _response_type()
    server, _service = _registered(response_type(text="raw"))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_3d_render"]
    assert tools["export_3d_render"].description == (
        "Render a 3D view of the active PCB board to a PNG image.\n\n"
        "Parameters\n----------\n"
        "output_file : str\n"
        "    Output file name (PNG or JPG). Defaults to ``render.png``.\n"
        "side : str\n"
        "    View direction: ``top``, ``bottom``, ``front``, ``back``, ``left``, ``right``.\n"
        "zoom : float\n"
        "    Camera zoom factor (0.05–20.0).\n"
        "width, height : int | None\n"
        "    Output image dimensions in pixels.\n"
        "quality : float | None\n"
        "    Rendering quality (0.0–1.0).\n"
        "preset : str | None\n"
        "    Render preset name (e.g. ``photo``, ``standard``).\n"
        "use_board_stackup_colors : bool\n"
        "    Use the board stackup-defined colors.\n"
        "floor : bool\n"
        "    Show the reflective floor. Default True.\n"
        "perspective : bool\n"
        "    Perspective projection. Set False for orthographic.\n"
        "pan_x, pan_y : float | None\n"
        "    Camera pan offset in mm.\n"
        "rotate_x, rotate_y, rotate_z : float | None\n"
        "    Camera rotation in degrees.\n"
        "light_top, light_bottom, light_side, light_camera : float | None\n"
        "    Light intensity for each direction (0.0–1.0).\n"
        "light_side_elevation : float | None\n"
        "    Side light elevation angle in degrees.\n"
    )
    assert tools["export_3d_render"].parameters == {
        "properties": {
            "output_file": {"default": "render.png", "title": "Output File", "type": "string"},
            "side": {"default": "top", "title": "Side", "type": "string"},
            "zoom": {"default": 1.0, "title": "Zoom", "type": "number"},
            "width": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Width",
            },
            "height": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Height",
            },
            "quality": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Quality",
            },
            "preset": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Preset",
            },
            "use_board_stackup_colors": {
                "default": False,
                "title": "Use Board Stackup Colors",
                "type": "boolean",
            },
            "floor": {"default": True, "title": "Floor", "type": "boolean"},
            "perspective": {"default": True, "title": "Perspective", "type": "boolean"},
            "pan_x": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Pan X",
            },
            "pan_y": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Pan Y",
            },
            "rotate_x": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Rotate X",
            },
            "rotate_y": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Rotate Y",
            },
            "rotate_z": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Rotate Z",
            },
            "light_top": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Light Top",
            },
            "light_bottom": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Light Bottom",
            },
            "light_side": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Light Side",
            },
            "light_camera": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Light Camera",
            },
            "light_side_elevation": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Light Side Elevation",
            },
        },
        "title": "export_3d_renderArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("export_3d_render")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_preserves_text_result_notice_and_delegation() -> None:
    response_type = _response_type()
    server, service = _registered(response_type(text="raw render"))
    tool = server._tool_manager.list_tools()[0]

    result = tool.fn(output_file="custom.png", side="bottom", zoom=2.0)

    text = next(item for item in result.content if isinstance(item, TextContent))
    assert text.text == "notice::raw render"
    assert result.structuredContent is None
    assert service.calls == [
        {
            "output_file": "custom.png",
            "side": "bottom",
            "zoom": 2.0,
            "width": None,
            "height": None,
            "quality": None,
            "preset": None,
            "use_board_stackup_colors": False,
            "floor": True,
            "perspective": True,
            "pan_x": None,
            "pan_y": None,
            "rotate_x": None,
            "rotate_y": None,
            "rotate_z": None,
            "light_top": None,
            "light_bottom": None,
            "light_side": None,
            "light_camera": None,
            "light_side_elevation": None,
        }
    ]


def test_registration_preserves_image_result_metadata_and_text(tmp_path: Path) -> None:
    response_type = _response_type()
    image_path = tmp_path / "render.png"
    image_path.write_bytes(b"png")
    server, _service = _registered(
        response_type(image_path=image_path, summary="Rendered board image exported to render.png")
    )
    tool = server._tool_manager.list_tools()[0]

    result = tool.fn(
        output_file="render.png",
        side="right",
        zoom=3.0,
        width=800,
        height=600,
        preset="photo",
    )

    metadata = {
        "status": "ok",
        "png_path": str(image_path),
        "side": "right",
        "zoom": 3.0,
        "width": 800,
        "height": 600,
        "preset": "photo",
    }
    assert result.structuredContent == metadata
    text = next(item for item in result.content if isinstance(item, TextContent))
    assert text.text.startswith("notice::Rendered board image exported to render.png\n{")
    image = next(item for item in result.content if isinstance(item, ImageContent))
    assert image.mimeType == "image/png"
    assert image.data


def test_export_root_preserves_3d_render_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-pcb-3d-render-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name in {"pcb_export_3d_pdf", "export_3d_render", "export_pick_and_place"}
    ]
    assert relevant == ["pcb_export_3d_pdf", "export_3d_render", "export_pick_and_place"]
