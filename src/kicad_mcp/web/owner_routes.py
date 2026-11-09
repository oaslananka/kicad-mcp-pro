"""Owner-bound loopback controls for onboarding, connector, and maintenance.

The browser has no bearer-token access to Cloud credentials. Only a local
same-origin session with a server-generated CSRF token may mutate owner state.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from urllib.parse import urlunsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from kicad_mcp.cli_init import _resolve_config_path
from kicad_mcp.config import get_config
from kicad_mcp.services.client_config import ClientConfigError, write_client_config_safe
from kicad_mcp.services.cloud_onboarding import DEFAULT_CLOUD_ORIGIN, CloudOnboardingService
from kicad_mcp.services.connector_lifecycle import ConnectorLifecycleManager
from kicad_mcp.services.maintenance import (
    CleanupPreview,
    CleanupResult,
    MaintenanceService,
    RepairPreview,
    RepairResult,
)
from kicad_mcp.web.state import begin_maintenance, end_maintenance

_COOKIE = "kicad_owner_session"
_CSRF_HEADER = "x-kicad-owner-csrf"
_SESSION_AGE = 1800
_PREVIEW_AGE = 300
_MAX_BODY = 16384
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
_INVALID_SETUP_REQUEST = "Invalid setup request"
_SETUP_NOT_FOUND = "Setup not found"
_INVALID_MAINTENANCE_REQUEST = "Invalid maintenance request"
_OWNER_AUTH_REQUIRED = "Owner authorization required"


def _response(payload: dict[str, object], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _scope(request: Request) -> SimpleNamespace:
    scope = getattr(request.app.state, "owner_control", None)
    if scope is None:
        scope = SimpleNamespace(sessions={}, operations={}, previews={})
        request.app.state.owner_control = scope
    return scope


def _services(request: Request) -> SimpleNamespace:
    services = getattr(request.app.state, "owner_services", None)
    if services is None:
        if os.name == "nt":
            from kicad_mcp.services.cloud_windows_onboarding_ui import WindowsCloudOnboardingService

            onboarding: CloudOnboardingService | WindowsCloudOnboardingService = (
                WindowsCloudOnboardingService()
            )
        else:
            onboarding = CloudOnboardingService()
        services = SimpleNamespace(
            onboarding=onboarding,
            connector=ConnectorLifecycleManager(),
            maintenance=MaintenanceService(),
        )
        request.app.state.owner_services = services
    return services


def _local_authority(request: Request) -> str | None:
    """Compare actual Host against the configured loopback port, not arbitrary DNS."""
    cfg = get_config()
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        return None
    if request.client is None or request.client.host not in ("127.0.0.1", "::1", "localhost"):
        return None
    # Exact static authorities: do not parse an untrusted Host into a URL.
    authority = request.headers.get("host", "").lower()
    for hostname in _LOOPBACK_HOSTS:
        trusted = f"{hostname}:{cfg.port}"
        if authority == trusted:
            return trusted
    return None


def _expected_origin(authority: str | None, port: int) -> str | None:
    """Return an origin generated only from verified loopback constants."""
    if authority is None:
        return None
    for hostname in _LOOPBACK_HOSTS:
        trusted = f"{hostname}:{port}"
        if authority == trusted:
            return urlunsplit(("http", trusted, "", "", ""))
    return None


def _owner_session(request: Request) -> tuple[str, str] | None:
    authority = _local_authority(request)
    if authority is None:
        return None
    scope = _scope(request)
    token = request.cookies.get(_COOKIE, "")
    record = scope.sessions.get(token)
    if not record:
        return None
    csrf, expiry, original_authority = record
    if expiry < time.monotonic() or original_authority != authority:
        scope.sessions.pop(token, None)
        return None
    return token, csrf


def _authorize_mutation(request: Request) -> tuple[str | None, JSONResponse | None]:
    session = _owner_session(request)
    if session is None:
        return None, _response({"error": _OWNER_AUTH_REQUIRED}, 403)
    authority = _local_authority(request)
    origin = request.headers.get("origin")
    if authority is None or origin != _expected_origin(authority, get_config().port):
        return None, _response({"error": "Origin not allowed"}, 403)
    csrf = request.headers.get(_CSRF_HEADER, "")
    if not csrf or not hmac.compare_digest(csrf, session[1]):
        return None, _response({"error": "Invalid CSRF token"}, 403)
    return session[0], None


async def _json_body(request: Request) -> tuple[dict[str, object] | None, JSONResponse | None]:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        return None, _response({"error": "Expected JSON"}, 415)
    if (
        request.headers.get("content-length", "").isdigit()
        and int(request.headers["content-length"]) > _MAX_BODY
    ):
        return None, _response({"error": "Request too large"}, 413)
    data = await request.body()
    if len(data) > _MAX_BODY:
        return None, _response({"error": "Request too large"}, 413)
    try:
        obj = json.loads(data)
    except ValueError:
        return None, _response({"error": "Malformed JSON"}, 400)
    if not isinstance(obj, dict):
        return None, _response({"error": "Expected JSON object"}, 400)
    return obj, None


def _preview_data(
    obj: RepairPreview | RepairResult | CleanupPreview | CleanupResult,
) -> dict[str, object]:
    return dict(asdict(obj))


def _preview_hash(
    obj: RepairPreview | RepairResult | CleanupPreview | CleanupResult,
) -> str:
    canonical = json.dumps(_preview_data(obj), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def api_owner_session(request: Request) -> JSONResponse:
    authority = _local_authority(request)
    if authority is None:
        return _response({"error": "Loopback owner only"}, 403)
    origin = request.headers.get("origin")
    if origin is not None and origin != _expected_origin(authority, get_config().port):
        return _response({"error": "Origin not allowed"}, 403)
    current = _owner_session(request)
    scope = _scope(request)
    if current is None:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        scope.sessions[token] = (csrf, time.monotonic() + _SESSION_AGE, authority)
    else:
        token, csrf = current
    response = _response({"csrf_token": csrf})
    response.set_cookie(
        _COOKIE,
        token,
        max_age=_SESSION_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return response


async def api_project_folder_browse(request: Request) -> JSONResponse:
    """Open an on-device folder chooser only for a CSRF-confirmed local owner."""
    _, denied = _authorize_mutation(request)
    if denied:
        return denied

    # Selecting a folder does not register a Cloud device or change the
    # active project. The user explicitly applies the choice afterwards.
    from kicad_mcp.cloud_user_cli import _browse_local_project_folder

    try:
        selected = await asyncio.to_thread(_browse_local_project_folder)
        directory = selected.resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("Selected path is not a folder")
    except Exception:
        # GUI unavailability and user cancellation are ordinary recoverable
        # outcomes. Avoid leaking filesystem or native dialog exceptions.
        return _response({"error": "No folder selected. Click Browse to try again."}, 409)
    return _response({"project_dir": str(directory)})


async def api_owner_project_select(request: Request) -> JSONResponse:
    """Apply only an explicit project folder selected by the local owner."""
    _, denied = _authorize_mutation(request)
    if denied:
        return denied
    body, bad = await _json_body(request)
    if bad:
        return bad
    if (
        body is None
        or set(body) != {"project_dir"}
        or not isinstance(body["project_dir"], str)
        or not body["project_dir"].strip()
    ):
        return _response({"error": "Select an existing local project folder."}, 400)
    from .routes import api_config_post

    return await api_config_post(request)


async def api_cloud_setup_start(request: Request) -> JSONResponse:
    owner, denied = _authorize_mutation(request)
    if denied:
        return denied
    body, bad = await _json_body(request)
    if bad:
        return bad
    if body is None or owner is None:
        return _response({"error": _INVALID_SETUP_REQUEST}, 400)
    path = body.get("project_path")
    alias = body.get("alias")
    if (
        not isinstance(path, str)
        or not path.strip()
        or "origin" in body
        or "new_device" in body
        or (alias is not None and (not isinstance(alias, str) or len(alias) > 80))
    ):
        return _response({"error": _INVALID_SETUP_REQUEST}, 400)
    try:
        session = _services(request).onboarding.start_setup(
            project_dir=Path(path), cloud_origin=DEFAULT_CLOUD_ORIGIN, alias=alias
        )
    except (ValueError, OSError):
        return _response({"error": "Unable to begin setup for this project"}, 400)
    _scope(request).operations[session.session_id] = owner
    return _response(
        {
            "ok": True,
            "session_id": session.session_id,
            "step": session.current_step.value,
            "approval_url": session.approval_url,
            "user_code": session.user_code,
            "status": (
                "project_registered"
                if session.current_step.value == "complete"
                else "pairing_pending"
            ),
        }
    )


async def _owned_setup_request(request: Request) -> tuple[str | None, JSONResponse | None]:
    owner, denied = _authorize_mutation(request)
    if denied:
        return None, denied
    body, bad = await _json_body(request)
    if bad:
        return None, bad
    if body is None:
        return None, _response({"error": _INVALID_SETUP_REQUEST}, 400)
    session_id = body.get("session_id")
    if not isinstance(session_id, str) or _scope(request).operations.get(session_id) != owner:
        return None, _response({"error": _SETUP_NOT_FOUND}, 404)
    return session_id, None


async def api_cloud_setup_status(request: Request) -> JSONResponse:
    session_id, denied = await _owned_setup_request(request)
    if denied:
        return denied
    if session_id is None:
        return _response({"error": _SETUP_NOT_FOUND}, 404)
    progress = _services(request).onboarding.get_setup_status(session_id)
    return _response(
        {
            "ok": True,
            "session_id": session_id,
            "status": progress.status.value,
            "step": progress.step.value,
            "device_id": progress.device_id,
            "project_id": progress.project_id,
            "error": progress.error,
            "approval_url": progress.approval_url,
            "user_code": progress.user_code,
        }
    )


async def api_cloud_setup_cancel(request: Request) -> JSONResponse:
    session_id, denied = await _owned_setup_request(request)
    if denied:
        return denied
    if session_id is None:
        return _response({"error": _SETUP_NOT_FOUND}, 404)
    cancelled = _services(request).onboarding.cancel_setup(session_id)
    if not cancelled:
        if os.name == "nt":
            from kicad_mcp.services.cloud_windows_onboarding_ui import WindowsCloudOnboardingService

            if isinstance(_services(request).onboarding, WindowsCloudOnboardingService):
                return _response(
                    {
                        "error": "Device approval already started. Deny it in the browser or let "
                        "it expire, then review Cloud Devices. Connector remains off."
                    },
                    409,
                )
        return _response({"error": _SETUP_NOT_FOUND}, 404)
    _scope(request).operations.pop(session_id, None)
    return _response({"ok": True, "status": "cancelled"})


async def api_cloud_connector_enable(request: Request) -> JSONResponse:
    _, denied = _authorize_mutation(request)
    if denied:
        return denied
    manager = _services(request).connector
    if os.name == "nt" and isinstance(manager, ConnectorLifecycleManager):
        from kicad_mcp.cloud_windows_connector import selected_project
        from kicad_mcp.cloud_windows_task_scheduler import enable_windows_connector, scheduler_state

        try:
            project = selected_project()
            if project is None:
                return _response({"error": "No owner-selected Windows project"}, 409)
            await asyncio.to_thread(
                enable_windows_connector, project, owner_confirm=lambda _project: True
            )
            return _response({"ok": True, "status": scheduler_state()})
        except (OSError, ValueError, RuntimeError):
            return _response({"error": "Windows Connector could not be scheduled"}, 409)
    try:
        started = await manager.start()
    except (OSError, ValueError, RuntimeError):
        return _response({"error": "Unable to start connector"}, 409)
    if not started and not manager.is_running():
        return _response({"error": "Connector could not start"}, 409)
    return _response({"ok": True, "status": "started" if started else "already_running"})


async def api_cloud_connector_disable(request: Request) -> JSONResponse:
    _, denied = _authorize_mutation(request)
    if denied:
        return denied
    manager = _services(request).connector
    if os.name == "nt" and isinstance(manager, ConnectorLifecycleManager):
        from kicad_mcp.cloud_windows_task_scheduler import disable_windows_connector

        try:
            stopped = await asyncio.to_thread(disable_windows_connector)
        except (OSError, ValueError, RuntimeError):
            return _response({"error": "Windows Connector shutdown could not be verified"}, 409)
        if not stopped:
            return _response(
                {"error": "Local read access revoked; background task shutdown unverified"}, 409
            )
        return _response({"ok": True, "status": "disabled"})
    try:
        await manager.stop()
    except (OSError, ValueError, RuntimeError):
        return _response({"error": "Unable to stop connector"}, 409)
    return _response({"ok": True, "status": "disabled"})


async def api_cloud_project_active(request: Request) -> JSONResponse:
    _, denied = _authorize_mutation(request)
    if denied:
        return denied
    body, bad = await _json_body(request)
    if bad:
        return bad
    if body is None:
        return _response({"error": "Invalid project identifier"}, 400)
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or len(project_id) > 128 or not project_id:
        return _response({"error": "Invalid project identifier"}, 400)
    try:
        switched = await _services(request).connector.switch_active_project(project_id)
    except (OSError, ValueError, RuntimeError):
        switched = False
    if not switched:
        return _response({"error": "Project not registered or unavailable"}, 409)
    return _response({"ok": True, "active_project_id": project_id})


# The local owner may choose a supported app; never accept an arbitrary
# filesystem path from HTTP for modifying another AI client's config.
_GUIDED_JSON_CLIENTS = frozenset(("claude-desktop", "cursor", "vscode", "windsurf"))


def _read_guided_client_config(target: Path) -> tuple[bytes, dict[str, object]]:
    """Inspect a supported local client file without following redirected paths."""
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError("Client configuration is redirected")
    if not target.exists():
        return b"", {}
    if not target.is_file() or target.stat().st_size > 1024 * 1024:
        raise ValueError("Client configuration is not a supported JSON file")
    content = target.read_bytes()
    try:
        obj = json.loads(content)
    except ValueError as exc:
        raise ValueError("Client configuration is malformed") from exc
    if not isinstance(obj, dict):
        raise ValueError("Client configuration root must be a JSON object")
    return content, obj


def _client_setup_preview(client: str) -> tuple[Path, str, bool, int]:
    if client not in _GUIDED_JSON_CLIENTS:
        raise ValueError("Unsupported guided client")
    target = _resolve_config_path(client)
    if target is None:
        raise ValueError("Client has no supported local configuration path")
    content, obj = _read_guided_client_config(target)
    from .routes import _mcp_snippet_for_client

    snippet, fmt = _mcp_snippet_for_client(client)
    if fmt != "json" or not isinstance(snippet, dict):
        raise ValueError("Client does not support guided JSON config")
    namespace = "servers" if client == "vscode" else "mcpServers"
    existing = obj.get(namespace, {})
    if not isinstance(existing, dict):
        raise ValueError("Existing client MCP settings are invalid")
    replacing = "kicad-mcp-pro" in existing
    # A changed file forces a fresh explicit preview before apply.
    signature = hashlib.sha256(
        json.dumps([str(target.resolve()), client], ensure_ascii=False).encode() + b"\x00" + content
    ).hexdigest()
    return target, signature, replacing, len(existing)


def api_client_config_preview(request: Request) -> JSONResponse:
    owner = _owner_session(request)
    if owner is None:
        return _response({"error": _OWNER_AUTH_REQUIRED}, 403)
    client = request.path_params.get("client", "")
    try:
        target, signature, replacing, entries = _client_setup_preview(client)
    except (ValueError, OSError):
        return _response({"error": "Client configuration is unavailable or unsupported"}, 409)
    nonce = secrets.token_urlsafe(32)
    _scope(request).previews[(owner[0], "client_config:" + client)] = (
        nonce,
        signature,
        time.monotonic() + _PREVIEW_AGE,
    )
    return _response(
        {
            "client": client,
            "config_path": str(target),
            "action": "update_existing" if replacing else "add",
            "other_entries": entries - int(replacing),
            "confirmation": nonce,
            "description": (
                "Preserves unrelated MCP entries and creates a backup when a file exists."
            ),
        }
    )


async def api_client_config_apply(request: Request) -> JSONResponse:
    owner, denied = _authorize_mutation(request)
    if denied:
        return denied
    body, bad = await _json_body(request)
    if bad:
        return bad
    client = request.path_params.get("client", "")
    if client not in _GUIDED_JSON_CLIENTS or owner is None or body is None:
        return _response({"error": "Unsupported client or invalid request"}, 400)
    confirmation = body.get("confirmation")
    pending = _scope(request).previews.pop((owner, "client_config:" + client), None)
    if (
        pending is None
        or not isinstance(confirmation, str)
        or not hmac.compare_digest(confirmation, pending[0])
        or pending[2] < time.monotonic()
    ):
        return _response({"error": "A fresh client configuration preview is required"}, 409)
    try:
        target, signature, _, _ = _client_setup_preview(client)
        if not hmac.compare_digest(signature, pending[1]):
            return _response({"error": "Client settings changed; preview again"}, 409)
        from .routes import _mcp_snippet_for_client

        snippet, fmt = _mcp_snippet_for_client(client)
        if fmt != "json" or not isinstance(snippet, dict):
            return _response({"error": "Unsupported client settings format"}, 409)
        result = write_client_config_safe(client, target, snippet)
    except (ValueError, OSError, ClientConfigError):
        return _response(
            {"error": "Client settings could not be changed; no connection was claimed"}, 409
        )
    return _response(
        {
            "ok": result.success,
            "client": client,
            "backup_created": result.backup_path is not None,
            "message": (
                "Client settings saved. Open the AI client and verify its actual MCP connection."
            ),
        }
    )


def _preview_service(request: Request, kind: str) -> RepairPreview | CleanupPreview:
    service = cast(MaintenanceService, _services(request).maintenance)
    if kind == "repair":
        return service.preview_repair()
    return service.preview_cleanup()


def _preview(request: Request, kind: str) -> JSONResponse:
    session = _owner_session(request)
    if session is None:
        return _response({"error": _OWNER_AUTH_REQUIRED}, 403)
    try:
        preview = _preview_service(request, kind)
    except (OSError, ValueError):
        return _response({"error": "Unable to inspect application state"}, 409)
    nonce = secrets.token_urlsafe(32)
    _scope(request).previews[(session[0], kind)] = (
        nonce,
        _preview_hash(preview),
        time.monotonic() + _PREVIEW_AGE,
    )
    return _response({**_preview_data(preview), "confirmation": nonce})


def api_maintenance_repair_preview(request: Request) -> JSONResponse:
    return _preview(request, "repair")


def api_maintenance_cleanup_preview(request: Request) -> JSONResponse:
    return _preview(request, "cleanup")


async def _apply(request: Request, kind: str) -> JSONResponse:
    owner, denied = _authorize_mutation(request)
    if denied:
        return denied
    body, bad = await _json_body(request)
    if bad:
        return bad
    if owner is None or body is None:
        return _response({"error": _INVALID_MAINTENANCE_REQUEST}, 400)
    supplied = body.get("confirmation")
    pending = _scope(request).previews.pop((owner, kind), None)
    if (
        pending is None
        or not isinstance(supplied, str)
        or not hmac.compare_digest(supplied, pending[0])
        or pending[2] < time.monotonic()
    ):
        return _response({"error": "A fresh maintenance preview is required"}, 409)
    try:
        if _preview_hash(_preview_service(request, kind)) != pending[1]:
            return _response({"error": "Application state changed; review again"}, 409)
        service = cast(MaintenanceService, _services(request).maintenance)
        result = service.apply_repair() if kind == "repair" else service.apply_cleanup()
    except (OSError, ValueError):
        return _response({"error": "Maintenance did not complete"}, 409)
    return _response(
        {"ok": result.success, **_preview_data(result)}, 200 if result.success else 409
    )


async def api_maintenance_repair_apply(request: Request) -> JSONResponse:
    return await _apply(request, "repair")


async def api_maintenance_cleanup_apply(request: Request) -> JSONResponse:
    return await _apply(request, "cleanup")


async def api_maintenance_quiesce(request: Request) -> JSONResponse:
    """Fences new tool calls only when no engineering operation is active."""
    owner, denied = _authorize_mutation(request)
    if denied:
        return denied
    body, bad = await _json_body(request)
    if bad:
        return bad
    if owner is None or body != {}:
        return _response({"error": _INVALID_MAINTENANCE_REQUEST}, 400)
    # Cloud reads use a separate dispatcher and do not traverse the MCP call
    # counter. Refuse updates while a connector may still issue such reads.
    try:
        connector_state = _services(request).connector.get_status().state
    except (OSError, RuntimeError, ValueError, AttributeError):
        return _response({"error": "Cloud connector state unavailable"}, 409)
    if connector_state != "off":
        return _response({"error": "Disable the Cloud connector before updating"}, 409)
    token = begin_maintenance(owner)
    if token is None:
        return _response({"error": "Backend busy or already quiesced"}, 409)
    return _response({"ok": True, "state": "quiesced", "token": token})


async def api_maintenance_resume(request: Request) -> JSONResponse:
    """Restore service only to the owner that obtained the update lease."""
    owner, denied = _authorize_mutation(request)
    if denied:
        return denied
    body, bad = await _json_body(request)
    if bad:
        return bad
    token = body.get("token") if body is not None else None
    if owner is None or not isinstance(token, str) or len(token) > 160:
        return _response({"error": _INVALID_MAINTENANCE_REQUEST}, 400)
    if not end_maintenance(owner, token):
        return _response({"error": "Maintenance ownership mismatch"}, 409)
    return _response({"ok": True, "state": "running"})
