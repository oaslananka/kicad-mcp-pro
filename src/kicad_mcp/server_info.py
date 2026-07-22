"""Versioned server-info and capability discovery contract."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from . import __version__
from .adapter_matrix import AdapterRuntimeContext, adapter_routing_contract
from .compatibility import MCP_PROTOCOL_VERSION, MCP_TOOL_SCHEMA_VERSION, compatibility_summary
from .config import get_config
from .connection import get_board, get_kicad
from .discovery import CliCapabilities, get_cli_capabilities
from .i18n import SERVER_DESCRIPTION, localize, localized_message_variants
from .ipc.capabilities import get_ipc_capability_state
from .ipc.client import KiCadIpcClient
from .operating_modes import operating_mode_contract

SERVER_INFO_SCHEMA_VERSION = "1.3.0"
_BIND_ALL_HOSTS = {"0.0.0.0", "::"}  # noqa: S104 - bind-all sentinel, not a socket bind.
_SEMVER_NUMBER_RE = re.compile(r"\d+")
TransportType = Literal["stdio", "streamable-http", "sse"]


@dataclass(frozen=True)
class _CliDiscovery:
    found: bool
    version: str | None
    capabilities: CliCapabilities | None


_CLI_DISCOVERY_CACHE: dict[tuple[Path, int | None], _CliDiscovery] = {}


def get_server_info_contract(*, probe_live_context: bool = True) -> dict[str, object]:
    """Return the stable server-info/capabilities payload for clients."""
    cfg = get_config()
    cli = _cached_cli_discovery(cfg.kicad_cli)
    ipc_state = get_ipc_capability_state(
        client=KiCadIpcClient(client_factory=get_kicad, board_factory=get_board),
        fallback_version=cli.version,
        probe_live_context=probe_live_context,
    )
    diagnostics = _diagnostics(
        cli_found=cli.found,
        live_diagnostics=ipc_state.diagnostics,
    )
    return {
        "schemaVersion": SERVER_INFO_SCHEMA_VERSION,
        "server": "kicad-mcp-pro",
        "description": localize(SERVER_DESCRIPTION),
        "localizedDescriptions": localized_message_variants(SERVER_DESCRIPTION),
        "version": __version__,
        "mcpProtocolVersion": MCP_PROTOCOL_VERSION,
        "toolSchemaVersion": _as_semver(MCP_TOOL_SCHEMA_VERSION),
        "compatibilityRange": _compatibility_range(),
        "transport": get_transport_metadata(),
        "kicad": {
            "cliFound": cli.found,
            "cliPath": str(cfg.kicad_cli),
            "cliVersion": cli.version,
            "ipcAvailable": ipc_state.reachable,
            "ipcVersion": ipc_state.version,
            "ipcApiVersion": ipc_state.api_version,
            "ipcMajorVersion": ipc_state.major_version,
            "ipcEndpointSource": ipc_state.endpoint.source,
            "livePcbContext": ipc_state.live_pcb_context,
            "liveSchematicContext": ipc_state.live_schematic_context,
            "headlessIpcRequested": ipc_state.headless_requested,
            "headlessIpcAvailable": ipc_state.headless_ipc_available,
            "ipcDocumentLoaded": ipc_state.live_pcb_context or ipc_state.live_schematic_context,
        },
        "operatingMode": operating_mode_contract(cfg),
        "capabilities": {
            "fileBackedDrc": cli.found,
            "fileBackedErc": cli.found,
            "fileBackedExports": cli.found,
            "livePcbRead": ipc_state.live_pcb_read,
            "livePcbWrite": ipc_state.live_pcb_write,
            "liveSchematicRead": ipc_state.live_schematic_read,
            "liveSchematicWrite": ipc_state.live_schematic_write,
            "liveEditingTools": ipc_state.live_editing_contract(),
            "chatgptConnectorCompatible": False,
            "adapterRouting": adapter_routing_contract(
                AdapterRuntimeContext(
                    kicad_major=ipc_state.major_version,
                    ipc_reachable=ipc_state.reachable,
                    live_pcb_context=ipc_state.live_pcb_context,
                    live_schematic_context=ipc_state.live_schematic_context,
                    headless_ipc_available=ipc_state.headless_ipc_available,
                    cli_available=cli.found,
                    ngspice_available=bool(cfg.ngspice_cli and cfg.ngspice_cli.exists())
                    or shutil.which("ngspice") is not None,
                    freerouting_available=bool(
                        cfg.freerouting_jar and cfg.freerouting_jar.exists()
                    ),
                    docker_available=shutil.which(cfg.docker_executable) is not None,
                    network_available=False,
                )
            ),
            "cliExports": {
                "ipc2581": bool(cli.capabilities and cli.capabilities.supports_ipc2581),
                "odb": bool(cli.capabilities and cli.capabilities.supports_odb_export),
                "svg": bool(cli.capabilities and cli.capabilities.supports_svg),
                "dxf": bool(cli.capabilities and cli.capabilities.supports_dxf),
                "step": bool(cli.capabilities and cli.capabilities.supports_step),
                "stepz": bool(cli.capabilities and cli.capabilities.supports_stepz),
                "xao": bool(cli.capabilities and cli.capabilities.supports_xao),
                "render": bool(cli.capabilities and cli.capabilities.supports_render),
                "spiceNetlist": bool(cli.capabilities and cli.capabilities.supports_spice_netlist),
            },
        },
        "diagnostics": diagnostics,
    }


def get_transport_metadata() -> dict[str, object]:
    """Return advertised transport metadata shared by server-info and well-known cards."""
    cfg = get_config()
    transport_type = _transport_type()
    return {
        "type": transport_type,
        "streamableHttp": transport_type == "streamable-http",
        "statelessHttp": transport_type == "streamable-http" and not cfg.stateful_http,
        "legacySse": cfg.legacy_sse or transport_type == "sse",
        "authRequired": transport_type != "stdio" and bool(cfg.auth_token),
        "endpoint": _endpoint(transport_type),
    }


def _transport_type() -> TransportType:
    cfg = get_config()
    if cfg.transport == "stdio":
        return "stdio"
    if cfg.transport == "sse" and cfg.legacy_sse:
        return "sse"
    return "streamable-http"


def _endpoint(transport_type: TransportType | None = None) -> str | None:
    cfg = get_config()
    selected_transport = transport_type or _transport_type()
    if selected_transport == "stdio":
        return None
    host = _format_host_for_url(_advertised_host(cfg.host))
    return f"http://{host}:{cfg.port}{cfg.mount_path}"


def _diagnostics(*, cli_found: bool, live_diagnostics: tuple[str, ...]) -> list[str]:
    diagnostics: list[str] = []
    if not cli_found:
        diagnostics.append(
            "KiCad CLI is unavailable; file-backed DRC/ERC/export operations are disabled."
        )
    diagnostics.extend(live_diagnostics)
    return diagnostics


def _as_semver(version: str) -> str:
    parts = _SEMVER_NUMBER_RE.findall(version)
    if not parts:
        return "0.0.0"
    normalized = [*parts[:3], "0", "0"]
    return ".".join(normalized[:3])


def _cached_cli_discovery(cli_path: Path) -> _CliDiscovery:
    resolved = cli_path.expanduser().resolve(strict=False)
    try:
        mtime_ns: int | None = resolved.stat().st_mtime_ns
    except OSError:
        return _CliDiscovery(found=False, version=None, capabilities=None)

    key = (resolved, mtime_ns)
    cached = _CLI_DISCOVERY_CACHE.get(key)
    if cached is not None:
        return cached

    capabilities = get_cli_capabilities(resolved)
    discovered = _CliDiscovery(found=True, version=capabilities.version, capabilities=capabilities)
    _CLI_DISCOVERY_CACHE[key] = discovered
    return discovered


def _advertised_host(host: str) -> str:
    normalized = host.strip()
    if normalized in _BIND_ALL_HOSTS:
        return "127.0.0.1"
    return normalized


def _format_host_for_url(host: str) -> str:
    if host.startswith("[") and host.endswith("]"):
        return host
    if ":" in host:
        return f"[{host}]"
    return host


def _compatibility_range() -> dict[str, dict[str, str]]:
    matrix = compatibility_summary()
    products = cast(dict[str, object], matrix["products"])
    studio = cast(dict[str, object], products["kicad-studio"])
    mcp_pro = cast(dict[str, object], products["kicad-mcp-pro"])
    studio_range = cast(dict[str, str], studio["compatibleMcpPro"])
    extension_range = cast(dict[str, str], mcp_pro["compatibleExtension"])
    return {
        "kicadStudio": {
            "required": studio_range["required"],
            "recommended": studio_range["recommended"],
            "testedAgainst": studio_range["testedAgainst"],
        },
        "kicadMcpPro": {
            "required": extension_range["required"],
            "testedAgainst": extension_range["testedAgainst"],
        },
    }
