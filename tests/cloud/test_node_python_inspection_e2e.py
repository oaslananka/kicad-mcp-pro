"""Real Node Cloud WSS + PostgreSQL grants + Python KiCad worker, all localhost.

An explicit TEST_DATABASE_URL fixture opt-in is required. Never connect this
test to a production or shared database. The Node fixture creates an isolated
schema and deletes it after the test.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from test_isolated_tls_websocket_handshake import _synthetic_tls

from kicad_mcp.cloud_outbound_handshake import (
    execute_operator_board_counts_once,
    execute_operator_inspection_once,
    execute_operator_schematic_counts_once,
)
from kicad_mcp.cloud_project_worker_bridge import BoundConnectorProjectWorker
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps" / "cloud"
PEER = APP / "test" / "inspection-python.fixture.ts"
TSX = APP / "node_modules" / ".bin" / "tsx"


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["inspection", "board_counts", "schematic_counts"])
async def test_real_node_cloud_python_signed_wss_project_inspection(
    tmp_path: Path, mode: str
) -> None:
    raw_db = os.environ.get("TEST_DATABASE_URL")
    if not raw_db:
        pytest.skip("Disposable TEST_DATABASE_URL required for cross-language integration")
    database = urlsplit(raw_db)
    if database.scheme not in {"postgres", "postgresql"} or database.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        pytest.fail("Cross-language fixture requires a loopback PostgreSQL database")
    if not TSX.is_file():
        pytest.skip("Local Cloud Node dependencies unavailable")
    tls_server, pem = _synthetic_tls(tmp_path)
    del tls_server  # The Node HTTPS server reads the cert and key from the fixture paths.
    signer = Ed25519PrivateKey.generate()
    key = tmp_path / "device-signing.key"
    key.write_bytes(
        signer.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key.chmod(0o600)
    project_dir = tmp_path / "private-design"
    project_dir.mkdir()
    (project_dir / "board.kicad_pro").write_text('{"private":"DESIGN_NOT_FOR_CLOUD"}')
    if mode in {"board_counts", "schematic_counts"}:
        from shutil import copyfile

        ext = "kicad_pcb" if mode == "board_counts" else "kicad_sch"
        source = ROOT / f"tests/fixtures/benchmark_projects/pass_minimal_mcu_board/demo.{ext}"
        copyfile(source, project_dir / f"board.{ext}")
    cert_file = tmp_path / "temporary-test-server.crt"
    tls_key = tmp_path / "temporary-test-server.key"
    peer = await asyncio.create_subprocess_exec(
        str(TSX),
        str(PEER),
        str(cert_file),
        str(tls_key),
        str(key),
        cwd=str(APP),
        env={**os.environ, "TEST_CONNECTOR_OPERATION": mode},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert peer.stdout is not None
        raw = await asyncio.wait_for(peer.stdout.readline(), timeout=25)
        if not raw:
            raise AssertionError(f"Cloud peer exited before TLS readiness: {peer.returncode}")
        readiness = json.loads(raw)
        assert readiness["origin"].startswith("https://localhost:")
        context = ssl.create_default_context(cadata=pem)
        expires = __import__("time").time_ns() // 1_000_000 + 40_000

        def factory(receipt):
            return BoundConnectorProjectWorker(
                verified=VerifiedLocalBinding(
                    device_id=receipt.device_id,
                    project_id=readiness["project"],
                    operations=frozenset(
                        {
                            "project_board_counts"
                            if mode == "board_counts"
                            else "project_schematic_counts"
                            if mode == "schematic_counts"
                            else "project_worker_inspection"
                        }
                    ),
                    session_id=receipt.session_id,
                    session_expires_unix_ms=expires,
                ),
                operator_project=OperatorProject(
                    device_id=receipt.device_id,
                    project_id=readiness["project"],
                    directory=project_dir,
                    filename_stem="board",
                ),
                current_authorization=lambda: True,
            )

        async with asyncio.TaskGroup() as tasks:
            outbound = tasks.create_task(
                (
                    execute_operator_board_counts_once
                    if mode == "board_counts"
                    else execute_operator_schematic_counts_once
                    if mode == "schematic_counts"
                    else execute_operator_inspection_once
                )(
                    origin=readiness["origin"],
                    trusted_origin=readiness["origin"],
                    owner_sub=readiness["owner"],
                    device_id=readiness["device"],
                    signing_key=signer,
                    tls_context=context,
                    inspector_factory=factory,
                )
            )
            ready = json.loads(await asyncio.wait_for(peer.stdout.readline(), timeout=25))
            assert ready == {"connectorReady": True}
            # A correctly signed JWT for a different owner must not consume
            # the bound project's one-shot worker session.
            async with (
                httpx2.AsyncClient(
                    verify=context,
                    headers={"Authorization": "Bearer " + readiness["foreignJwt"]},
                    timeout=15.0,
                ) as outsider_http,
                streamable_http_client(
                    readiness["origin"] + "/mcp", http_client=outsider_http
                ) as outsider_streams,
                ClientSession(*outsider_streams) as outsider,
            ):
                await outsider.initialize()
                foreign = await outsider.call_tool(
                    "get_project_engine_status", {"project_id": readiness["project"]}
                )
                assert foreign.structured_content == {
                    "available": False,
                    "selectionRequired": False,
                }
            # This is an actual, unmodified Python MCP SDK client over the
            # real Cloud HTTP path, not an ad-hoc JSON-RPC test request.
            async with (
                httpx2.AsyncClient(
                    verify=context,
                    headers={"Authorization": "Bearer " + readiness["jwt"]},
                    timeout=25.0,
                ) as http,
                streamable_http_client(readiness["origin"] + "/mcp", http_client=http) as streams,
                ClientSession(*streams) as mcp,
            ):
                await mcp.initialize()
                available = await mcp.list_tools()
                names = {tool.name for tool in available.tools}
                assert "discover_project_workflow" in names
                assert "get_project_engine_status" in names
                assert "get_project_board_counts" in names
                assert "get_project_schematic_counts" in names
                assert "get_project_drc_counts" not in names
                assert "kicad_set_project" not in names
                board_guide = await mcp.call_tool(
                    "discover_project_workflow",
                    {"task": "inspect_board", "project_id": readiness["project"]},
                )
                assert board_guide.structured_content["tools"] == ["get_project_board_counts"]
                schematic_guide = await mcp.call_tool(
                    "discover_project_workflow",
                    {"task": "inspect_schematic", "project_id": readiness["project"]},
                )
                assert schematic_guide.structured_content["tools"] == [
                    "get_project_schematic_counts"
                ]
                guide = await mcp.call_tool(
                    "discover_project_workflow",
                    {"task": "inspect_engine", "project_id": readiness["project"]},
                )
                assert guide.structured_content == {
                    "available": True,
                    "selectionRequired": False,
                    "tools": ["get_project_engine_status"],
                    "requiresOwnerSession": True,
                }
                unexposed = await mcp.call_tool(
                    "discover_project_workflow",
                    {"task": "check_board_drc", "project_id": readiness["project"]},
                )
                assert unexposed.structured_content == {
                    "available": False,
                    "selectionRequired": False,
                    "tools": [],
                    "reason": "cloud_operation_not_enabled",
                }
                # A cloud caller cannot switch the local KiCad project, even
                # by asking for a hidden local-only tool by exact name.
                with pytest.raises(MCPError, match="not found"):
                    await mcp.call_tool(
                        "kicad_set_project", {"project_dir": str(tmp_path / "different")}
                    )
                response = await mcp.call_tool(
                    "get_project_board_counts"
                    if mode == "board_counts"
                    else "get_project_schematic_counts"
                    if mode == "schematic_counts"
                    else "get_project_engine_status",
                    {"project_id": readiness["project"]},
                    read_timeout_seconds=22,
                )
                assert response.is_error is not True
                assert response.structured_content is not None
                assert response.structured_content["available"] is True
                if mode == "schematic_counts":
                    counts = response.structured_content["counts"]
                    assert counts == {"components": 2, "populated": 2, "dnp": 0, "inBom": 2}
                elif mode == "board_counts":
                    board = response.structured_content["board"]
                    assert board["source"] == "file-backed"
                    assert set(board) == {
                        "source",
                        "tracks",
                        "vias",
                        "footprints",
                        "zones",
                        "nets",
                        "shapes",
                    }
                    assert board["footprints"] >= 1
                    assert all(
                        type(v) is int and v >= 0 for key, v in board.items() if key != "source"
                    )
                else:
                    status = response.structured_content["status"]
                    assert isinstance(status["engineVersion"], str)
                    assert type(status["cliAvailable"]) is bool
                    assert type(status["ipcAvailable"]) is bool
                    caps = status["capabilities"]
                    assert set(caps) == {
                        "fileBackedDrc",
                        "fileBackedErc",
                        "livePcbRead",
                        "liveSchematicRead",
                    }
                    assert all(type(value) is bool for value in caps.values())
                    assert "cliPath" not in str(status)
                assert "DESIGN_NOT_FOR_CLOUD" not in str(response.structured_content)
                assert str(project_dir) not in str(response.structured_content)
                assert "cliPath" not in str(response.structured_content)
            receipt = await asyncio.wait_for(outbound, timeout=10)
            assert receipt.device_id == readiness["device"]
        assert peer.stdin is not None
        peer.stdin.write(b"done\n")
        await peer.stdin.drain()
        await asyncio.wait_for(peer.wait(), timeout=14)
        assert peer.returncode == 0
    finally:
        if peer.returncode is None:
            peer.terminate()
            try:
                await asyncio.wait_for(peer.wait(), timeout=5)
            except TimeoutError:
                peer.kill()
                await peer.wait()
