from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.aliases import ALIASES
from kicad_mcp.tools.metadata import get_tool_metadata

CANONICAL = [
    "export_step",
    "export_stepz",
    "export_xao",
    "export_brep",
    "export_glb",
    "export_gencad",
    "export_ipc_d356",
    "export_ply",
    "export_stl",
    "export_u3d",
    "export_vrml",
    "export_ps",
]
REGISTERED = ["export_3d_step", *CANONICAL]
FORMATS = [
    "step",
    "stepz",
    "xao",
    "brep",
    "glb",
    "gencad",
    "ipc_d356",
    "ply",
    "stl",
    "u3d",
    "vrml",
    "ps",
]
DESCRIPTIONS = {
    "export_step": "Export a STEP model for the active board.",
    "export_stepz": "Export a STEPZ model for the active board.",
    "export_xao": "Export an XAO model for the active board.",
    "export_brep": "Export BREP format for the active board.",
    "export_glb": "Export GLB format for the active board.",
    "export_gencad": "Export GenCAD format for the active board.",
    "export_ipc_d356": "Export IPC-D-356 format for the active board.",
    "export_ply": "Export PLY format for the active board.",
    "export_stl": "Export STL format for the active board.",
    "export_u3d": "Export U3D format for the active board.",
    "export_vrml": "Export VRML format for the active board.",
    "export_ps": "Export PostScript format for the active board.",
}


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_pcb_file_formats")
    assert spec is not None, "PCB single-file export adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_pcb_file_formats")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def export(self, format_name: str, output_path: str = "", **_kwargs: object) -> str:
        self.calls.append((format_name, output_path))
        return f"raw::{format_name}::{output_path}"


def _registered() -> tuple[FastMCP, FakeService]:
    adapter = _adapter()
    server = FastMCP("export-pcb-file-formats-test")
    service = FakeService()
    adapter.register(
        server,
        adapter.ExportPcbFileFormatsDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_names_schemas_descriptions_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == REGISTERED
    alias = tools["export_3d_step"]
    assert alias.parameters == {
        "properties": {},
        "title": "export_3d_stepArguments",
        "type": "object",
    }
    assert alias.description == (
        "Deprecated alias of ``export_step``; exports a STEP model for the active board.\n\n"
        "Retained for backward compatibility. Prefer ``export_step``, which accepts an\n"
        "optional output path. This alias logs a one-time deprecation warning.\n"
    )
    for name in CANONICAL:
        assert tools[name].parameters == {
            "properties": {
                "output_path": {
                    "default": "",
                    "title": "Output Path",
                    "type": "string",
                }
            },
            "title": f"{name}Arguments",
            "type": "object",
        }
        assert tools[name].description == DESCRIPTIONS[name]
    for name in REGISTERED:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False
    assert ALIASES["export_3d_step"] == "export_step"


def test_registration_preserves_notice_alias_and_delegation() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    for name, format_name in zip(CANONICAL, FORMATS, strict=True):
        assert (
            tools[name].fn(f"{format_name}.out") == f"notice::raw::{format_name}::{format_name}.out"
        )
    assert tools["export_3d_step"].fn() == "notice::raw::step::"
    assert service.calls == [
        *((format_name, f"{format_name}.out") for format_name in FORMATS),
        ("step", ""),
    ]


def test_export_composition_root_preserves_file_format_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-pcb-file-formats-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant_names = {"export_sch_python_bom", *REGISTERED, "pcb_export_3d_pdf"}
    relevant = [name for name in names if name in relevant_names]
    assert relevant == ["export_sch_python_bom", *REGISTERED, "pcb_export_3d_pdf"]
