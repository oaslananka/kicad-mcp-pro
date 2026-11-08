"""Owner-gated client config: preview, exact confirmation, and no cross-app edits."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp.config import reset_config
from kicad_mcp.services.client_config import write_client_config_safe
from kicad_mcp.web import owner_routes
from kicad_mcp.web.routes import web_routes

ORIGIN = "http://127.0.0.1:3334"


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    monkeypatch.setenv("KICAD_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("KICAD_MCP_PORT", "3334")
    reset_config()
    target = tmp_path / "settings.json"
    monkeypatch.setattr(owner_routes, "_resolve_config_path", lambda _client: target)

    def scoped_write(client: str, path: Path, snippet: dict) -> object:
        return write_client_config_safe(
            client, path, snippet, registry_root=tmp_path / "owner-registry"
        )

    monkeypatch.setattr(owner_routes, "write_client_config_safe", scoped_write)
    with TestClient(
        Starlette(routes=web_routes), base_url=ORIGIN, client=("127.0.0.1", 50000)
    ) as browser:
        yield browser, target
    reset_config()


def headers_for(browser: TestClient) -> dict[str, str]:
    session = browser.get("/api/owner/session")
    assert session.status_code == 200
    return {"Origin": ORIGIN, "X-KiCad-Owner-CSRF": session.json()["csrf_token"]}


def test_guided_config_requires_owner_and_explicit_origin(owner) -> None:
    browser, target = owner
    assert browser.get("/api/owner/client-config/preview/claude-desktop").status_code == 403
    headers = headers_for(browser)
    preview = browser.get("/api/owner/client-config/preview/claude-desktop")
    assert preview.status_code == 200
    token = preview.json()["confirmation"]
    assert not target.exists()
    assert (
        browser.post(
            "/api/owner/client-config/apply/claude-desktop",
            headers={**headers, "Origin": "https://evil.example"},
            json={"confirmation": token},
        ).status_code
        == 403
    )
    assert (
        browser.post(
            "/api/owner/client-config/apply/claude-desktop",
            headers={"Origin": ORIGIN},
            json={"confirmation": token},
        ).status_code
        == 403
    )
    assert not target.exists()


def test_guided_apply_preserves_other_mcp_clients_and_reports_only_config_saved(owner) -> None:
    browser, target = owner
    target.write_text(
        json.dumps({"mcpServers": {"sqlite": {"command": "unrelated"}}}),
        encoding="utf-8",
    )
    headers = headers_for(browser)
    preview = browser.get("/api/owner/client-config/preview/claude-desktop")
    assert preview.status_code == 200
    assert preview.json()["other_entries"] == 1
    assert "sqlite" not in preview.text
    success = browser.post(
        "/api/owner/client-config/apply/claude-desktop",
        headers=headers,
        json={"confirmation": preview.json()["confirmation"]},
    )
    assert success.status_code == 200
    assert success.json()["backup_created"]
    assert "verify its actual MCP connection" in success.json()["message"]
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "sqlite" in data["mcpServers"]
    assert "kicad-mcp-pro" in data["mcpServers"]
    assert (
        browser.post(
            "/api/owner/client-config/apply/claude-desktop",
            headers=headers,
            json={"confirmation": preview.json()["confirmation"]},
        ).status_code
        == 409
    )


def test_guided_apply_requires_fresh_preview_if_file_changes(owner) -> None:
    browser, target = owner
    headers = headers_for(browser)
    preview = browser.get("/api/owner/client-config/preview/cursor")
    assert preview.status_code == 200
    target.write_text('{"user_setting": "do-not-change"}', encoding="utf-8")
    denied = browser.post(
        "/api/owner/client-config/apply/cursor",
        headers=headers,
        json={"confirmation": preview.json()["confirmation"]},
    )
    assert denied.status_code == 409
    assert "changed" in denied.text
    assert json.loads(target.read_text(encoding="utf-8")) == {"user_setting": "do-not-change"}


def test_guided_client_allowlist_and_vscode_merge(owner) -> None:
    browser, target = owner
    headers = headers_for(browser)
    assert browser.get("/api/owner/client-config/preview/codex").status_code == 409
    assert browser.get("/api/owner/client-config/preview/../../outside").status_code in (404, 409)
    target.write_text(json.dumps({"servers": {"unrelated": {"type": "stdio"}}}), encoding="utf-8")
    preview = browser.get("/api/owner/client-config/preview/vscode")
    assert preview.status_code == 200
    result = browser.post(
        "/api/owner/client-config/apply/vscode",
        headers=headers,
        json={"confirmation": preview.json()["confirmation"]},
    )
    assert result.status_code == 200
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data["servers"]) == {"unrelated", "kicad-mcp-pro"}


def test_bundled_app_owned_uv_is_reflected_in_local_client_snippet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp.web.routes import _mcp_snippet_for_client

    bundled = tmp_path / "uv.exe"
    bundled.write_bytes(b"test-owned placeholder executable")
    monkeypatch.setenv("KICAD_MCP_DESKTOP_UV", str(bundled))
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "cache"))
    snippet, format_name = _mcp_snippet_for_client("claude-desktop")
    assert format_name == "json"
    server = snippet["mcpServers"]["kicad-mcp-pro"]
    assert server["command"] == str(bundled)
    assert server["args"][:3] == ["tool", "run", "--from"]
    assert server["env"]["UV_CACHE_DIR"] == str(tmp_path / "cache")


@pytest.mark.parametrize(
    "content",
    [
        "{broken json",
        "[]",
        json.dumps({"mcpServers": []}),
    ],
)
def test_guided_preview_rejects_unsupported_existing_client_settings(owner, content: str) -> None:
    browser, target = owner
    headers_for(browser)
    target.write_text(content, encoding="utf-8")
    response = browser.get("/api/owner/client-config/preview/claude-desktop")
    assert response.status_code == 409
    assert target.read_text(encoding="utf-8") == content


def test_guided_preview_rejects_missing_and_oversized_client_config(
    owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser, target = owner
    headers_for(browser)
    monkeypatch.setattr(owner_routes, "_resolve_config_path", lambda _name: None)
    assert browser.get("/api/owner/client-config/preview/cursor").status_code == 409
    monkeypatch.setattr(owner_routes, "_resolve_config_path", lambda _name: target)
    target.write_bytes(b" " * (1024 * 1024 + 1))
    assert browser.get("/api/owner/client-config/preview/cursor").status_code == 409
    assert target.stat().st_size > 1024 * 1024


def test_guided_preview_refuses_redirected_and_unrecognized_client_format(
    owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser, target = owner
    headers_for(browser)
    original_is_symlink = Path.is_symlink

    def redirected(path: Path) -> bool:
        return path == target or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", redirected)
    assert browser.get("/api/owner/client-config/preview/cursor").status_code == 409
    monkeypatch.setattr(Path, "is_symlink", original_is_symlink)
    from kicad_mcp.web import routes

    monkeypatch.setattr(routes, "_mcp_snippet_for_client", lambda _client: ({}, "toml"))
    assert browser.get("/api/owner/client-config/preview/cursor").status_code == 409
    assert not target.exists()


def test_guided_apply_rejects_bad_body_or_unsupported_client(
    owner,
) -> None:
    browser, target = owner
    headers = headers_for(browser)
    malformed = browser.post(
        "/api/owner/client-config/apply/claude-desktop",
        headers={**headers, "Content-Type": "application/json"},
        content="{bad",
    )
    assert malformed.status_code == 400
    unsupported = browser.post(
        "/api/owner/client-config/apply/codex",
        headers=headers,
        json={"confirmation": "not-valid"},
    )
    assert unsupported.status_code == 400
    assert not target.exists()


def test_guided_apply_handles_write_failure_without_claiming_connection(
    owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser, target = owner
    headers = headers_for(browser)
    preview = browser.get("/api/owner/client-config/preview/claude-desktop")
    assert preview.status_code == 200

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise owner_routes.ClientConfigError("test blocked client write")

    monkeypatch.setattr(owner_routes, "write_client_config_safe", fail_write)
    result = browser.post(
        "/api/owner/client-config/apply/claude-desktop",
        headers=headers,
        json={"confirmation": preview.json()["confirmation"]},
    )
    assert result.status_code == 409
    assert "no connection was claimed" in result.text
    assert not target.exists()
