"""Shared test fixtures for KiCad MCP Pro."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_configure(config: pytest.Config) -> None:
    """Register local markers even when pytest is launched from the monorepo root."""
    config.addinivalue_line(
        "markers",
        "benchmark: lightweight performance regression checks with committed baselines",
    )
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end tests using Playwright (run with E2E=1)",
    )
    config.addinivalue_line(
        "markers",
        "gui: real KiCad GUI smoke tests for scheduled/manual environments",
    )
    config.addinivalue_line(
        "markers",
        "mcp_mode(mode): run the test with an explicit KiCad MCP operating mode",
    )
    config.addinivalue_line(
        "markers",
        "slow: tests that are useful for scheduled/full validation but skipped by fast loops",
    )


def tool_text(result: object) -> str:
    """Extract text from a FastMCP tool result."""
    if hasattr(result, "isError") and hasattr(result, "content"):
        return tool_text(result.content)
    if isinstance(result, tuple) and len(result) == 2:
        content, structured = result
        if isinstance(structured, dict) and "result" in structured:
            return str(structured["result"])
        return tool_text(content)
    if isinstance(result, dict):
        return json.dumps(result)
    if isinstance(result, Iterable) and not isinstance(result, str | bytes | dict):
        parts = []
        for item in result:
            if hasattr(item, "text"):
                parts.append(item.text)
            elif getattr(item, "type", None) == "image":
                continue
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(result)


async def call_tool_text(server: object, name: str, arguments: dict[str, object]) -> str:
    """Call a FastMCP tool and normalize its textual output."""
    result = await server.call_tool(name, arguments)
    return tool_text(result)


async def call_tool_payload(server: object, name: str, arguments: dict[str, object]) -> object:
    """Call a FastMCP tool and extract structured payloads when available."""
    result = await server.call_tool(name, arguments)
    if isinstance(result, tuple) and len(result) == 2:
        _, structured = result
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        return structured
    return result


async def call_tool_content(
    server: object,
    name: str,
    arguments: dict[str, object],
) -> list[object]:
    """Call a FastMCP tool and return its protocol content blocks."""
    result = await server.call_tool(name, arguments)
    if hasattr(result, "content"):
        return list(result.content)
    if isinstance(result, tuple) and result:
        content = result[0]
        if isinstance(content, Iterable) and not isinstance(content, str | bytes | dict):
            return list(content)
    if isinstance(result, Iterable) and not isinstance(result, str | bytes | dict):
        return list(result)
    return [result]


async def read_resource_text(server: object, uri: str) -> str:
    """Read an MCP resource and normalize its textual output."""
    result = await server.read_resource(uri)
    return tool_text(list(result))


async def get_prompt_text(server: object, name: str, arguments: dict[str, object]) -> str:
    """Read an MCP prompt and normalize the returned text content."""
    result = await server.get_prompt(name, arguments)
    return tool_text([result.messages[0].content])


@pytest.fixture(autouse=True)
def reset_globals(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset cached config and KiCad connection state before every test."""
    from kicad_mcp.config import reset_config
    from kicad_mcp.connection import reset_connection
    from kicad_mcp.discovery import stop_studio_project_watcher
    from kicad_mcp.utils.cache import clear_ttl_cache
    from kicad_mcp.utils.telemetry import reset_telemetry

    reset_config()
    reset_connection()
    stop_studio_project_watcher()
    clear_ttl_cache()
    reset_telemetry(shutdown_managed=True)
    monkeypatch.delenv("KICAD_MCP_PROJECT_DIR", raising=False)
    monkeypatch.delenv("KICAD_MCP_PROJECT_FILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_PCB_FILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_SCH_FILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("KICAD_MCP_SYMBOL_LIBRARY_DIR", raising=False)
    monkeypatch.delenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", raising=False)
    monkeypatch.delenv("KICAD_MCP_KICAD_CLI", raising=False)
    monkeypatch.delenv("KICAD_API_SOCKET", raising=False)
    monkeypatch.delenv("KICAD_CLI_PATH", raising=False)
    monkeypatch.delenv("KICAD_API_TOKEN", raising=False)
    monkeypatch.delenv("KICAD_MCP_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("KICAD_MCP_RETRIES", raising=False)
    monkeypatch.delenv("KICAD_MCP_HEADLESS", raising=False)
    monkeypatch.delenv("KICAD_MCP_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("KICAD_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("KICAD_MCP_PROTOCOL_LANE", raising=False)
    monkeypatch.delenv("KICAD_MCP_LEGACY_SSE", raising=False)
    monkeypatch.delenv("KICAD_MCP_STATEFUL_HTTP", raising=False)
    monkeypatch.delenv("KICAD_MCP_ENABLE_METRICS", raising=False)
    monkeypatch.delenv("KICAD_MCP_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("KICAD_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("KICAD_MCP_HOST", raising=False)
    monkeypatch.delenv("KICAD_MCP_PORT", raising=False)
    monkeypatch.delenv("KICAD_MCP_LOG_LEVEL", raising=False)
    monkeypatch.delenv("KICAD_MCP_LOG_FORMAT", raising=False)
    monkeypatch.delenv("KICAD_MCP_LOG_FILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_LOG_MAX_BYTES", raising=False)
    monkeypatch.delenv("KICAD_MCP_LOG_BACKUP_COUNT", raising=False)
    monkeypatch.delenv("KICAD_MCP_PROFILE", raising=False)
    monkeypatch.delenv("KICAD_MCP_OPERATING_MODE", raising=False)
    monkeypatch.delenv("KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS", raising=False)
    monkeypatch.delenv("KICAD_MCP_TELEMETRY_ENABLED", raising=False)
    monkeypatch.delenv("KICAD_MCP_OTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("KICAD_MCP_OTEL_HEADERS", raising=False)
    monkeypatch.delenv("KICAD_MCP_OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("KICAD_MCP_OTEL_PROTOCOL", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_PROTOCOL", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    yield
    reset_telemetry(shutdown_managed=True)


@pytest.fixture(autouse=True)
def legacy_mutating_suite_mode(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, reset_globals: None
) -> None:
    """Run tests that exercise mutating tool surfaces with an explicit mode."""
    marker = request.node.get_closest_marker("mcp_mode")
    if marker is not None:
        mode = str(marker.args[0])
    else:
        mode = ""

    path_parts = set(Path(str(request.node.path)).parts)
    if not mode and {"integration", "e2e"}.isdisjoint(path_parts):
        return
    if not mode:
        mode = "experimental"

    from kicad_mcp.config import reset_config

    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", mode)
    reset_config()


@pytest.fixture
def fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fake kicad-cli executable path."""
    cli = tmp_path / "kicad-cli"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    cli.chmod(0o755)
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", str(cli))
    return cli


@pytest.fixture
def sample_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_cli: Path) -> Path:
    """Create a minimal KiCad project and library layout."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    (project_dir / "demo.kicad_pro").write_text('{"meta": {"version": 1}}', encoding="utf-8")
    (project_dir / "demo.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    (project_dir / "demo.kicad_dru").write_text("(rules)\n", encoding="utf-8")
    (project_dir / "demo.kicad_sch").write_text(
        (
            "(kicad_sch\n"
            "\t(version 20250316)\n"
            '\t(generator "pytest")\n'
            '\t(uuid "00000000-0000-0000-0000-000000000000")\n'
            '\t(paper "A4")\n'
            "\t(lib_symbols)\n"
            "\t(sheet_instances\n"
            '\t\t(path "/" (page "1"))\n'
            "\t)\n"
            "\t(embedded_fonts no)\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    symbols_dir = tmp_path / "symbols"
    symbols_dir.mkdir()
    (symbols_dir / "Device.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "R"\n'
            '    (property "Reference" "R" (id 0) (at 0 2.54 0))\n'
            '    (property "Value" "R" (id 1) (at 0 -2.54 0))\n'
            '    (property "Description" "Resistor")\n'
            '    (property "ki_keywords" "resistor ohm")\n'
            '    (property "Footprint" "Resistor_SMD:R_0805")\n'
            '    (property "Datasheet" "https://example.com/r.pdf")\n'
            '    (pin passive line (at -2.54 0 0) (length 2.54) (name "1") (number "1"))\n'
            '    (pin passive line (at 2.54 0 180) (length 2.54) (name "2") (number "2"))\n'
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    (symbols_dir / "power.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "GND"\n'
            "    (power global)\n"
            '    (property "Reference" "#PWR" (id 0) (at 0 2.54 0))\n'
            '    (property "Value" "GND" (id 1) (at 0 -2.54 0))\n'
            '    (symbol "GND_0_1"\n'
            "      (polyline (pts (xy 0 0) (xy 0 -1.27)))\n"
            "    )\n"
            '    (symbol "GND_1_1"\n'
            '      (pin power_in line (at 0 0 270) (length 0) (name "") (number "1"))\n'
            "    )\n"
            "  )\n"
            '  (symbol "VCC"\n'
            "    (power global)\n"
            '    (property "Reference" "#PWR" (id 0) (at 0 2.54 0))\n'
            '    (property "Value" "VCC" (id 1) (at 0 3.81 0))\n'
            '    (symbol "VCC_0_1"\n'
            "      (polyline (pts (xy 0 0) (xy 0 1.27)))\n"
            "    )\n"
            '    (symbol "VCC_1_1"\n'
            '      (pin power_in line (at 0 0 90) (length 0) (name "") (number "1"))\n'
            "    )\n"
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    (symbols_dir / "Extended.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "BaseTimer"\n'
            '    (property "Reference" "U" (id 0) (at -5.08 5.08 0))\n'
            '    (property "Value" "BaseTimer" (id 1) (at 0 -5.08 0))\n'
            '    (pin input line (at -2.54 0 0) (length 2.54) (name "IN") (number "1"))\n'
            '    (pin output line (at 2.54 0 180) (length 2.54) (name "OUT") (number "2"))\n'
            "  )\n"
            '  (symbol "ChildTimer"\n'
            '    (extends "BaseTimer")\n'
            '    (property "Reference" "U" (id 0) (at -5.08 5.08 0))\n'
            '    (property "Value" "ChildTimer" (id 1) (at 0 -5.08 0))\n'
            '    (property "Footprint" "Package_DIP:DIP-8_W7.62mm" (id 2) (at 0 -7.62 0))\n'
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )
    (symbols_dir / "MultiUnit.kicad_sym").write_text(
        (
            "(kicad_symbol_lib (version 20250316) (generator pytest)\n"
            '  (symbol "DualOpamp"\n'
            '    (property "Reference" "U" (id 0) (at 0 5.08 0))\n'
            '    (property "Value" "DualOpamp" (id 1) (at 0 -5.08 0))\n'
            '    (symbol "DualOpamp_1_1"\n'
            '      (pin output line (at 7.62 0 180) (length 2.54) (name "OUTA") (number "1"))\n'
            '      (pin input line (at -7.62 -2.54 0) (length 2.54) (name "-A") (number "2"))\n'
            '      (pin input line (at -7.62 2.54 0) (length 2.54) (name "+A") (number "3"))\n'
            "    )\n"
            '    (symbol "DualOpamp_2_1"\n'
            '      (pin input line (at -7.62 2.54 0) (length 2.54) (name "+B") (number "5"))\n'
            '      (pin input line (at -7.62 -2.54 0) (length 2.54) (name "-B") (number "6"))\n'
            '      (pin output line (at 7.62 0 180) (length 2.54) (name "OUTB") (number "7"))\n'
            "    )\n"
            '    (symbol "DualOpamp_3_1"\n'
            '      (pin power_in line (at -2.54 -7.62 90) (length 2.54) (name "V-") (number "4"))\n'
            '      (pin power_in line (at -2.54 7.62 270) (length 2.54) (name "V+") (number "8"))\n'
            "    )\n"
            "  )\n"
            '  (symbol "DualChild"\n'
            '    (extends "DualOpamp")\n'
            '    (property "Reference" "U" (id 0) (at 0 5.08 0))\n'
            '    (property "Value" "DualChild" (id 1) (at 0 -5.08 0))\n'
            '    (property "Footprint" "Package_DIP:DIP-8_W7.62mm" (id 2) (at 0 -7.62 0))\n'
            "  )\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    footprints_dir = tmp_path / "footprints"
    footprints_dir.mkdir()
    resistor_lib = footprints_dir / "Resistor_SMD.pretty"
    resistor_lib.mkdir()
    (resistor_lib / "R_0805.kicad_mod").write_text(
        (
            '(footprint "R_0805"\n'
            '\t(layer "F.Cu")\n'
            '\t(property "Reference" "REF**"\n'
            "\t\t(at 0 -1.5 0)\n"
            '\t\t(layer "F.SilkS")\n'
            "\t)\n"
            '\t(property "Value" "R_0805"\n'
            "\t\t(at 0 1.5 0)\n"
            '\t\t(layer "F.Fab")\n'
            "\t)\n"
            "\t(fp_rect (start -1.4 -0.9) (end 1.4 0.9)"
            ' (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
            '\t(pad "1" smd rect (at -0.95 0) (size 0.8 1.2)'
            ' (layers "F.Cu" "F.Mask" "F.Paste"))\n'
            '\t(pad "2" smd rect (at 0.95 0) (size 0.8 1.2)'
            ' (layers "F.Cu" "F.Mask" "F.Paste"))\n'
            '\t(model "Resistor_SMD.3dshapes/R_0805.wrl")\n'
            ")\n"
        ),
        encoding="utf-8",
    )
    (resistor_lib / "R_1206.kicad_mod").write_text(
        (
            '(footprint "R_1206"\n'
            '\t(layer "F.Cu")\n'
            '\t(property "Reference" "REF**"\n'
            "\t\t(at 0 -1.8 0)\n"
            '\t\t(layer "F.SilkS")\n'
            "\t)\n"
            '\t(property "Value" "R_1206"\n'
            "\t\t(at 0 1.8 0)\n"
            '\t\t(layer "F.Fab")\n'
            "\t)\n"
            "\t(fp_rect (start -1.8 -1.0) (end 1.8 1.0)"
            ' (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
            '\t(pad "1" smd rect (at -1.4 0) (size 1.2 1.6)'
            ' (layers "F.Cu" "F.Mask" "F.Paste"))\n'
            '\t(pad "2" smd rect (at 1.4 0) (size 1.2 1.6)'
            ' (layers "F.Cu" "F.Mask" "F.Paste"))\n'
            '\t(model "Resistor_SMD.3dshapes/R_1206.wrl")\n'
            ")\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("KICAD_MCP_SYMBOL_LIBRARY_DIR", str(symbols_dir))
    monkeypatch.setenv("KICAD_MCP_FOOTPRINT_LIBRARY_DIR", str(footprints_dir))
    return project_dir


@pytest.fixture
def mock_kicad() -> MagicMock:
    """Mock KiCad IPC connection."""
    with patch("kicad_mcp.connection.KiCad") as mocked:
        instance = MagicMock()
        instance.get_version.return_value = "10.0.1"
        instance.get_open_documents.return_value = []
        mocked.return_value = instance
        yield instance


@pytest.fixture
def mock_board(mock_kicad: MagicMock) -> MagicMock:
    """Mock the active board object."""
    board = MagicMock()
    board.get_tracks.return_value = []
    board.get_vias.return_value = []
    board.get_footprints.return_value = []
    board.get_nets.return_value = []
    board.get_zones.return_value = []
    board.get_shapes.return_value = []
    board.get_pads.return_value = []
    board.get_enabled_layers.return_value = []
    board.get_selection.return_value = []
    board.get_stackup.return_value.layers = []
    board.get_as_string.return_value = "(kicad_pcb)"
    mock_kicad.get_board.return_value = board
    return board


# ---------------------------------------------------------------------------
# IPC state fixtures: simulate KiCad being connected or disconnected
# ---------------------------------------------------------------------------


@pytest.fixture
def ipc_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a scenario where KiCad IPC is reachable.

    Patches ``get_ipc_capability_state`` to return a connected state,
    powers the mock_kicad fixture, and sets ``KICAD_API_SOCKET`` so the
    connection layer attempts to use it.
    """
    from kicad_mcp.ipc.capabilities import KiCadIpcCapabilityState

    monkeypatch.setenv("KICAD_API_SOCKET", "tcp://127.0.0.1:12345")
    monkeypatch.setenv("KICAD_API_TOKEN", "test-token-1234")

    state = KiCadIpcCapabilityState()
    state.connected = True
    state.version = "10.0"
    state.open_documents = []
    state.last_error = None

    with patch(
        "kicad_mcp.ipc.capabilities.get_ipc_capability_state",
        return_value=state,
    ):
        yield


@pytest.fixture
def ipc_disconnected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a scenario where KiCad IPC is **not** reachable.

    Patches ``get_ipc_capability_state`` to return a disconnected state
    without a socket being configured, which is the default for CI/test.
    """
    from kicad_mcp.ipc.capabilities import KiCadIpcCapabilityState

    monkeypatch.delenv("KICAD_API_SOCKET", raising=False)

    state = KiCadIpcCapabilityState()
    state.connected = False
    state.version = None
    state.open_documents = []
    state.last_error = "Connection refused"

    with patch(
        "kicad_mcp.ipc.capabilities.get_ipc_capability_state",
        return_value=state,
    ):
        yield


@pytest.fixture
def ipc_with_open_board(
    mock_kicad: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    """Simulate KiCad IPC being connected with an open board file.

    Returns the mock board so tests can configure its return values.
    """
    from kicad_mcp.ipc.capabilities import KiCadIpcCapabilityState

    monkeypatch.setenv("KICAD_API_SOCKET", "tcp://127.0.0.1:12345")

    state = KiCadIpcCapabilityState()
    state.connected = True
    state.version = "10.0"
    state.open_documents = ["/project/demo.kicad_pcb"]
    state.last_error = None

    board = MagicMock()
    board.get_tracks.return_value = []
    board.get_vias.return_value = []
    board.get_footprints.return_value = []
    board.get_nets.return_value = []
    board.get_zones.return_value = []
    board.get_shapes.return_value = []
    board.get_pads.return_value = []
    board.get_enabled_layers.return_value = ["F.Cu", "B.Cu"]
    board.get_selection.return_value = []
    board.get_stackup.return_value.layers = []
    board.get_as_string.return_value = "(kicad_pcb)"
    mock_kicad.get_board.return_value = board

    with patch(
        "kicad_mcp.ipc.capabilities.get_ipc_capability_state",
        return_value=state,
    ):
        yield board
