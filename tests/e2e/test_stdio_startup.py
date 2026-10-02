from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

from kicad_mcp.compatibility import MCP_LEGACY_PROTOCOL_VERSION

STDIO_STARTUP_TIMEOUT_SECONDS = 10.0


def test_stdio_initialize_does_not_require_client_warmup() -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("KICAD_MCP_")}
    env["KICAD_MCP_LOG_LEVEL"] = "ERROR"
    env["KICAD_MCP_LOG_FORMAT"] = "json"
    env["KICAD_MCP_KICAD_CLI"] = "kicad-cli-missing-for-stdio-startup-test"
    env["KICAD_MCP_OPERATING_MODE"] = "experimental"
    env["KICAD_MCP_TRANSPORT"] = "stdio"

    started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, "-m", "kicad_mcp.server", "--profile", "full"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    stdout: queue.Queue[str] = queue.Queue()
    threading.Thread(
        target=lambda: [stdout.put(line) for line in iter(process.stdout.readline, "")],
        daemon=True,
    ).start()

    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_LEGACY_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "stdio-startup-test", "version": "0"},
        },
    }
    process.stdin.write(json.dumps(initialize) + "\n")
    process.stdin.flush()

    try:
        line = stdout.get(timeout=STDIO_STARTUP_TIMEOUT_SECONDS)
        elapsed = time.perf_counter() - started
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        process.stdin.write(json.dumps(initialized) + "\n")
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
        )
        process.stdin.flush()
        tools_line = stdout.get(timeout=6.0)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()

    payload = json.loads(line)
    assert payload["id"] == 1
    assert "serverInfo" in payload["result"]
    assert elapsed < STDIO_STARTUP_TIMEOUT_SECONDS

    tools_payload = json.loads(tools_line)
    tool_names = {tool["name"] for tool in tools_payload["result"]["tools"]}
    assert tools_payload["id"] == 2
    assert "kicad_get_version" in tool_names
    assert len(tool_names) > 200
