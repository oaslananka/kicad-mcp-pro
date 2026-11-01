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

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_isolated_tls_websocket_handshake import _synthetic_tls

from kicad_mcp.cloud_outbound_handshake import execute_operator_inspection_once
from kicad_mcp.cloud_project_worker_bridge import BoundConnectorProjectWorker
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps" / "cloud"
PEER = APP / "test" / "inspection-python.fixture.ts"
TSX = APP / "node_modules" / ".bin" / "tsx"


@pytest.mark.anyio
async def test_real_node_cloud_python_signed_wss_project_inspection(tmp_path: Path) -> None:
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
    cert_file = tmp_path / "temporary-test-server.crt"
    tls_key = tmp_path / "temporary-test-server.key"
    peer = await asyncio.create_subprocess_exec(
        str(TSX),
        str(PEER),
        str(cert_file),
        str(tls_key),
        str(key),
        cwd=str(APP),
        env=os.environ.copy(),
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
                    operations=frozenset({"project_worker_inspection"}),
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

        receipt = await asyncio.wait_for(
            execute_operator_inspection_once(
                origin=readiness["origin"],
                trusted_origin=readiness["origin"],
                owner_sub=readiness["owner"],
                device_id=readiness["device"],
                signing_key=signer,
                tls_context=context,
                inspector_factory=factory,
            ),
            timeout=35,
        )
        assert receipt.device_id == readiness["device"]
        response = json.loads(await asyncio.wait_for(peer.stdout.readline(), timeout=20))
        status = response["result"]["status"]
        assert isinstance(status["engineVersion"], str)
        assert type(status["cliAvailable"]) is bool
        assert type(status["ipcAvailable"]) is bool
        assert "DESIGN_NOT_FOR_CLOUD" not in json.dumps(response)
        assert str(project_dir) not in json.dumps(response)
        assert "cliPath" not in json.dumps(response)
        await asyncio.wait_for(peer.wait(), timeout=12)
        assert peer.returncode == 0
    finally:
        if peer.returncode is None:
            peer.terminate()
            try:
                await asyncio.wait_for(peer.wait(), timeout=5)
            except TimeoutError:
                peer.kill()
                await peer.wait()
