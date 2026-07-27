"""KiCad IPC endpoint discovery."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

EndpointSource = Literal["config", "environment", "default"]


class IpcDiscoveryConfig(Protocol):
    """Configuration protocol used by KiCadIpcDiscovery."""

    kicad_socket_path: str | Path | None
    kicad_token: str | None
    ipc_connection_timeout: float


ConfigFactory = Callable[[], IpcDiscoveryConfig]


@dataclass(frozen=True)
class KiCadIpcEndpoint:
    """Resolved KiCad IPC endpoint metadata."""

    socket_path: str | Path | None
    source: EndpointSource
    token_configured: bool
    timeout_ms: int


def _normalize_endpoint(value: str) -> str | Path:
    """Preserve URI endpoints and expand plain filesystem socket paths."""
    endpoint = value.strip()
    if "://" in endpoint:
        return endpoint
    return Path(endpoint).expanduser()


def _endpoints_equal(raw: str, configured: str | Path) -> bool:
    """Compare an environment endpoint with its normalized config value."""
    normalized = _normalize_endpoint(raw)
    return normalized == configured


def _default_config() -> IpcDiscoveryConfig:
    from ..config import get_config

    return get_config()


class KiCadIpcDiscovery:
    """Discover how the server should connect to the running KiCad IPC API."""

    def __init__(self, *, config_factory: ConfigFactory = _default_config) -> None:
        self._config_factory = config_factory

    def discover(self) -> KiCadIpcEndpoint:
        """Return configured, environment, or default KiCad IPC endpoint metadata."""
        cfg = self._config_factory()
        env_socket = os.environ.get("KICAD_API_SOCKET")
        if cfg.kicad_socket_path is not None:
            return KiCadIpcEndpoint(
                socket_path=cfg.kicad_socket_path,
                source="environment"
                if env_socket and _endpoints_equal(env_socket, cfg.kicad_socket_path)
                else "config",
                token_configured=bool(cfg.kicad_token),
                timeout_ms=int(cfg.ipc_connection_timeout * 1000),
            )

        if env_socket:
            return KiCadIpcEndpoint(
                socket_path=_normalize_endpoint(env_socket),
                source="environment",
                token_configured=bool(cfg.kicad_token or os.environ.get("KICAD_API_TOKEN")),
                timeout_ms=int(cfg.ipc_connection_timeout * 1000),
            )

        return KiCadIpcEndpoint(
            socket_path=None,
            source="default",
            token_configured=bool(cfg.kicad_token or os.environ.get("KICAD_API_TOKEN")),
            timeout_ms=int(cfg.ipc_connection_timeout * 1000),
        )
