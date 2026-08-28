"""Studio-context payload + push client for the KiCad companion plugin (issue #157).

Stdlib only. ``build_studio_context`` maps a snapshot of KiCad's live GUI state
(:class:`BoardInfo`) onto the ``studio_push_context`` tool arguments, and
:class:`StudioContextClient` posts a JSON-RPC ``tools/call`` to a running
kicad-mcp-pro server's HTTP endpoint. The networking opener is injectable so the whole
flow is unit-testable without KiCad or a live server.
"""

from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast

# Mutating operations a companion plugin must guard behind a safe-apply dialog
# before they touch the board.
SAFE_APPLY_ACTIONS = frozenset(
    {
        "apply_patch",
        "move_footprint",
        "delete_object",
        "edit_track",
        "edit_zone",
        "run_autoroute",
    }
)


def requires_confirmation(action: str) -> bool:
    """Return whether ``action`` must be confirmed before it mutates the board."""
    return action in SAFE_APPLY_ACTIONS


CompanionHealthState = Literal[
    "ready",
    "backend_unreachable",
    "backend_unhealthy",
    "backend_incompatible",
    "authentication_required",
    "runtime_unavailable",
]


@dataclass(frozen=True, slots=True)
class CompanionHealthStatus:
    """Closed, user-safe companion/backend readiness state."""

    state: CompanionHealthState
    message: str
    backend_version: str = ""


_SEMVER_TRIPLET = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_COMPATIBILITY_SCHEMA = "kicad-mcp-companion-compat.v1"


def _version_triplet(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = _SEMVER_TRIPLET.fullmatch(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def backend_version_is_compatible(
    backend_version: str,
    compatibility: dict[str, object],
) -> bool:
    """Return whether a backend version satisfies the closed companion contract."""
    if compatibility.get("schema_version") != _COMPATIBILITY_SCHEMA:
        return False
    backend = compatibility.get("backend")
    if not isinstance(backend, dict):
        return False
    current = _version_triplet(backend_version)
    minimum = _version_triplet(backend.get("minimum"))
    maximum = _version_triplet(backend.get("maximum_exclusive"))
    if current is None or minimum is None or maximum is None or minimum >= maximum:
        return False
    return minimum <= current < maximum


def load_compatibility_contract(path: Path | None = None) -> dict[str, object]:
    """Load and validate the packaged companion compatibility contract."""
    source = path or Path(__file__).with_name("compatibility.json")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Companion compatibility metadata is missing or invalid.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != _COMPATIBILITY_SCHEMA:
        raise ValueError("Companion compatibility metadata uses an unsupported schema.")
    plugin_version = _version_triplet(payload.get("plugin_version"))
    backend = payload.get("backend")
    kicad = payload.get("kicad")
    if plugin_version is None or not isinstance(backend, dict) or not isinstance(kicad, dict):
        raise ValueError("Companion compatibility metadata is incomplete.")
    minimum = _version_triplet(backend.get("minimum"))
    maximum = _version_triplet(backend.get("maximum_exclusive"))
    if minimum is None or maximum is None or minimum >= maximum:
        raise ValueError("Companion compatibility backend range is invalid.")
    if kicad.get("runtime") not in {"swig", "ipc"}:
        raise ValueError("Companion compatibility runtime is invalid.")
    return cast(dict[str, object], payload)


def classify_backend_health(
    payload: object,
    compatibility: dict[str, object],
) -> CompanionHealthStatus:
    """Classify one sanitized ``/api/health`` payload without side effects."""
    if not isinstance(payload, dict):
        return CompanionHealthStatus("backend_unhealthy", "Backend health response is invalid.")
    backend_version = payload.get("version")
    version_text = backend_version if isinstance(backend_version, str) else ""
    if payload.get("ok") is not True:
        return CompanionHealthStatus(
            "backend_unhealthy",
            "KiCad MCP Pro backend is not healthy; run kicad-mcp-pro doctor.",
            version_text,
        )
    runtime = payload.get("kicadRuntime")
    if isinstance(runtime, dict) and runtime.get("available") is False:
        return CompanionHealthStatus(
            "runtime_unavailable",
            "Backend is healthy but the required KiCad runtime capability is unavailable.",
            version_text,
        )
    if not backend_version_is_compatible(version_text, compatibility):
        return CompanionHealthStatus(
            "backend_incompatible",
            "Backend version is incompatible with this KiCad companion release.",
            version_text,
        )
    return CompanionHealthStatus("ready", "Backend is healthy and compatible.", version_text)


@dataclass(frozen=True, slots=True)
class BoardInfo:
    """Snapshot of the live KiCad document the plugin can read without mutating it."""

    file_name: str = ""
    file_type: str = "pcb"
    project_root: str = ""
    project_file: str = ""
    selected_reference: str = ""
    selected_net: str = ""
    cursor: tuple[float, float] | None = None
    drc_errors: tuple[str, ...] = field(default_factory=tuple)


def build_studio_context(info: BoardInfo) -> dict[str, Any]:
    """Map a :class:`BoardInfo` onto ``studio_push_context`` tool arguments."""

    file_type = info.file_type if info.file_type in {"schematic", "pcb", "other"} else "other"
    snapshot: dict[str, Any] = {}
    if info.project_root:
        snapshot["projectRoot"] = info.project_root
    if info.project_file:
        snapshot["projectFile"] = info.project_file

    arguments: dict[str, Any] = {"file_type": file_type}
    if info.file_name:
        arguments["active_file"] = info.file_name
    if info.selected_reference:
        arguments["selected_reference"] = info.selected_reference
    if info.selected_net:
        arguments["selected_net"] = info.selected_net
    if info.cursor is not None:
        arguments["cursor_position"] = {"x": info.cursor[0], "y": info.cursor[1]}
    if info.drc_errors:
        arguments["drc_errors"] = list(info.drc_errors)
    if snapshot:
        arguments["snapshot"] = snapshot
    return arguments


class _HttpResponse(Protocol):
    """Minimal response surface the client needs from an opener."""

    def read(self) -> bytes | str: ...

    def close(self) -> None: ...


Opener = Callable[[urllib.request.Request], _HttpResponse]


def _is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_loopback_base_url(base_url: str) -> None:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not _is_loopback_host(parsed.hostname):
        raise ValueError("KiCad companion can only connect to a loopback http(s) MCP endpoint.")


def _mcp_tool_error_message(payload: object) -> str | None:
    """Return a user-facing MCP tool error message, or ``None`` for success."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or result.get("isError") is not True:
        return None
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return "MCP tool call failed."


class StudioContextClient:
    """Minimal JSON-RPC client that pushes context to a running kicad-mcp-pro server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3334",
        mount_path: str = "/mcp",
        *,
        auth_token: str = "",
        timeout: float = 5.0,
        opener: Opener | None = None,
    ) -> None:
        _validate_loopback_base_url(base_url)
        self._base_url = base_url.rstrip("/")
        self._url = f"{self._base_url}/{mount_path.strip('/')}"
        self._health_url = f"{self._base_url}/api/health"
        self._auth_token = auth_token
        self._timeout = timeout
        self._opener = opener or self._default_opener

    def _default_opener(self, request: urllib.request.Request) -> _HttpResponse:
        # urlopen is typed to return Any-ish; localhost-only call, narrow to our Protocol.
        return cast(
            _HttpResponse,
            urllib.request.urlopen(  # noqa: S310  # nosec B310
                request,
                timeout=self._timeout,
            ),
        )

    def health(self, compatibility: dict[str, object]) -> CompanionHealthStatus:
        """Read the loopback backend health endpoint and classify readiness."""
        request = urllib.request.Request(  # noqa: S310 - validated loopback http(s) endpoint
            self._health_url,
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            response = self._opener(request)
            try:
                raw = response.read()
            finally:
                response.close()
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return CompanionHealthStatus(
                    "authentication_required",
                    "Backend health requires authentication or local access configuration.",
                )
            return CompanionHealthStatus(
                "backend_unhealthy",
                f"Backend health request failed with HTTP {exc.code}.",
            )
        except OSError:
            return CompanionHealthStatus(
                "backend_unreachable",
                "KiCad MCP Pro backend is not reachable on the configured loopback address.",
            )
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw) if raw else None
        except (UnicodeError, json.JSONDecodeError):
            return CompanionHealthStatus(
                "backend_unhealthy",
                "Backend health response could not be decoded.",
            )
        return classify_backend_health(payload, compatibility)

    def build_tool_call_body(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        request_id: int = 1,
    ) -> dict[str, Any]:
        """Return the JSON-RPC body for a generic MCP ``tools/call`` request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
        }

    def build_request_body(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return the JSON-RPC body for a ``studio_push_context`` tools/call."""
        return self.build_tool_call_body("studio_push_context", arguments)

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST a MCP tool call to the server and return the decoded JSON response."""
        body = json.dumps(self.build_tool_call_body(tool_name, arguments)).encode("utf-8")
        # MCP Streamable HTTP requires the client to accept both JSON and SSE; a
        # JSON-only Accept header is rejected with HTTP 400 by the transport.
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        request = urllib.request.Request(  # noqa: S310 - fixed loopback http(s) endpoint
            self._url, data=body, headers=headers, method="POST"
        )
        response = self._opener(request)
        try:
            raw = response.read()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw) if raw else {}
            error_message = _mcp_tool_error_message(payload)
            if error_message is not None:
                raise RuntimeError(error_message)
            return payload
        finally:
            response.close()

    def push(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """POST the context to the server and return the decoded JSON response."""
        return self.call_tool("studio_push_context", arguments)

    def request_render_artifact(
        self,
        *,
        sheet: str = "",
        output_file: str = "",
    ) -> dict[str, Any]:
        """Ask the server to render a schematic PNG artifact for visual QA."""
        args = {
            key: value
            for key, value in {"sheet": sheet, "output_file": output_file}.items()
            if value
        }
        return self.call_tool("sch_render_png", args)

    def request_highlight_net(self, net_name: str) -> dict[str, Any]:
        """Ask the server to highlight or identify a PCB net when the runtime supports it."""
        return self.call_tool("pcb_highlight_net", {"net_name": net_name})
