from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kicad_mcp import server_info
from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.discovery import CliCapabilities
from kicad_mcp.server import create_server
from kicad_mcp.server_info import get_server_info_contract
from tests.conftest import call_tool_payload

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "protocol-schemas"
    / "schemas"
    / "kicad-mcp-server-info.schema.json"
)


def _validate_contract(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)


def test_server_info_contract_matches_protocol_schema(monkeypatch, sample_project) -> None:
    _ = sample_project
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "http")
    monkeypatch.setenv("KICAD_MCP_STATEFUL_HTTP", "true")
    monkeypatch.setenv("KICAD_MCP_AUTH_TOKEN", "local-test-token-with-enough-entropy")
    monkeypatch.setattr(
        "kicad_mcp.server_info.get_cli_capabilities",
        lambda _cli: CliCapabilities(
            version="KiCad 10.0.4",
            supports_ipc2581=True,
            supports_odb_export=True,
            supports_svg=True,
            supports_dxf=True,
            supports_step=True,
            supports_stepz=True,
            supports_xao=True,
            supports_render=True,
            supports_spice_netlist=True,
        ),
    )
    monkeypatch.setattr("kicad_mcp.server_info.get_kicad", lambda: object())
    monkeypatch.setattr("kicad_mcp.server_info.get_board", lambda: object())

    payload = get_server_info_contract()

    _validate_contract(payload)
    assert payload["schemaVersion"] == "1.3.0"
    assert payload["server"] == "kicad-mcp-pro"
    assert payload["description"] == "KiCad MCP Pro server for PCB and schematic workflows."
    assert payload["localizedDescriptions"] == {
        "en": "KiCad MCP Pro server for PCB and schematic workflows.",
        "tr": "PCB ve şematik iş akışları için KiCad MCP Pro sunucusu.",
    }
    assert payload["mcpProtocolVersion"] == "2025-11-25"
    assert payload["toolSchemaVersion"] == "1.0.0"
    assert payload["compatibilityRange"] == {
        "kicadStudio": {
            "required": ">=3.5.2 <4.0.0",
            "recommended": ">=3.5.2 <4.0.0",
            "testedAgainst": "3.5.2",
        },
        "kicadMcpPro": {
            "required": ">=1.0.0 <2.0.0",
            "testedAgainst": "1.0.0",
        },
    }
    assert payload["transport"] == {
        "type": "streamable-http",
        "streamableHttp": True,
        "statelessHttp": False,
        "legacySse": False,
        "authRequired": True,
        "endpoint": "http://127.0.0.1:3334/mcp",
    }
    assert payload["kicad"] == {
        "cliFound": True,
        "cliPath": str(sample_project.parent / "kicad-cli"),
        "cliVersion": "KiCad 10.0.4",
        "ipcAvailable": True,
        "ipcVersion": "KiCad 10.0.4",
        "ipcApiVersion": None,
        "ipcMajorVersion": 10,
        "ipcEndpointSource": "default",
        "livePcbContext": True,
        "liveSchematicContext": False,
        "headlessIpcRequested": False,
        "headlessIpcAvailable": False,
        "ipcDocumentLoaded": True,
    }
    operating_mode = payload["operatingMode"]
    assert operating_mode["active"] == "readonly"
    assert operating_mode["default"] == "readonly"
    assert operating_mode["available"] == [
        "readonly",
        "write",
        "manufacturing",
        "experimental",
    ]
    assert operating_mode["experimentalEnabled"] is False
    assert operating_mode["toolAvailability"]["kicad_get_version"] == {
        "available": True,
        "requiredMode": "readonly",
        "reason": None,
    }
    assert operating_mode["toolAvailability"]["pcb_add_track"] == {
        "available": False,
        "requiredMode": "write",
        "reason": "Requires write operating mode.",
    }
    assert operating_mode["toolAvailability"]["export_manufacturing_package"] == {
        "available": False,
        "requiredMode": "manufacturing",
        "reason": "Requires manufacturing operating mode.",
    }
    assert operating_mode["toolAvailability"]["route_tune_length"] == {
        "available": False,
        "requiredMode": "experimental",
        "reason": "Requires experimental operating mode.",
    }
    capabilities = payload["capabilities"]
    adapter_routing = capabilities.pop("adapterRouting")
    assert adapter_routing["schemaVersion"] == "1.0.0"
    assert set(adapter_routing["categories"]) == {
        "project",
        "pcb_read",
        "pcb_write",
        "schematic",
        "library",
        "export",
        "release_export",
        "manufacturing",
        "validation",
        "dfm",
        "routing",
        "signal_integrity",
        "power_integrity",
        "emc",
        "simulation",
        "version_control",
    }
    assert adapter_routing["categories"]["pcb_write"]["selectedBackends"]["kicad-gui-ipc"]
    assert capabilities == {
        "fileBackedDrc": True,
        "fileBackedErc": True,
        "fileBackedExports": True,
        "livePcbRead": True,
        "livePcbWrite": True,
        "liveSchematicRead": False,
        "liveSchematicWrite": False,
        "liveEditingTools": {
            "pcb_place_component": {
                "available": True,
                "backend": "kicad-ipc",
                "reason": None,
                "minimumKiCadMajor": 10,
            },
            "pcb_route_trace": {
                "available": True,
                "backend": "kicad-ipc",
                "reason": None,
                "minimumKiCadMajor": 10,
            },
            "pcb_add_zone": {
                "available": True,
                "backend": "kicad-ipc",
                "reason": None,
                "minimumKiCadMajor": 10,
            },
            "pcb_set_design_rules": {
                "available": True,
                "backend": "hybrid-file-ipc",
                "reason": None,
                "minimumKiCadMajor": 10,
            },
            "pcb_move_component": {
                "available": True,
                "backend": "kicad-ipc",
                "reason": None,
                "minimumKiCadMajor": 10,
            },
            "pcb_delete_object": {
                "available": True,
                "backend": "kicad-ipc",
                "reason": None,
                "minimumKiCadMajor": 10,
            },
            "sch_add_component": {
                "available": False,
                "backend": "hybrid-file-ipc",
                "reason": (
                    "Live schematic writes require KiCad 10+ with an open schematic document."
                ),
                "minimumKiCadMajor": 10,
            },
            "sch_add_wire": {
                "available": False,
                "backend": "hybrid-file-ipc",
                "reason": (
                    "Live schematic writes require KiCad 10+ with an open schematic document."
                ),
                "minimumKiCadMajor": 10,
            },
            "sch_modify_property": {
                "available": False,
                "backend": "hybrid-file-ipc",
                "reason": (
                    "Live schematic writes require KiCad 10+ with an open schematic document."
                ),
                "minimumKiCadMajor": 10,
            },
        },
        "chatgptConnectorCompatible": False,
        "cliExports": {
            "ipc2581": True,
            "odb": True,
            "svg": True,
            "dxf": True,
            "step": True,
            "stepz": True,
            "xao": True,
            "render": True,
            "spiceNetlist": True,
        },
    }
    assert payload["diagnostics"] == []


def test_server_info_contract_reports_degraded_live_context(monkeypatch, sample_project) -> None:
    _ = sample_project
    monkeypatch.setattr("kicad_mcp.server_info.get_kicad", lambda: object())
    monkeypatch.setattr(
        "kicad_mcp.server_info.get_board",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("No PCB is open.")),
    )

    payload = get_server_info_contract()

    _validate_contract(payload)
    assert payload["kicad"]["ipcAvailable"] is True
    assert payload["kicad"]["livePcbContext"] is False
    assert payload["capabilities"]["livePcbRead"] is False
    assert payload["capabilities"]["livePcbWrite"] is False
    assert payload["capabilities"]["liveEditingTools"]["pcb_route_trace"]["available"] is False
    assert "Live KiCad PCB context is unavailable: No PCB is open." in payload["diagnostics"]


def test_server_info_contract_reports_unavailable_ipc(monkeypatch, sample_project) -> None:
    _ = sample_project
    monkeypatch.setattr(
        "kicad_mcp.server_info.get_kicad",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("KiCad is not running.")),
    )
    monkeypatch.setattr("kicad_mcp.server_info.get_board", lambda: object())

    payload = get_server_info_contract()

    _validate_contract(payload)
    assert payload["kicad"]["ipcAvailable"] is False
    assert payload["kicad"]["livePcbContext"] is False
    assert payload["capabilities"]["liveEditingTools"]["pcb_place_component"]["available"] is False
    assert "KiCad IPC is unavailable: KiCad is not running." in payload["diagnostics"]


def test_server_info_contract_skips_live_probe_for_metadata(monkeypatch, sample_project) -> None:
    _ = sample_project
    monkeypatch.setattr(
        "kicad_mcp.server_info.get_kicad",
        lambda: (_ for _ in ()).throw(AssertionError("IPC should not be probed")),
    )
    monkeypatch.setattr(
        "kicad_mcp.server_info.get_board",
        lambda: (_ for _ in ()).throw(AssertionError("Board should not be probed")),
    )

    payload = get_server_info_contract(probe_live_context=False)

    _validate_contract(payload)
    assert payload["kicad"]["ipcAvailable"] is False
    assert payload["kicad"]["livePcbContext"] is False
    assert payload["capabilities"]["liveSchematicWrite"] is False


def test_server_info_contract_caches_cli_discovery(monkeypatch, sample_project) -> None:
    _ = sample_project
    calls = 0

    def fake_capabilities(_cli: Path) -> CliCapabilities:
        nonlocal calls
        calls += 1
        return CliCapabilities(version="KiCad 10.0.4", supports_svg=True)

    monkeypatch.setattr("kicad_mcp.server_info.get_cli_capabilities", fake_capabilities)
    monkeypatch.setattr("kicad_mcp.server_info.get_kicad", lambda: object())
    monkeypatch.setattr("kicad_mcp.server_info.get_board", lambda: object())

    first = get_server_info_contract()
    second = get_server_info_contract()

    assert first["kicad"]["cliVersion"] == "KiCad 10.0.4"
    assert second["capabilities"]["cliExports"]["svg"] is True
    assert calls == 1


def test_server_info_contract_preserves_remote_advertised_host(
    monkeypatch,
    sample_project,
) -> None:
    _ = sample_project
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "http")
    monkeypatch.setenv("KICAD_MCP_HOST", "192.168.1.42")
    monkeypatch.setenv("KICAD_MCP_AUTH_TOKEN", "remote-test-token-with-enough-entropy")
    monkeypatch.setattr("kicad_mcp.server_info.get_kicad", lambda: object())
    monkeypatch.setattr("kicad_mcp.server_info.get_board", lambda: object())

    payload = get_server_info_contract()

    _validate_contract(payload)
    assert payload["transport"]["endpoint"] == "http://192.168.1.42:3334/mcp"


def test_server_info_contract_brackets_ipv6_loopback(monkeypatch, sample_project) -> None:
    _ = sample_project
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "http")
    monkeypatch.setenv("KICAD_MCP_HOST", "::1")
    monkeypatch.setattr("kicad_mcp.server_info.get_kicad", lambda: object())
    monkeypatch.setattr("kicad_mcp.server_info.get_board", lambda: object())

    payload = get_server_info_contract()

    _validate_contract(payload)
    assert payload["transport"]["endpoint"] == "http://[::1]:3334/mcp"


def test_server_info_contract_reports_legacy_sse_transport(
    monkeypatch,
    sample_project,
) -> None:
    _ = sample_project
    monkeypatch.setenv("KICAD_MCP_TRANSPORT", "sse")
    monkeypatch.setenv("KICAD_MCP_LEGACY_SSE", "true")
    monkeypatch.setattr("kicad_mcp.server_info.get_kicad", lambda: object())
    monkeypatch.setattr("kicad_mcp.server_info.get_board", lambda: object())

    payload = get_server_info_contract()

    _validate_contract(payload)
    assert payload["transport"]["type"] == "sse"
    assert payload["transport"]["streamableHttp"] is False
    assert payload["transport"]["legacySse"] is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", "1.0.0"),
        ("1.2", "1.2.0"),
        ("1.2.3", "1.2.3"),
        ("1.2.3.4", "1.2.3"),
        ("1.2.3-beta.1", "1.2.3"),
        ("2025-11-25", "2025.11.25"),
        ("dev", "0.0.0"),
    ],
)
def test_as_semver_always_returns_three_numeric_components(raw: str, expected: str) -> None:
    assert server_info._as_semver(raw) == expected


@pytest.mark.anyio
async def test_server_info_tool_and_resource_return_same_contract(
    monkeypatch,
    sample_project,
) -> None:
    _ = sample_project
    monkeypatch.setattr("kicad_mcp.server_info.get_kicad", lambda: object())
    monkeypatch.setattr(
        "kicad_mcp.server_info.get_board",
        lambda: (_ for _ in ()).throw(KiCadConnectionError("No PCB is open.")),
    )
    server = create_server("minimal")

    tool_payload = await call_tool_payload(server, "kicad_get_server_info", {})
    resource_items = list(await server.read_resource("kicad://server/info"))
    resource_payload = json.loads(resource_items[0].content)

    assert tool_payload == resource_payload
    _validate_contract(resource_payload)
    assert resource_payload["server"] == "kicad-mcp-pro"


def test_server_info_contract_reports_kicad11_headless_adapter_routes(
    monkeypatch,
    sample_project,
) -> None:
    from kicad_mcp.ipc.capabilities import KiCadIpcCapabilityState, _operation_states
    from kicad_mcp.ipc.discovery import KiCadIpcEndpoint

    _ = sample_project
    server_info._CLI_DISCOVERY_CACHE.clear()
    monkeypatch.setattr(
        "kicad_mcp.server_info.get_cli_capabilities",
        lambda _cli: CliCapabilities(version="KiCad 11.0.0", supports_svg=True),
    )
    state = KiCadIpcCapabilityState(
        endpoint=KiCadIpcEndpoint(
            socket_path=None,
            source="default",
            token_configured=False,
            timeout_ms=2000,
        ),
        reachable=True,
        version="KiCad 11.0.0",
        api_version="11.0.0",
        major_version=11,
        live_pcb_context=False,
        live_schematic_context=False,
        headless_requested=True,
        operations=_operation_states(
            reachable=True,
            major_version=11,
            live_pcb_context=False,
            live_schematic_context=False,
            headless_requested=True,
        ),
        diagnostics=(),
    )
    monkeypatch.setattr("kicad_mcp.server_info.get_ipc_capability_state", lambda **_kwargs: state)

    payload = get_server_info_contract()

    _validate_contract(payload)
    assert payload["capabilities"]["liveEditingTools"]["pcb_route_trace"]["backend"] == (
        "kicad-ipc-headless"
    )
    routing = payload["capabilities"]["adapterRouting"]
    assert routing["context"]["kicadMajor"] == 11
    assert routing["categories"]["pcb_write"]["selectedBackends"]["kicad-11-headless-ipc"]
