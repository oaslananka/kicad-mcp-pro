from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.config import KiCadMCPConfig
from kicad_mcp.ipc.capabilities import (
    REQUIRED_LIVE_EDITING_TOOLS,
    KiCadIpcCapabilityState,
    get_ipc_capability_state,
)
from kicad_mcp.ipc.client import KiCadIpcClient
from kicad_mcp.ipc.discovery import KiCadIpcDiscovery
from kicad_mcp.ipc.errors import KiCadIpcUnavailableError


class FakeIpcClient:
    def __init__(
        self,
        *,
        version: str = "KiCad 10.0.4",
        api_version: str = "10.0.0",
        board_open: bool = True,
        schematic_open: bool = True,
    ) -> None:
        self.version = version
        self.api_version = api_version
        self.board_open = board_open
        self.schematic_open = schematic_open

    def probe(self) -> dict[str, object]:
        return {
            "connected": True,
            "version": self.version,
            "apiVersion": self.api_version,
        }

    def board(self) -> object:
        if not self.board_open:
            raise KiCadIpcUnavailableError("No PCB is open.")
        return object()

    def has_open_schematic(self) -> bool:
        return self.schematic_open


def test_ipc_discovery_uses_configured_socket_and_kicad_api_socket_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_cli: Path,
) -> None:
    configured = tmp_path / "configured.sock"
    env_socket = tmp_path / "env.sock"

    cfg = KiCadMCPConfig(kicad_cli=fake_cli, kicad_socket_path=configured)
    assert KiCadIpcDiscovery(config_factory=lambda: cfg).discover().socket_path == configured

    monkeypatch.setenv("KICAD_API_SOCKET", str(env_socket))
    env_cfg = KiCadMCPConfig(kicad_cli=fake_cli)
    discovered = KiCadIpcDiscovery(config_factory=lambda: env_cfg).discover()

    assert discovered.socket_path == env_socket
    assert discovered.source == "environment"


def test_ipc_discovery_preserves_explicit_uri_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    fake_cli: Path,
) -> None:
    endpoint = r"ipc://C:\Users\Admin\AppData\Local\Temp\kicad\api.sock"
    monkeypatch.setenv("KICAD_API_SOCKET", endpoint)

    cfg = KiCadMCPConfig(kicad_cli=fake_cli)
    discovered = KiCadIpcDiscovery(config_factory=lambda: cfg).discover()

    assert discovered.socket_path == endpoint
    assert discovered.source == "environment"


def test_ipc_capability_matrix_kicad_10_exposes_required_live_editing_tools(
    fake_cli: Path,
) -> None:
    state = get_ipc_capability_state(
        client=FakeIpcClient(version="KiCad 10.0.4", schematic_open=True),
        config_factory=lambda: KiCadMCPConfig(kicad_cli=fake_cli),
    )

    assert state.reachable is True
    assert state.version == "KiCad 10.0.4"
    assert state.major_version == 10
    assert state.live_pcb_context is True
    assert state.live_schematic_context is True
    assert state.live_pcb_write is True
    assert state.live_schematic_write is True
    assert state.available_live_tools() == REQUIRED_LIVE_EDITING_TOOLS
    assert state.tool_available("pcb_route_trace") is True
    assert state.tool_available("sch_add_component") is True


def test_ipc_capability_matrix_kicad_9_limits_live_schematic_writes(fake_cli: Path) -> None:
    state = get_ipc_capability_state(
        client=FakeIpcClient(version="KiCad 9.0.8", schematic_open=True),
        config_factory=lambda: KiCadMCPConfig(kicad_cli=fake_cli),
    )

    assert state.major_version == 9
    assert state.live_pcb_write is True
    assert state.live_schematic_context is False
    assert state.live_schematic_write is False
    assert state.tool_available("pcb_place_component") is True
    assert state.tool_available("sch_add_component") is False


def test_ipc_capability_state_falls_back_when_ipc_unavailable(fake_cli: Path) -> None:
    class UnavailableClient:
        def probe(self) -> dict[str, object]:
            raise KiCadIpcUnavailableError("KiCad is not running.")

    state = get_ipc_capability_state(
        client=UnavailableClient(),
        config_factory=lambda: KiCadMCPConfig(kicad_cli=fake_cli),
    )

    assert isinstance(state, KiCadIpcCapabilityState)
    assert state.reachable is False
    assert state.live_pcb_read is False
    assert state.live_pcb_write is False
    assert state.available_live_tools() == frozenset()
    assert "KiCad IPC is unavailable: KiCad is not running." in state.diagnostics
    for tool_name in REQUIRED_LIVE_EDITING_TOOLS:
        assert state.tool_available(tool_name) is False


def test_ipc_client_normalizes_lazy_connection_failures() -> None:
    class LazyConnectionFailure:
        def get_version(self) -> str:
            raise ConnectionError("Connection refused")

    client = KiCadIpcClient(client_factory=lambda: LazyConnectionFailure())

    with pytest.raises(KiCadIpcUnavailableError, match="Connection refused"):
        client.probe()


def test_kicad11_requires_explicit_headless_configuration(fake_cli: Path) -> None:
    gui_state = get_ipc_capability_state(
        client=FakeIpcClient(
            version="KiCad 11.0.0",
            api_version="11.0.0",
            board_open=False,
            schematic_open=False,
        ),
        config_factory=lambda: KiCadMCPConfig(kicad_cli=fake_cli, headless=False),
    )
    headless_state = get_ipc_capability_state(
        client=FakeIpcClient(
            version="KiCad 11.0.0",
            api_version="11.0.0",
            board_open=False,
            schematic_open=False,
        ),
        config_factory=lambda: KiCadMCPConfig(kicad_cli=fake_cli, headless=True),
    )

    assert gui_state.headless_ipc_available is False
    assert gui_state.live_pcb_write is False
    assert headless_state.headless_ipc_available is True
    assert headless_state.live_pcb_write is True
    assert headless_state.live_schematic_write is True
