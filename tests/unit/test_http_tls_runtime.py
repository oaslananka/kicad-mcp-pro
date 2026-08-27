from __future__ import annotations

from pathlib import Path

import pytest
import uvicorn

from kicad_mcp.config import KiCadMCPConfig
from kicad_mcp.server import KiCadFastMCP


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["run_streamable_http_async", "run_sse_async"])
async def test_http_runtime_passes_direct_tls_files_to_uvicorn(
    method_name: str,
    tmp_path: Path,
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = sample_project
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("private-key", encoding="utf-8")
    cfg = KiCadMCPConfig(
        transport="streamable-http",
        host="192.168.1.42",
        auth_token="x" * 32,
        tls_cert_file=cert,
        tls_key_file=key,
    )
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, app: object, **kwargs: object) -> None:
            captured["app"] = app
            captured.update(kwargs)

    class FakeServer:
        def __init__(self, config: object) -> None:
            captured["config"] = config

        async def serve(self) -> None:
            captured["served"] = True

    monkeypatch.setattr("kicad_mcp.server.get_config", lambda: cfg)
    monkeypatch.setattr(uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)

    server = KiCadFastMCP(
        name="tls-test",
        host=cfg.host,
        port=cfg.port,
        streamable_http_path=cfg.mount_path,
        mount_path=cfg.mount_path,
    )
    await getattr(server, method_name)()

    assert captured["ssl_certfile"] == str(cert)
    assert captured["ssl_keyfile"] == str(key)
    assert captured["served"] is True
