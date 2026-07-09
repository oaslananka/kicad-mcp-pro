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
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

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
        self._url = f"{base_url.rstrip('/')}/{mount_path.strip('/')}"
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
            return json.loads(raw) if raw else {}
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
