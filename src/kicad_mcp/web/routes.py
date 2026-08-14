"""Starlette APIRouter for the web dashboard and API endpoints."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import platform
import sys
import threading
import time
from collections.abc import AsyncGenerator
from pathlib import Path

import structlog
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from .. import __version__
from ..cli_init import MCP_CLIENT_CONFIGS
from ..compatibility import DESKTOP_API_CONTRACT_VERSION, DESKTOP_BACKEND_VERSION_POLICY
from ..config import get_config, reset_config
from ..diagnostics import build_health_report
from ..discovery import find_kicad_version
from ..errors import UnsafePathError
from ..ipc.capabilities import get_ipc_capability_state
from ..models.live_preview import LivePreviewManifest
from ..operating_modes import active_operating_mode
from ..path_safety import resolve_under
from ..tools.router import available_profiles, tool_count_for_profile
from .dashboard import DASHBOARD_HTML
from .state import get_metrics_snapshot, get_server_handle, get_start_time

logger = structlog.get_logger(__name__)

_CLIENT_ALIASES = {
    "claude": "claude-desktop",
    "claude-desktop": "claude-desktop",
    "cursor": "cursor",
    "vscode": "vscode",
    "vs-code": "vscode",
    "windsurf": "windsurf",
    "zed": "zed",
    "codex": "codex",
}

# ---------------------------------------------------------------------------
# Log stream support
# ---------------------------------------------------------------------------

_log_subscribers: list[asyncio.Queue[str]] = []
_log_subscribers_lock = asyncio.Lock()


async def _broadcast_log(entry: str) -> None:
    """Push a log entry to all active SSE subscribers."""
    async with _log_subscribers_lock:
        dead: list[asyncio.Queue[str]] = []
        for q in _log_subscribers:
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _log_subscribers.remove(q)


def push_log(level: str, event: str, **kwargs: object) -> None:
    """Thread-safe push of a log entry to SSE subscribers.

    Can be called from any thread (structlog processor, CLI command, etc.).
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry = json.dumps({"timestamp": timestamp, "level": level, "event": event, **kwargs})
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_broadcast_log(entry), loop)
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# SSE log stream generator
# ---------------------------------------------------------------------------


async def _sse_log_generator() -> AsyncGenerator[str]:
    """SSE generator that yields log entries as they arrive."""
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
    async with _log_subscribers_lock:
        _log_subscribers.append(q)
    try:
        yield f"data: {json.dumps({'event': 'connected'})}\n\n"
        while True:
            try:
                entry = await asyncio.wait_for(q.get(), timeout=30.0)
                yield f"data: {entry}\n\n"
            except TimeoutError:
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        raise
    finally:
        async with _log_subscribers_lock:
            if q in _log_subscribers:
                _log_subscribers.remove(q)


def setup_log_stream() -> None:
    """Configure structlog to broadcast log entries to SSE subscribers."""
    from structlog.processors import EventRenamer

    renamer = EventRenamer("event")

    def _sse_processor(
        logger: structlog.typing.FilteringBoundLogger,
        method_name: str,
        event_dict: structlog.typing.EventDict,
    ) -> structlog.typing.EventDict:
        level = event_dict.get("level", method_name.upper())
        event = event_dict.get("event", "")
        push_log(
            str(level).upper(),
            str(event),
            **{k: v for k, v in event_dict.items() if k not in ("level", "event", "timestamp")},
        )
        return event_dict

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            renamer,
            _sse_processor,
            structlog.dev.ConsoleRenderer(),
        ]
    )


# ---------------------------------------------------------------------------
# API endpoint handlers
# ---------------------------------------------------------------------------


def _config_public_payload() -> dict[str, object]:
    """Return config fields useful for the dashboard without leaking secrets."""
    cfg = get_config()
    safe = cfg.safe_diagnostics()
    payload: dict[str, object] = {
        "profile": cfg.profile,
        "transport": cfg.transport,
        "host": cfg.host,
        "port": cfg.port,
        "kicad_path": str(cfg.kicad_cli) if cfg.kicad_cli else "",
        "kicad_cli": str(cfg.kicad_cli) if cfg.kicad_cli else "",
        "project_dir": str(cfg.project_dir) if cfg.project_dir else "",
        "pcb_file": str(cfg.pcb_file) if cfg.pcb_file else "",
        "sch_file": str(cfg.sch_file) if cfg.sch_file else "",
        "log_level": safe.get("log_level", os.environ.get("KICAD_MCP_LOG_LEVEL", "INFO")),
        "operating_mode": active_operating_mode(cfg).value,
    }
    payload.update({k: v for k, v in safe.items() if k not in payload})
    return payload


def _platform_config_path(client: str) -> str:
    """Return the documented MCP client config path for the current platform."""
    if client == "codex":
        return "~/.codex/config.toml"
    sys_key = platform.system().lower()
    if sys_key.startswith("win"):
        sys_key = "windows"
    candidates = MCP_CLIENT_CONFIGS.get(client, {})
    return candidates.get(sys_key, "")


def _mcp_snippet_for_client(client: str) -> tuple[object, str]:
    """Build a client-specific MCP config snippet and format label."""
    cfg = get_config()
    server_name = "kicad-mcp-pro"
    args = [f"{server_name}@{__version__}"]
    if cfg.transport != "stdio":
        args.extend(["--transport", cfg.transport, "--port", str(cfg.port)])
    stdio_server = {"command": "uvx", "args": args, "env": {}}

    if client == "vscode":
        return {"servers": {server_name: {"type": "stdio", **stdio_server}}}, "json"
    if client == "codex":
        return (
            "\n".join(
                [
                    f"[mcp_servers.{server_name}]",
                    'command = "uvx"',
                    f"args = {json.dumps(args)}",
                ]
            ),
            "toml",
        )
    return {"mcpServers": {server_name: stdio_server}}, "json"


def _json_config(snippet: object, fmt: str) -> str:
    """Render config snippets for copy/paste clients."""
    if fmt == "toml":
        return str(snippet)
    return json.dumps(snippet, indent=2, ensure_ascii=False)


async def api_status(request: Request) -> JSONResponse:
    """Return full server status as JSON."""
    cfg = get_config()
    report = build_health_report()
    ipc_state = get_ipc_capability_state()
    kicad_version = find_kicad_version(cfg.kicad_cli)
    tool_count = tool_count_for_profile(cfg.profile)
    metrics = get_metrics_snapshot()
    uptime_seconds = round(time.time() - get_start_time(), 2)
    status = "running" if report.ok else report.status

    return JSONResponse(
        {
            "status": status,
            "uptime_seconds": uptime_seconds,
            "transport": cfg.transport,
            "host": cfg.host,
            "port": cfg.port,
            "version": __version__,
            "kicad_version": kicad_version or None,
            "kicad_path": str(cfg.kicad_cli) if cfg.kicad_cli else None,
            "active_sessions": 0,
            "total_tool_calls": metrics.get("total_calls", 0),
            "tool_calls_today": metrics.get("total_calls", 0),
            "error_count_today": metrics.get("total_errors", 0),
            "pid": os.getpid(),
            "server": {
                "version": __version__,
                "profile": cfg.profile,
                "operating_mode": active_operating_mode(cfg).value,
                "transport": cfg.transport,
                "host": cfg.host,
                "port": cfg.port,
                "status": status,
                "uptime_seconds": uptime_seconds,
                "pid": os.getpid(),
            },
            "kicad": {
                "cli_path": str(cfg.kicad_cli) if cfg.kicad_cli else None,
                "version": kicad_version or None,
                "ipc_status": "connected" if ipc_state.reachable else "disconnected",
            },
            "project": {
                "dir": str(cfg.project_dir) if cfg.project_dir else None,
                "pcb": str(cfg.pcb_file) if cfg.pcb_file else None,
                "sch": str(cfg.sch_file) if cfg.sch_file else None,
            },
            "health": {
                "status": report.status,
                "ok": report.ok,
                "checks": [
                    {"name": c.name, "status": c.status, "message": c.message}
                    for c in report.checks
                ],
            },
            "tools": {
                "available_profiles": available_profiles(),
                "active_tool_count": tool_count,
                "total_tool_calls": metrics.get("total_calls", 0),
                "error_count_today": metrics.get("total_errors", 0),
            },
            "timestamp": time.time(),
        }
    )


async def api_health(request: Request) -> JSONResponse:
    """Return lightweight health check."""
    report = build_health_report()
    return JSONResponse(
        {
            "ok": report.ok,
            "status": report.status,
            "version": __version__,
            "desktopCompatibility": {
                "contractVersion": DESKTOP_API_CONTRACT_VERSION,
                "backendVersion": __version__,
                "versionPolicy": DESKTOP_BACKEND_VERSION_POLICY,
            },
            "uptime": time.time() - get_start_time(),
        }
    )


async def api_info(request: Request) -> JSONResponse:
    """Return basic server information."""
    cfg = get_config()
    return JSONResponse(
        {
            "name": "KiCad MCP Pro",
            "version": __version__,
            "python": sys.version,
            "platform": sys.platform,
            "pid": os.getpid(),
            "config": cfg.safe_diagnostics(),
        }
    )


_sse_headers = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def api_log_stream(request: Request) -> StreamingResponse:
    """SSE endpoint for real-time log streaming."""
    return StreamingResponse(
        _sse_log_generator(),
        media_type="text/event-stream",
        headers=_sse_headers,
    )


async def api_dashboard(request: Request) -> HTMLResponse:
    """Serve the web dashboard HTML page."""
    return HTMLResponse(DASHBOARD_HTML)


# ---------------------------------------------------------------------------
# Step 3 — Missing API endpoints
# ---------------------------------------------------------------------------


async def api_tools(request: Request) -> JSONResponse:
    """List available MCP tools with metadata and annotations."""
    handle = get_server_handle()
    if handle is None:
        return JSONResponse({"error": "Server not initialized", "tools": []}, status_code=503)
    try:
        raw_tools = handle.list_tools()
        payload: list[dict[str, object]] = []
        for tool in raw_tools:
            if hasattr(tool, "model_dump"):
                dumped = tool.model_dump(mode="json", exclude_none=True)
            else:
                dumped = {"name": str(tool)}
            payload.append(
                {
                    "name": dumped.get("name"),
                    "description": dumped.get("description", ""),
                    "inputSchema": dumped.get("inputSchema", {}),
                    "annotations": dumped.get("annotations", {}),
                }
            )
        return JSONResponse({"count": len(payload), "tools": payload})
    except Exception as exc:
        logger.warning("api_tools_error", error=str(exc))
        return JSONResponse({"error": str(exc), "tools": []}, status_code=500)


async def api_config_get(request: Request) -> JSONResponse:
    """Return the current (sanitized) server configuration."""
    payload = _config_public_payload()
    return JSONResponse({"config": payload, **payload})


ALLOWED_CONFIG_KEYS = {
    "transport",
    "host",
    "port",
    "profile",
    "log_level",
    "project_dir",
    "pcb_file",
    "sch_file",
    "operating_mode",
    "enable_experimental_tools",
    "enable_tasks",
}
_config_post_lock = threading.Lock()


async def api_config_post(request: Request) -> JSONResponse:
    """Update the server configuration at runtime via environment overrides."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be JSON."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body must be a JSON object."}, status_code=400)

    applied: list[str] = []
    errors: list[dict[str, str]] = []

    # Filter body to only contain safe config keys
    safe_body = {k: v for k, v in body.items() if k in ALLOWED_CONFIG_KEYS}

    with _config_post_lock:
        for key, value in safe_body.items():
            env_key = f"KICAD_MCP_{key.upper()}"
            os.environ[env_key] = str(value)
            applied.append(key)

        if applied:
            reset_config()
            logger.info("config_updated_via_api", keys=applied)

    payload = _config_public_payload()
    result = {
        "applied": applied,
        "errors": errors,
        "config": payload,
        **payload,
        "message": "Settings saved. Some changes require a restart.",
    }
    if errors:
        result["warning"] = "Some values were not applied."
    return JSONResponse(result)


async def api_config_export(request: Request) -> JSONResponse:
    """Export an MCP config snippet for a specific client."""
    raw_client = request.path_params.get("client", "").strip().casefold()
    client = _CLIENT_ALIASES.get(raw_client, raw_client)
    supported = set(MCP_CLIENT_CONFIGS) | {"codex"}
    if client not in supported:
        return JSONResponse(
            {
                "error": (
                    f"Unsupported client: {raw_client}. Supported: {', '.join(sorted(supported))}"
                )
            },
            status_code=400,
        )
    snippet, fmt = _mcp_snippet_for_client(client)
    config_path = _platform_config_path(client)
    config = _json_config(snippet, fmt)
    return JSONResponse(
        {
            "client": client,
            "config_path": config_path,
            "snippet": snippet,
            "instructions": (f"Add this snippet to {config_path or client + ' configuration'}."),
            "config": config,
            "format": fmt,
        }
    )


async def api_tool_test(request: Request) -> JSONResponse:
    """Validate or execute a dashboard tool test request.

    By default this endpoint performs a dry run so the GUI can exercise the
    form safely.  Passing ``{"dry_run": false, "arguments": {...}}`` attempts
    to call an exposed server ``call_tool`` method when available.
    """
    tool_name = request.path_params.get("tool_name", "").strip()
    if not tool_name:
        return JSONResponse({"error": "tool_name is required"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body must be a JSON object."}, status_code=400)

    arguments = body.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return JSONResponse({"error": "arguments must be an object."}, status_code=400)

    handle = get_server_handle()
    if handle is None:
        return JSONResponse({"error": "Server not initialized"}, status_code=503)

    dry_run = bool(body.get("dry_run", True))
    if dry_run:
        return JSONResponse(
            {
                "ok": True,
                "dry_run": True,
                "tool": tool_name,
                "arguments": arguments,
                "result": "Tool form validated. Set dry_run=false to execute.",
            }
        )

    call_tool = getattr(handle, "call_tool", None)
    if not callable(call_tool):
        return JSONResponse(
            {"error": "Tool execution is not available from this server handle."},
            status_code=501,
        )
    try:
        result = call_tool(tool_name, arguments)
        if inspect.isawaitable(result):
            result = await result
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json", exclude_none=True)
        return JSONResponse({"ok": True, "dry_run": False, "tool": tool_name, "result": result})
    except Exception as exc:
        logger.warning("api_tool_test_error", tool=tool_name, error=str(exc))
        return JSONResponse({"ok": False, "error": str(exc), "tool": tool_name}, status_code=500)


async def api_metrics(request: Request) -> JSONResponse:
    """Return server metrics as JSON (call counts, latencies, uptime)."""
    snapshot = get_metrics_snapshot()
    uptime = time.time() - get_start_time()
    return JSONResponse(
        {
            **snapshot,
            "uptime_seconds": round(uptime, 2),
            "uptime_human": _format_uptime(uptime),
        }
    )


async def api_server_action(request: Request) -> JSONResponse:
    """Control the server lifecycle (shutdown / restart).

    POST /api/server/start
    POST /api/server/stop
    POST /api/server/restart
    POST /api/server/shutdown
    """
    action = request.path_params.get("action", "").strip().casefold()
    if action not in {"start", "stop", "shutdown", "restart"}:
        return JSONResponse(
            {"error": f"Unknown action: {action}. Use: start, stop, restart"},
            status_code=400,
        )
    logger.warning("server_action_via_api", action=action)
    if action == "start":
        return JSONResponse({"ok": True, "action": "start", "status": "running"})
    if action in {"stop", "shutdown"}:
        thread = threading.Thread(target=_shutdown_process, daemon=True)
        thread.start()
        return JSONResponse(
            {
                "ok": True,
                "action": "stop" if action == "stop" else "shutdown",
                "status": "initiated",
            }
        )
    if action == "restart":
        thread = threading.Thread(target=_restart_process, daemon=True)
        thread.start()
        return JSONResponse({"ok": True, "action": "restart", "status": "initiated"})
    return JSONResponse({"error": f"Unknown action: {action}"}, status_code=400)


def _shutdown_process() -> None:
    """Shutdown the current process after a short delay to allow response delivery."""
    time.sleep(0.5)
    os._exit(0)


def _restart_process() -> None:
    """Restart the current process after a short delay."""
    time.sleep(0.5)
    os.execl(sys.executable, sys.executable, "-m", "kicad_mcp.server", *sys.argv[1:])  # noqa: S606


def _format_uptime(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


_ARTIFACT_MIME_TYPES = {".svg": "image/svg+xml", ".png": "image/png"}


def _schematic_render_dir() -> Path:
    return get_config().ensure_output_dir("schematic-renders")


async def api_artifacts_schematic(request: Request) -> JSONResponse:
    """List recent schematic live-preview manifests for the dashboard Preview tab."""
    render_dir = _schematic_render_dir()
    entries: list[dict[str, object]] = []
    for manifest_path in render_dir.glob("*.manifest.json"):
        try:
            manifest = LivePreviewManifest.model_validate_json(manifest_path.read_text())
        except (OSError, ValueError):
            continue
        entries.append(
            {
                "session_id": manifest.session_id,
                "target_path": manifest.target_path,
                "sheet_path": manifest.render.sheet_path,
                "png_path": manifest.render.png_path,
                "svg_path": manifest.render.svg_path,
                "timestamp": manifest_path.stat().st_mtime,
            }
        )
    entries.sort(key=lambda e: e["timestamp"], reverse=True)  # type: ignore[arg-type,return-value]
    return JSONResponse({"artifacts": entries})


async def api_artifacts_file(request: Request) -> JSONResponse | FileResponse:
    """Serve a single schematic render artifact (SVG/PNG) from the sandboxed render dir."""
    raw_path = request.query_params.get("path", "")
    if not raw_path:
        return JSONResponse({"error": "path query parameter is required"}, status_code=400)
    suffix = Path(raw_path).suffix.lower()
    media_type = _ARTIFACT_MIME_TYPES.get(suffix)
    if media_type is None:
        return JSONResponse(
            {"error": "Only .svg and .png artifacts can be served"}, status_code=400
        )
    render_dir = _schematic_render_dir()
    try:
        resolved = resolve_under(render_dir, raw_path, allow_absolute=True)
    except UnsafePathError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    if not resolved.is_file():
        return JSONResponse({"error": "Artifact not found"}, status_code=404)
    return FileResponse(resolved, media_type=media_type)


# ---------------------------------------------------------------------------
# Route definitions — list of Starlette Route objects for clean mounting
# ---------------------------------------------------------------------------

web_routes: list[Route] = [
    Route("/api/status", endpoint=api_status, methods=["GET"]),
    Route("/api/health", endpoint=api_health, methods=["GET"]),
    Route("/api/info", endpoint=api_info, methods=["GET"]),
    Route("/api/tools", endpoint=api_tools, methods=["GET"]),
    Route("/api/tools/{tool_name}/test", endpoint=api_tool_test, methods=["POST"]),
    Route("/api/config", endpoint=api_config_get, methods=["GET"]),
    Route("/api/config", endpoint=api_config_post, methods=["POST"]),
    Route("/api/config/export/{client}", endpoint=api_config_export, methods=["GET"]),
    Route("/api/metrics", endpoint=api_metrics, methods=["GET"]),
    Route("/api/server/{action}", endpoint=api_server_action, methods=["POST"]),
    Route("/api/logs/stream", endpoint=api_log_stream, methods=["GET"]),
    Route("/api/artifacts/schematic", endpoint=api_artifacts_schematic, methods=["GET"]),
    Route("/api/artifacts/file", endpoint=api_artifacts_file, methods=["GET"]),
    Route("/ui", endpoint=api_dashboard, methods=["GET"]),
    Route("/ui/", endpoint=api_dashboard, methods=["GET"]),
    Route("/api/dashboard", endpoint=api_dashboard, methods=["GET"]),
    Route("/", endpoint=api_dashboard, methods=["GET"]),
]

# Backward-compatible alias
router = web_routes
