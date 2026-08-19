from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata

NAMES = [
    "lib_generate_footprint_ipc7351",
    "lib_validate_footprint_ipc7351",
    "lib_certify_footprint",
]


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.library_footprint_engineering")
    assert spec is not None, "Footprint engineering adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.library_footprint_engineering")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def generate_footprint_ipc7351(
        self,
        package: str,
        density: str = "B",
        pin_count: int | None = None,
        pitch_mm: float | None = None,
        body_l_mm: float | None = None,
        body_w_mm: float | None = None,
        rows: int = 1,
        exposed_pad_mm: float | None = None,
        ball_diameter_mm: float | None = None,
        output_path: str = "",
    ) -> str:
        self.calls.append(
            (
                "generate",
                package,
                density,
                pin_count,
                pitch_mm,
                body_l_mm,
                body_w_mm,
                rows,
                exposed_pad_mm,
                ball_diameter_mm,
                output_path,
            )
        )
        return "generated"

    def validate_footprint_ipc7351(
        self,
        footprint_path: str,
        size_code: str,
        density: str = "B",
        tolerance_mm: float = 0.12,
    ) -> str:
        self.calls.append(("validate", footprint_path, size_code, density, tolerance_mm))
        return "validated"

    def certify_footprint(self, footprint_path: str) -> str:
        self.calls.append(("certify", footprint_path))
        return "certified"


def test_registration_preserves_names_descriptions_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("library-footprint-engineering-test")
    service = FakeService()
    adapter.register(server, adapter.LibraryFootprintEngineeringDependencies(service=service))
    tools = server._tool_manager.list_tools()

    assert [tool.name for tool in tools] == NAMES
    by_name = {tool.name: tool for tool in tools}
    assert by_name[NAMES[0]].description.startswith(
        "Generate an IPC-7351B compliant KiCad footprint (.kicad_mod) and save it."
    )
    assert by_name[NAMES[1]].description.startswith(
        "Validate a two-terminal chip footprint against its IPC-7351B nominal (hard gate)."
    )
    assert by_name[NAMES[2]].description.startswith(
        "Certify a footprint against package, documentation, and standard checks (#201)."
    )
    for name in NAMES:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False

    assert by_name[NAMES[0]].fn("0805") == "generated"
    assert by_name[NAMES[1]].fn("x.kicad_mod", "0805") == "validated"
    assert by_name[NAMES[2]].fn("x.kicad_mod") == "certified"
    assert service.calls == [
        ("generate", "0805", "B", None, None, None, None, 1, None, None, ""),
        ("validate", "x.kicad_mod", "0805", "B", 0.12),
        ("certify", "x.kicad_mod"),
    ]


def test_library_root_preserves_footprint_engineering_registration_order() -> None:
    from kicad_mcp.tools.library import register

    server = FastMCP("library-footprint-engineering-order-test")
    register(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name
        in {
            "lib_bind_part_to_symbol",
            *NAMES,
            "lib_check_derating",
        }
    ]
    assert relevant == [*NAMES, "lib_check_derating", "lib_bind_part_to_symbol"]
