"""Version-gated KiCad IPC capability matrix."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from ..errors import KiCadMcpError
from .client import KiCadIpcClient
from .discovery import KiCadIpcDiscovery, KiCadIpcEndpoint

BackendName = Literal["kicad-ipc", "kicad-ipc-headless", "hybrid-file-ipc"]

# KiCad 11 introduced `kicad-cli api-server` (headless IPC) — no GUI required.
# This constant guards version-branching so domain logic stays channel-agnostic.
KICAD_11_HEADLESS_IPC_MIN_VERSION: int = 11

REQUIRED_LIVE_EDITING_TOOLS = frozenset(
    {
        "pcb_place_component",
        "pcb_route_trace",
        "pcb_add_zone",
        "pcb_set_design_rules",
        "pcb_move_component",
        "pcb_delete_object",
        "sch_add_component",
        "sch_add_wire",
        "sch_modify_property",
    }
)

PCB_LIVE_EDITING_TOOLS = frozenset(
    {
        "pcb_place_component",
        "pcb_route_trace",
        "pcb_add_zone",
        "pcb_set_design_rules",
        "pcb_move_component",
        "pcb_delete_object",
    }
)
SCHEMATIC_LIVE_EDITING_TOOLS = REQUIRED_LIVE_EDITING_TOOLS - PCB_LIVE_EDITING_TOOLS
_VERSION_RE = re.compile(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?")


class CapabilityConfig(Protocol):
    kicad_socket_path: Path | None
    kicad_token: str | None
    ipc_connection_timeout: float
    headless: bool


ConfigFactory = Callable[[], CapabilityConfig]


class CapabilityClient(Protocol):
    def probe(self) -> Mapping[str, object]:
        """Return IPC probe data."""
        ...

    def board(self) -> object:
        """Return the active board."""
        ...

    def has_open_schematic(self) -> bool:
        """Return whether a schematic document is open."""
        ...


@dataclass(frozen=True)
class KiCadIpcOperationState:
    """Availability for a single live editing operation."""

    name: str
    available: bool
    backend: BackendName
    reason: str | None
    minimum_kicad_major: int

    def to_contract(self) -> dict[str, object]:
        """Return JSON-serializable server-info payload."""
        return {
            "available": self.available,
            "backend": self.backend,
            "reason": self.reason,
            "minimumKiCadMajor": self.minimum_kicad_major,
        }


@dataclass(frozen=True)
class KiCadIpcCapabilityState:
    """Resolved KiCad IPC capability state."""

    endpoint: KiCadIpcEndpoint
    reachable: bool
    version: str | None
    api_version: str | None
    major_version: int | None
    live_pcb_context: bool
    live_schematic_context: bool
    headless_requested: bool
    operations: Mapping[str, KiCadIpcOperationState]
    diagnostics: tuple[str, ...]

    @property
    def headless_ipc_available(self) -> bool:
        """Whether KiCad 11+ headless IPC (kicad-cli api-server) is available.

        KiCad 11 introduced a headless IPC mode that does not require a running
        KiCad GUI — it exposes the same API via ``kicad-cli api-server``. When this
        is True, domain logic can rely on IPC without requiring ``live_pcb_context``.
        """
        return (
            self.reachable
            and self.headless_requested
            and _major_at_least(self.major_version, KICAD_11_HEADLESS_IPC_MIN_VERSION)
        )

    @property
    def live_pcb_read(self) -> bool:
        """Whether live PCB reads can use the KiCad IPC API.

        Returns True if the GUI has an open board (KiCad 9/10) OR if headless IPC
        is available (KiCad 11+, no GUI required).
        """
        gui_path = (
            self.reachable and self.live_pcb_context and _major_at_least(self.major_version, 9)
        )
        return gui_path or self.headless_ipc_available

    @property
    def live_pcb_write(self) -> bool:
        """Whether live PCB writes can use the KiCad IPC API."""
        return self.live_pcb_read

    @property
    def live_schematic_read(self) -> bool:
        """Whether live schematic context is visible through KiCad IPC.

        Returns True if the GUI has an open schematic (KiCad 10+) OR if headless
        IPC is available (KiCad 11+).
        """
        gui_path = (
            self.reachable
            and self.live_schematic_context
            and _major_at_least(self.major_version, 10)
        )
        return gui_path or self.headless_ipc_available

    @property
    def live_schematic_write(self) -> bool:
        """Whether schematic writes can use the hybrid file-backed IPC reload path."""
        return self.live_schematic_read

    def ipc_backend(self) -> BackendName:
        """Return the active IPC backend identifier for telemetry and diagnostics."""
        if self.headless_ipc_available:
            return "kicad-ipc-headless"
        return "kicad-ipc"

    def tool_available(self, tool_name: str) -> bool:
        """Return whether a required live editing tool is available."""
        operation = self.operations.get(tool_name)
        return bool(operation and operation.available)

    def available_live_tools(self) -> frozenset[str]:
        """Return all available OASLANA-119 live editing tools."""
        return frozenset(name for name, state in self.operations.items() if state.available)

    def live_editing_contract(self) -> dict[str, dict[str, object]]:
        """Return server-info contract payload for live editing tools."""
        return {name: self.operations[name].to_contract() for name in sorted(self.operations)}


def _default_config() -> CapabilityConfig:
    from ..config import get_config

    return get_config()


def get_ipc_capability_state(
    *,
    client: CapabilityClient | None = None,
    config_factory: ConfigFactory = _default_config,
    probe_live_context: bool = True,
    fallback_version: str | None = None,
) -> KiCadIpcCapabilityState:
    """Probe KiCad IPC and return a version-gated live operation matrix."""
    cfg = config_factory()
    endpoint = KiCadIpcDiscovery(config_factory=lambda: cfg).discover()
    headless_requested = bool(cfg.headless)
    if not probe_live_context:
        return _unavailable_state(
            endpoint,
            version=None,
            api_version=None,
            diagnostic=None,
            headless_requested=headless_requested,
        )

    active_client = client or KiCadIpcClient()
    try:
        probe = active_client.probe()
    except KiCadMcpError as exc:
        return _unavailable_state(
            endpoint,
            version=None,
            api_version=None,
            diagnostic=f"KiCad IPC is unavailable: {_first_line(exc)}",
            headless_requested=headless_requested,
        )
    except Exception as exc:  # pragma: no cover - defensive IPC boundary
        return _unavailable_state(
            endpoint,
            version=None,
            api_version=None,
            diagnostic=f"KiCad IPC probe failed: {_first_line(exc)}",
            headless_requested=headless_requested,
        )

    version = _string_or_none(probe.get("version")) or fallback_version
    api_version = _string_or_none(probe.get("apiVersion"))
    major_version = _parse_major(version) or _parse_major(api_version)
    if not bool(probe.get("connected", True)):
        return _unavailable_state(
            endpoint,
            version=version,
            api_version=api_version,
            diagnostic="KiCad IPC is unavailable: probe reported disconnected.",
            headless_requested=headless_requested,
        )

    live_pcb_context = False
    diagnostics: list[str] = []
    try:
        active_client.board()
        live_pcb_context = True
    except KiCadMcpError as exc:
        diagnostics.append(f"Live KiCad PCB context is unavailable: {_first_line(exc)}")
    except Exception as exc:  # pragma: no cover - defensive IPC boundary
        diagnostics.append(f"Live KiCad PCB context probe failed: {_first_line(exc)}")

    live_schematic_context = False
    if _major_at_least(major_version, 10):
        try:
            live_schematic_context = active_client.has_open_schematic()
        except KiCadMcpError as exc:
            diagnostics.append(f"Live KiCad schematic context is unavailable: {_first_line(exc)}")
        except Exception as exc:  # pragma: no cover - defensive IPC boundary
            diagnostics.append(f"Live KiCad schematic context probe failed: {_first_line(exc)}")

    operations = _operation_states(
        reachable=True,
        major_version=major_version,
        live_pcb_context=live_pcb_context,
        live_schematic_context=live_schematic_context,
        headless_requested=headless_requested,
    )
    return KiCadIpcCapabilityState(
        endpoint=endpoint,
        reachable=True,
        version=version,
        api_version=api_version,
        major_version=major_version,
        live_pcb_context=live_pcb_context,
        live_schematic_context=live_schematic_context,
        headless_requested=headless_requested,
        operations=operations,
        diagnostics=tuple(diagnostics),
    )


def _unavailable_state(
    endpoint: KiCadIpcEndpoint,
    *,
    version: str | None,
    api_version: str | None,
    diagnostic: str | None,
    headless_requested: bool,
) -> KiCadIpcCapabilityState:
    operations = _operation_states(
        reachable=False,
        major_version=_parse_major(version) or _parse_major(api_version),
        live_pcb_context=False,
        live_schematic_context=False,
        headless_requested=headless_requested,
    )
    return KiCadIpcCapabilityState(
        endpoint=endpoint,
        reachable=False,
        version=version,
        api_version=api_version,
        major_version=_parse_major(version) or _parse_major(api_version),
        live_pcb_context=False,
        live_schematic_context=False,
        headless_requested=headless_requested,
        operations=operations,
        diagnostics=(diagnostic,) if diagnostic else (),
    )


def _operation_states(
    *,
    reachable: bool,
    major_version: int | None,
    live_pcb_context: bool,
    live_schematic_context: bool,
    headless_requested: bool = False,
) -> dict[str, KiCadIpcOperationState]:
    headless = (
        reachable
        and headless_requested
        and _major_at_least(major_version, KICAD_11_HEADLESS_IPC_MIN_VERSION)
    )
    states: dict[str, KiCadIpcOperationState] = {}
    for tool_name in sorted(PCB_LIVE_EDITING_TOOLS):
        available = headless or (
            reachable and live_pcb_context and _major_at_least(major_version, 9)
        )
        if tool_name == "pcb_set_design_rules":
            backend: BackendName = "hybrid-file-ipc"
        elif headless:
            backend = "kicad-ipc-headless"
        else:
            backend = "kicad-ipc"
        states[tool_name] = KiCadIpcOperationState(
            name=tool_name,
            available=available,
            backend=backend,
            reason=None
            if available
            else _reason(
                reachable=reachable,
                major_version=major_version,
                context_available=live_pcb_context,
                context_name="PCB",
                minimum_major=10,
            ),
            minimum_kicad_major=10,
        )
    for tool_name in sorted(SCHEMATIC_LIVE_EDITING_TOOLS):
        available = headless or (
            reachable and live_schematic_context and _major_at_least(major_version, 10)
        )
        states[tool_name] = KiCadIpcOperationState(
            name=tool_name,
            available=available,
            backend="kicad-ipc-headless" if headless else "hybrid-file-ipc",
            reason=None
            if available
            else _reason(
                reachable=reachable,
                major_version=major_version,
                context_available=live_schematic_context,
                context_name="schematic",
                minimum_major=10,
            ),
            minimum_kicad_major=10,
        )
    return states


def _reason(
    *,
    reachable: bool,
    major_version: int | None,
    context_available: bool,
    context_name: str,
    minimum_major: int,
) -> str:
    if not reachable:
        return "KiCad IPC is unavailable."
    if not _major_at_least(major_version, minimum_major):
        return f"Live {context_name} writes require KiCad {minimum_major}+."
    if not context_available:
        return (
            f"Live {context_name} writes require KiCad {minimum_major}+ with "
            f"an open {context_name} document."
        )
    return "Operation is unavailable for the current KiCad IPC state."


def _parse_major(version: str | None) -> int | None:
    if not version:
        return None
    match = _VERSION_RE.search(version)
    if match is None:
        return None
    return int(match.group(1))


def _major_at_least(major_version: int | None, minimum: int) -> bool:
    return major_version is not None and major_version >= minimum


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _first_line(exc: BaseException) -> str:
    return str(exc).splitlines()[0] or exc.__class__.__name__
