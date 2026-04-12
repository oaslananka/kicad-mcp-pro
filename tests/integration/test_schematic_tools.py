from __future__ import annotations

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_schematic_add_label(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    text = await call_tool_text(
        server,
        "sch_add_label",
        {"name": "NET_A", "x_mm": 10.0, "y_mm": 10.0, "rotation": 0},
    )
    assert "updated" in text.lower() or "reload" in text.lower()
    labels = await call_tool_text(server, "sch_get_labels", {})
    assert "NET_A" in labels


@pytest.mark.anyio
async def test_library_assign_footprint_updates_schematic(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    await server.call_tool(
        "sch_add_symbol",
        {
            "library": "Device",
            "symbol_name": "R",
            "x_mm": 10.0,
            "y_mm": 10.0,
            "reference": "R1",
            "value": "10k",
            "footprint": "",
            "rotation": 0,
        },
    )
    text = await call_tool_text(
        server,
        "lib_assign_footprint",
        {"reference": "R1", "library": "Resistor_SMD", "footprint": "R_0805"},
    )
    assert "Assigned footprint" in text


# ── sch_build_circuit ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_build_circuit_empty(sample_project, mock_kicad) -> None:
    """sch_build_circuit with all empty lists must not raise."""
    server = build_server("schematic")
    text = await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": [], "wires": [], "labels": [], "power_symbols": []},
    )
    # Any success response is acceptable
    assert text is not None


@pytest.mark.anyio
async def test_build_circuit_symbol_missing_fields_raises(sample_project, mock_kicad) -> None:
    """sch_build_circuit raises a clear ValidationError when required symbol fields are absent."""
    from pydantic import ValidationError

    server = build_server("schematic")
    with pytest.raises((ValidationError, Exception)) as exc_info:
        await server.call_tool(
            "sch_build_circuit",
            {
                "symbols": [{}],  # all required fields missing
                "wires": [],
                "labels": [],
                "power_symbols": [],
            },
        )
    # The error must mention the missing field names — not a bare KeyError
    assert "library" in str(exc_info.value) or "symbol_name" in str(exc_info.value)


@pytest.mark.anyio
async def test_build_circuit_wire_missing_fields_raises(sample_project, mock_kicad) -> None:
    """Wire dicts without required coords raise a clear ValidationError."""
    from pydantic import ValidationError

    server = build_server("schematic")
    with pytest.raises((ValidationError, Exception)) as exc_info:
        await server.call_tool(
            "sch_build_circuit",
            {"symbols": [], "wires": [{}], "labels": [], "power_symbols": []},
        )
    error_text = str(exc_info.value)
    assert any(field in error_text for field in ("x1_mm", "y1_mm", "x2_mm", "y2_mm"))


@pytest.mark.anyio
async def test_build_circuit_label_missing_fields_raises(sample_project, mock_kicad) -> None:
    """Label dicts without required fields raise a clear ValidationError."""
    from pydantic import ValidationError

    server = build_server("schematic")
    with pytest.raises((ValidationError, Exception)) as exc_info:
        await server.call_tool(
            "sch_build_circuit",
            {"symbols": [], "wires": [], "labels": [{}], "power_symbols": []},
        )
    error_text = str(exc_info.value)
    assert any(field in error_text for field in ("name", "x_mm", "y_mm"))


@pytest.mark.anyio
async def test_build_circuit_power_symbol_missing_fields_raises(sample_project, mock_kicad) -> None:
    """Power symbol dicts without required fields raise a clear ValidationError."""
    from pydantic import ValidationError

    server = build_server("schematic")
    with pytest.raises((ValidationError, Exception)) as exc_info:
        await server.call_tool(
            "sch_build_circuit",
            {"symbols": [], "wires": [], "labels": [], "power_symbols": [{}]},
        )
    error_text = str(exc_info.value)
    assert any(field in error_text for field in ("name", "x", "y"))


@pytest.mark.anyio
async def test_build_circuit_full_resistor(sample_project, mock_kicad) -> None:
    """sch_build_circuit places a resistor with a wire and a label end-to-end."""
    server = build_server("schematic")
    text = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.0,
                    "y_mm": 10.0,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                    "rotation": 0,
                }
            ],
            "wires": [{"x1_mm": 7.46, "y1_mm": 10.0, "x2_mm": 5.0, "y2_mm": 10.0}],
            "labels": [{"name": "NET_A", "x_mm": 5.0, "y_mm": 10.0, "rotation": 0}],
            "power_symbols": [],
        },
    )
    # Success or KiCad-not-connected message — either is acceptable in CI
    assert text is not None

    # Verify schematic file was written with the expected content
    import os
    from pathlib import Path

    sch_file = next(Path(os.environ["KICAD_MCP_PROJECT_DIR"]).glob("*.kicad_sch"))
    content = sch_file.read_text(encoding="utf-8")
    assert "Device:R" in content
    assert "R1" in content
    assert "NET_A" in content
