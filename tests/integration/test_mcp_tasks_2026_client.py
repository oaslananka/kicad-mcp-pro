"""Real independent Tasks 2026 requester over disposable loopback JSON-RPC.

Uses official @modelcontextprotocol/ext-tasks with a test-only HTTP adapter.
No production MCP, KiCad runtime, filesystem project, queue or cloud endpoint.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import anyio
import httpx
import pytest

from tests.research.mcp_tasks_http_probe import TaskProbeServer

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "tests/research/mcp_tasks_client_2026.mjs"
PACKAGE = ROOT / "node_modules/@modelcontextprotocol/ext-tasks/package.json"


@contextmanager
def probe_server(mode: str) -> Iterator[TaskProbeServer]:
    server = TaskProbeServer(mode=mode)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def require_independent_client() -> str:
    node = shutil.which("node")
    if node is None or not PACKAGE.is_file():
        if os.environ.get("MCP_TASKS_REAL_CLIENT_REQUIRED") == "1":
            pytest.fail("Pinned independent 2026 Tasks client is required in this CI lane")
        pytest.skip("Pinned Node Tasks client not installed in this optional Python-only lane")
    assert json.loads(PACKAGE.read_text(encoding="utf-8"))["version"] == "0.2.3"
    return node


@pytest.mark.parametrize("mode", ["complete", "toolerror", "input", "cancel", "sync", "expired"])
def test_pinned_external_requester_exchanges_real_http_messages(mode: str) -> None:
    require_independent_client()
    with probe_server(mode) as server:

        async def invoke_client() -> tuple[int, str, str]:
            with anyio.fail_after(25):
                finished = await anyio.run_process(
                    ["node", "tests/research/mcp_tasks_client_2026.mjs"],
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "MCP_TASKS_TEST_TOKEN": server.tokens["client-a"],
                        "MCP_TASKS_TEST_ENDPOINT": server.url,
                        "MCP_TASKS_TEST_MODE": mode,
                    },
                    check=False,
                )
            return (
                finished.returncode,
                finished.stdout.decode("utf-8"),
                finished.stderr.decode("utf-8"),
            )

        code, stdout, stderr = anyio.run(invoke_client)
        assert code == 0, f"{mode}: {stderr[:1200]}"
        report = json.loads(stdout)
        assert report["mode"] == mode
        assert report["result"] == "PASS"
        assert all(record["caller"] == "client-a" for record in server.log)
        assert all(record["header_matches"] for record in server.log)
        if mode == "sync":
            assert not any(
                isinstance(record["method"], str) and record["method"].startswith("tasks/")
                for record in server.log
            )
            assert server.fixture.retained_count == 0
        elif mode != "expired":
            assert any(
                isinstance(record["method"], str) and record["method"].startswith("tasks/")
                for record in server.log
            )


def test_test_only_http_transport_rejects_unauthenticated_and_wrong_task_headers() -> None:
    with probe_server("cancel") as server:
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "synthetic_erc_review",
                "arguments": {},
                "_meta": {
                    "io.modelcontextprotocol/clientCapabilities": {
                        "extensions": {"io.modelcontextprotocol/tasks": {}}
                    }
                },
            },
        }
        headers = {"Mcp-Method": "tools/call", "Mcp-Name": "synthetic_erc_review"}
        with httpx.Client(timeout=5) as client:
            assert client.post(server.url, headers=headers, json=body).status_code == 401
            accepted = client.post(
                server.url,
                headers={
                    **headers,
                    "Authorization": f"Bearer {server.tokens['client-a']}",
                },
                json=body,
            )
            assert accepted.status_code == 200
            task_id = accepted.json()["result"]["taskId"]

            follow = {
                **body,
                "id": 2,
                "method": "tasks/get",
                "params": {
                    "taskId": task_id,
                    "_meta": body["params"]["_meta"],
                },
            }
            first = client.post(
                server.url,
                headers={
                    "Authorization": f"Bearer {server.tokens['client-b']}",
                    "Mcp-Method": "tasks/get",
                    "Mcp-Name": task_id,
                },
                json=follow,
            )
            assert first.status_code == 200
            assert first.json()["error"]["code"] == -32602
            assert task_id not in first.text

            mismatched = client.post(
                server.url,
                headers={
                    "Authorization": f"Bearer {server.tokens['client-a']}",
                    "Mcp-Method": "tasks/get",
                    "Mcp-Name": "wrong-handle",
                },
                json=follow,
            )
            assert mismatched.status_code == 400
            assert task_id not in mismatched.text
            correct = client.post(
                server.url,
                headers={
                    "Authorization": f"Bearer {server.tokens['client-a']}",
                    "Mcp-Method": "tasks/get",
                    "Mcp-Name": task_id,
                },
                json=follow,
            )
            assert correct.status_code == 200
            assert correct.json()["result"]["taskId"] == task_id


def test_loopback_capacity_and_request_size_are_bounded_under_parallel_clients() -> None:
    from concurrent.futures import ThreadPoolExecutor

    with probe_server("cancel") as server:
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "synthetic_drc_review",
                "arguments": {},
                "_meta": {
                    "io.modelcontextprotocol/clientCapabilities": {
                        "extensions": {"io.modelcontextprotocol/tasks": {}}
                    }
                },
            },
        }
        headers = {
            "Authorization": f"Bearer {server.tokens['client-a']}",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "synthetic_drc_review",
        }

        def submit(index: int) -> dict[str, Any]:
            response = httpx.post(
                server.url,
                headers=headers,
                json={**body, "id": index},
                timeout=5,
            )
            assert response.status_code == 200
            return cast(dict[str, Any], response.json())

        with ThreadPoolExecutor(max_workers=4) as pool:
            observed = list(pool.map(submit, range(12)))

        created = [r for r in observed if r.get("result", {}).get("resultType") == "task"]
        rejected = [r for r in observed if r.get("error", {}).get("code") == -32000]
        assert len(created) == 8
        assert len(rejected) == 4
        assert server.fixture.retained_count == 8
        assert len({r["result"]["taskId"] for r in created}) == 8

        oversized = httpx.post(
            server.url,
            headers=headers,
            content=b"x" * 4097,
            timeout=5,
        )
        assert oversized.status_code == 413
        assert server.fixture.retained_count == 8

        invalid = httpx.post(
            server.url,
            headers=headers,
            content=b"{",
            timeout=5,
        )
        assert invalid.status_code == 400
        assert server.fixture.retained_count == 8
