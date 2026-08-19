from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata

NAMES = ["lib_assign_footprint", "lib_create_custom_symbol"]


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.library_local_authoring")
    assert spec is not None, "Library local-authoring adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.library_local_authoring")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def assign_footprint(self, reference: str, library: str, footprint: str) -> str:
        self.calls.append(("assign", reference, library, footprint))
        return "assigned"

    def create_custom_symbol(self, name: str, pins: list[dict[str, object]]) -> str:
        self.calls.append(("create", name, pins))
        return "created"


def test_registration_preserves_exact_contract_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("library-local-authoring-test")
    service = FakeService()
    adapter.register(server, adapter.LibraryLocalAuthoringDependencies(service=service))
    tools = server._tool_manager.list_tools()

    assert [tool.name for tool in tools] == NAMES
    by_name = {tool.name: tool for tool in tools}
    assert (
        by_name["lib_assign_footprint"].description
        == "Assign a footprint property to a schematic symbol."
    )
    assert by_name["lib_assign_footprint"].parameters == {
        "properties": {
            "reference": {"title": "Reference", "type": "string"},
            "library": {"title": "Library", "type": "string"},
            "footprint": {"title": "Footprint", "type": "string"},
        },
        "required": ["reference", "library", "footprint"],
        "title": "lib_assign_footprintArguments",
        "type": "object",
    }
    assert by_name["lib_create_custom_symbol"].description == (
        "Create a simple custom symbol in the active project directory."
    )
    assert by_name["lib_create_custom_symbol"].parameters == {
        "properties": {
            "name": {"title": "Name", "type": "string"},
            "pins": {
                "items": {"additionalProperties": True, "type": "object"},
                "title": "Pins",
                "type": "array",
            },
        },
        "required": ["name", "pins"],
        "title": "lib_create_custom_symbolArguments",
        "type": "object",
    }
    for name in NAMES:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False

    assert by_name["lib_assign_footprint"].fn("R1", "Resistor_SMD", "R_0805") == "assigned"
    pins: list[dict[str, object]] = [{"number": "1", "name": "A"}]
    assert by_name["lib_create_custom_symbol"].fn("Demo", pins) == "created"
    assert service.calls == [
        ("assign", "R1", "Resistor_SMD", "R_0805"),
        ("create", "Demo", pins),
    ]


def test_library_root_preserves_local_authoring_registration_order() -> None:
    from kicad_mcp.tools.library import register

    server = FastMCP("library-local-authoring-order-test")
    register(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name
        in {
            "lib_verify_component_contract",
            *NAMES,
            "lib_get_datasheet_url",
        }
    ]
    assert relevant == [
        "lib_verify_component_contract",
        *NAMES,
        "lib_get_datasheet_url",
    ]


def test_root_wiring_preserves_late_monkeypatch_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import kicad_mcp.tools.library as library_mod

    server = FastMCP("library-local-authoring-late-binding-test")
    library_mod.register(server)
    footprint = tmp_path / "R_0805.kicad_mod"
    footprint.write_text("(footprint)", encoding="utf-8")
    updates: list[tuple[str, str, str]] = []
    monkeypatch.setattr(library_mod, "_footprint_file", lambda _lib, _fp: footprint)
    monkeypatch.setattr(
        library_mod,
        "update_symbol_property",
        lambda ref, field, value: updates.append((ref, field, value)),
    )

    tool = next(
        tool for tool in server._tool_manager.list_tools() if tool.name == "lib_assign_footprint"
    )
    assert tool.fn("R1", "Resistor_SMD", "R_0805") == (
        "Assigned footprint 'Resistor_SMD:R_0805' to 'R1'."
    )
    assert updates == [("R1", "Footprint", "Resistor_SMD:R_0805")]


class FakePinTableService(FakeService):
    def generate_symbol_from_pintable(
        self,
        name: str,
        pins: list[dict[str, object]],
        reference_prefix: str = "U",
        description: str = "",
        datasheet: str = "",
        footprint_hint: str = "",
        output_path: str = "",
    ) -> str:
        self.calls.append(
            (
                "generate-pintable",
                name,
                pins,
                reference_prefix,
                description,
                datasheet,
                footprint_hint,
                output_path,
            )
        )
        return "generated"


def test_pin_table_registration_preserves_exact_contract_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("library-local-authoring-pintable-test")
    service = FakePinTableService()
    deps = adapter.LibraryLocalAuthoringDependencies(service=service)

    adapter.register_pin_table_generator(server, deps)

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["lib_generate_symbol_from_pintable"]
    tool = tools[0]
    assert tool.description.startswith(
        "Generate a KiCad symbol (.kicad_sym) from a pin table and save it."
    )
    metadata = get_tool_metadata(tool.name)
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
    pins: list[dict[str, object]] = [{"number": "1", "name": "VIN"}]
    assert tool.fn("Demo", pins) == "generated"
    assert service.calls == [("generate-pintable", "Demo", pins, "U", "", "", "", "")]


def test_library_root_preserves_pin_table_generator_late_position() -> None:
    from kicad_mcp.tools.library import register

    server = FastMCP("library-local-authoring-pintable-order-test")
    register(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name
        in {
            "lib_check_derating",
            "lib_generate_symbol_from_pintable",
            "lib_recommend_part",
            "lib_bind_part_to_symbol",
        }
    ]
    assert relevant == [
        "lib_check_derating",
        "lib_generate_symbol_from_pintable",
        "lib_recommend_part",
        "lib_bind_part_to_symbol",
    ]
