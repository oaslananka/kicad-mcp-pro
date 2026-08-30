from __future__ import annotations

import importlib
import importlib.util
from typing import Any


def _service_type() -> type[Any]:
    try:
        spec = importlib.util.find_spec("kicad_mcp.project.help")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "Project help service module must be extracted"
    module = importlib.import_module("kicad_mcp.project.help")
    service_type = getattr(module, "ProjectHelpService", None)
    assert service_type is not None, "ProjectHelpService must own quick-start rendering behavior"
    return service_type


def test_help_text_lists_categories_and_profiles_in_order() -> None:
    service_type = _service_type()
    service = service_type(
        category_descriptions=lambda: {"pcb": "PCB tools", "schematic": "Schematic tools"},
        available_profiles=lambda: ["full", "minimal"],
    )

    text = service.help_text()

    assert text.startswith("# KiCad MCP Pro Quick Start")
    assert "1. Call `kicad_get_version()` to verify the runtime." in text
    assert "- `pcb`: PCB tools" in text
    assert "- `schematic`: Schematic tools" in text
    assert text.index("- `pcb`: PCB tools") < text.index("- `schematic`: Schematic tools")
    assert "Profiles:" in text
    assert "- `full`" in text
    assert "- `minimal`" in text
    assert text.index("- `full`") < text.index("- `minimal`")


def test_help_text_handles_no_categories_or_profiles() -> None:
    service_type = _service_type()
    service = service_type(
        category_descriptions=lambda: {},
        available_profiles=lambda: [],
    )

    text = service.help_text()

    assert "Available categories:" in text
    assert "Profiles:" in text
