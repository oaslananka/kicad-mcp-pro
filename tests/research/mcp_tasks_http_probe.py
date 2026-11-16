"""Loopback-only HTTP adapter for the isolated MCP Tasks synthetic research fixture.

Not imported by production code. Real HTTP requests exercise authentication,
routing headers and encoded JSON-RPC; no KiCad or durable task runner exists.
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tests.research.mcp_tasks_fixture import MAX_REQUEST_BYTES, TaskFixture


class ProbeClock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds


class TaskProbeServer(ThreadingHTTPServer):
    """An ephemeral fixture transport bound strictly to IPv4 loopback."""

    daemon_threads = True

    def __init__(self, *, mode: str) -> None:
        if mode not in {"complete", "toolerror", "input", "cancel", "sync", "expired"}:
            raise ValueError("Unsupported test-only scenario")
        self.mode = mode
        self.clock = ProbeClock()
        self.fixture = TaskFixture(self.clock)
        self.lock = threading.Lock()
        self.log: list[dict[str, object]] = []
        self.tokens = {
            "client-a": secrets.token_urlsafe(32),
            "client-b": secrets.token_urlsafe(32),
        }
        super().__init__(("127.0.0.1", 0), TaskProbeHandler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/mcp"

    def caller_for_token(self, header: str | None) -> str | None:
        candidate = header.removeprefix("Bearer ") if header else ""
        if not header or not header.startswith("Bearer "):
            return None
        for caller, expected in self.tokens.items():
            if hmac.compare_digest(candidate, expected):
                return caller
        return None

    def dispatch(self, message: dict[str, Any], caller: str) -> dict[str, Any]:
        """Progress is driven by the test scenario, never by a GET/poll."""
        with self.lock:
            reply = self.fixture.dispatch(message, caller=caller)
            method = message["method"]
            if method == "tools/call" and reply.get("result", {}).get("resultType") == "task":
                task_id = reply["result"]["taskId"]
                if self.mode in {"complete", "toolerror", "input"}:
                    self.fixture.advance(task_id=task_id, caller=caller)
                elif self.mode == "expired":
                    self.clock.seconds = 60.0
            elif method == "tasks/update" and self.mode == "input":
                self.fixture.advance(task_id=message["params"]["taskId"], caller=caller)
            return reply


class TaskProbeHandler(BaseHTTPRequestHandler):
    """A strict test-only endpoint with no listener outside loopback."""

    server: TaskProbeServer

    def _send(self, code: int, message: dict[str, Any]) -> None:
        encoded = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _reject(self, status: int, reason: str) -> None:
        self.close_connection = True
        self._send(
            status,
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32602, "message": reason}},
        )

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self._reject(404, "Not found")
            return
        caller = self.server.caller_for_token(self.headers.get("Authorization"))
        if caller is None:
            self._reject(401, "Unauthorized")
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            self._reject(400, "Invalid content length")
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._reject(413, "Invalid request size")
            return
        try:
            message = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, ValueError):
            self._reject(400, "Invalid JSON")
            return
        if not isinstance(message, dict):
            self._reject(400, "Invalid JSON-RPC envelope")
            return
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            self._reject(400, "Invalid JSON-RPC request")
            return
        if self.headers.get("Mcp-Method") != method:
            self._reject(400, "Invalid routing headers")
            return
        name = self.headers.get("Mcp-Name")
        if method.startswith("tasks/"):
            if not isinstance(params.get("taskId"), str) or name != params["taskId"]:
                self._reject(400, "Invalid routing headers")
                return
        elif method == "tools/call" and name != params.get("name"):
            self._reject(400, "Invalid routing headers")
            return
        with self.server.lock:
            self.server.log.append({"method": method, "caller": caller, "header_matches": True})
        response = self.server.dispatch(message, caller)
        self._send(200, response)
