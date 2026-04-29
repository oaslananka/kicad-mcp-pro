"""KiCad MCP Pro server entrypoint."""
# mypy: disable-error-code=untyped-decorator

from __future__ import annotations

import asyncio
import contextlib
import inspect
import io
import json
import os
import secrets
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any, Protocol, cast

import anyio
import click
import structlog
import typer
from mcp import types as mcp_types
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Icon, ToolAnnotations
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from typer.models import OptionInfo

from . import __version__
from .config import KiCadMCPConfig, get_config, reset_config
from .connection import KiCadConnectionError, get_board
from .diagnostics import DiagnosticReport, build_doctor_report, build_health_report
from .discovery import ensure_studio_project_watcher, find_kicad_version
from .tools import router
from .tools.fixers import validate_callable_imports
from .tools.metadata import infer_tool_annotations
from .tools.router import EXPERIMENTAL_TOOL_NAMES, available_profiles, categories_for_profile
from .utils.logging import setup_logging
from .wellknown import get_wellknown_metadata

logger = structlog.get_logger(__name__)
app = typer.Typer(help="KiCad MCP Pro server for PCB and schematic workflows.")
AnyFunction = Callable[..., object]


class _LazyRegistrationServer(Protocol):
    def start_lazy_registration_background(self) -> None:
        """Start deferred MCP surface registration."""
        raise NotImplementedError


HEAVY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "run_drc",
        "run_erc",
        "validate_design",
        "schematic_quality_gate",
        "schematic_connectivity_gate",
        "pcb_quality_gate",
        "pcb_placement_quality_gate",
        "pcb_transfer_quality_gate",
        "manufacturing_quality_gate",
        "project_quality_gate",
        "project_quality_gate_report",
        "project_auto_fix_loop",
        "project_full_validation_loop",
        "check_design_for_manufacture",
        "export_gerber",
        "export_drill",
        "export_bom",
        "export_netlist",
        "export_spice_netlist",
        "export_pcb_pdf",
        "export_sch_pdf",
        "export_3d_step",
        "export_step",
        "pcb_export_3d_pdf",
        "export_3d_render",
        "export_pick_and_place",
        "export_ipc2581",
        "export_svg",
        "export_dxf",
        "get_board_stats",
        "export_manufacturing_package",
        "route_export_dsn",
        "route_autoroute_freerouting",
        "route_import_ses",
        "route_tune_time_domain",
    }
)
CLI_FAILURE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "run_drc",
        "run_erc",
        "export_gerber",
        "export_drill",
        "export_bom",
        "export_netlist",
        "export_spice_netlist",
        "export_pcb_pdf",
        "export_sch_pdf",
        "export_3d_step",
        "export_step",
        "pcb_export_3d_pdf",
        "export_3d_render",
        "export_pick_and_place",
        "export_ipc2581",
        "export_svg",
        "export_dxf",
        "get_board_stats",
        "route_export_dsn",
        "route_autoroute_freerouting",
        "route_import_ses",
    }
)
_TOOL_LIMITERS: dict[str, anyio.CapacityLimiter] = {}
_TOOL_LIMITERS_LOCK = threading.Lock()
_METRICS_LOCK = threading.Lock()
_TOOL_CALL_COUNTS: dict[tuple[str, str], int] = {}
_TOOL_LATENCIES_MS: dict[str, deque[float]] = {}


def _tool_limiter(tool_name: str) -> anyio.CapacityLimiter | None:
    if tool_name not in HEAVY_TOOL_NAMES:
        return None
    with _TOOL_LIMITERS_LOCK:
        limiter = _TOOL_LIMITERS.get(tool_name)
        if limiter is None:
            limiter = anyio.CapacityLimiter(2)
            _TOOL_LIMITERS[tool_name] = limiter
        return limiter


def _record_tool_metric(tool_name: str, status: str, elapsed_ms: float) -> None:
    with _METRICS_LOCK:
        key = (tool_name, status)
        _TOOL_CALL_COUNTS[key] = _TOOL_CALL_COUNTS.get(key, 0) + 1
        samples = _TOOL_LATENCIES_MS.setdefault(tool_name, deque(maxlen=256))
        samples.append(elapsed_ms)


def _percentile(samples: deque[float], percentile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _clean_tool_error(exc: BaseException) -> str:
    message = str(exc)
    prefix = "Error executing tool "
    if message.startswith(prefix) and ": " in message:
        return message.split(": ", 1)[1]
    return message


def _tool_error_code(message: str, *, tool_name: str = "") -> str:
    lowered = message.casefold()
    if "timed out" in lowered or "timeout" in lowered:
        return "CLI_TIMEOUT"
    if "kicad-cli" in lowered:
        return "CLI_UNAVAILABLE"
    if "manufacturing export blocked" in lowered or "quality gate" in lowered:
        return "VALIDATION_FAILED"
    if (
        "no pcb file" in lowered
        or "no schematic file" in lowered
        or "invalid output path" in lowered
    ):
        return "CONFIGURATION_ERROR"
    if tool_name in CLI_FAILURE_TOOL_NAMES:
        return "CLI_COMMAND_FAILED"
    return "TOOL_EXECUTION_FAILED"


def _tool_error_hint(message: str) -> str:
    lowered = message.casefold()
    if "no pcb file" in lowered or "no schematic file" in lowered:
        return "Call kicad_set_project() or set the relevant KICAD_MCP_*_FILE variable."
    if "kicad-cli" in lowered:
        return "Install KiCad or set KICAD_MCP_KICAD_CLI to the kicad-cli executable."
    if "quality gate" in lowered or "hard-blocked" in lowered:
        return "Read kicad://project/fix_queue, resolve blocking gate issues, then rerun the tool."
    if "unknown tool" in lowered:
        return "Check kicad_list_tool_categories() and kicad_get_tools_in_category()."
    return "Inspect the structured error and retry after correcting the request or project state."


def _structured_tool_error_from_message(
    message: str,
    *,
    tool_name: str = "",
) -> mcp_types.CallToolResult:
    code = _tool_error_code(message, tool_name=tool_name)
    payload = {
        "error_code": code,
        "message": message,
        "hint": _tool_error_hint(message),
    }
    return mcp_types.CallToolResult(
        isError=True,
        structuredContent=payload,
        content=[
            mcp_types.TextContent(
                type="text",
                text=(f"{payload['error_code']}: {payload['message']}\nHint: {payload['hint']}"),
            )
        ],
    )


def _structured_tool_error(exc: BaseException, *, tool_name: str = "") -> mcp_types.CallToolResult:
    return _structured_tool_error_from_message(_clean_tool_error(exc), tool_name=tool_name)


def _result_text(result: object) -> str:
    if isinstance(result, mcp_types.CallToolResult):
        return _result_text(result.content)
    if isinstance(result, list):
        return "\n".join(
            str(getattr(item, "text", item))
            for item in result
            if getattr(item, "text", item) is not None
        )
    if isinstance(result, tuple) and result:
        return _result_text(result[0])
    return str(result)


def _tool_failure_message(tool_name: str, result: object) -> str | None:
    text = _result_text(result).strip()
    lowered = text.casefold()
    first_line = lowered.splitlines()[0] if lowered else ""
    if tool_name == "export_manufacturing_package" and lowered.startswith(
        "manufacturing export blocked"
    ):
        return text
    if tool_name == "export_manufacturing_package" and (
        "hard-blocked" in lowered or "project quality gate: fail" in lowered
    ):
        return text
    if tool_name in CLI_FAILURE_TOOL_NAMES and (
        " failed:" in lowered or " failed." in lowered or " is unavailable:" in lowered
    ):
        return text
    if (
        " failed:" in first_line
        or first_line.endswith(" failed.")
        or " is unavailable:" in first_line
        or first_line.startswith("invalid output path:")
    ):
        return text
    return None


def _status_from_result(result: object) -> tuple[str, str | None]:
    if isinstance(result, mcp_types.CallToolResult) and result.isError:
        structured = result.structuredContent or {}
        return "error", str(structured.get("error_code", "TOOL_ERROR"))
    return "ok", None


def _audit_tool_call(
    *,
    tool_name: str,
    arguments: dict[str, object],
    status: str,
    elapsed_ms: float,
    error_code: str | None,
) -> None:
    if get_config().transport == "stdio":
        return
    logger.info(
        "tool_call_audit",
        tool=tool_name,
        status=status,
        duration_ms=round(elapsed_ms, 3),
        argument_keys=sorted(arguments),
        error_code=error_code,
    )


class _SyncServerHandle:
    """Compatibility wrapper that exposes sync-friendly discovery helpers."""

    def __init__(self, server: FastMCP) -> None:
        self._server = server

    def list_tools(self) -> object:
        """Return tool metadata synchronously when called outside an event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._server.list_tools())
        sync_list = getattr(self._server, "list_tools_sync", None)
        if callable(sync_list):
            return sync_list()

        result: list[object] = []
        error: BaseException | None = None

        def _runner() -> None:
            nonlocal result, error
            try:
                result = list(asyncio.run(self._server.list_tools()))
            except Exception as exc:  # pragma: no cover - defensive bridge
                error = exc

        thread = threading.Thread(target=_runner, name="kicad-mcp-list-tools", daemon=True)
        thread.start()
        thread.join()
        if error is not None:
            raise error
        return result

    def __getattr__(self, name: str) -> object:
        return getattr(self._server, name)


class _StaticTokenVerifier:
    """Simple bearer-token verifier for local HTTP bridge deployments."""

    def __init__(self, expected_token: str) -> None:
        self._expected_token = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token, self._expected_token):
            return AccessToken(token=token, client_id="kicad-studio", scopes=["mcp"])
        return None

    def rotate(self, token: str) -> None:
        """Replace the accepted bearer token without restarting the server."""
        self._expected_token = token


class KiCadFastMCP(FastMCP):
    """FastMCP extension that auto-infers tool annotations and adds CORS support."""

    allow_experimental_tools: bool = False
    allowed_tool_names: set[str] | None = None
    _lazy_registration: Callable[[], None] | None = None
    _lazy_registration_complete: bool = False
    _lazy_registration_error: BaseException | None = None
    _lazy_registration_lock: threading.Lock
    _lazy_registration_thread: threading.Thread | None = None

    def set_lazy_registration(self, register: Callable[[], None]) -> None:
        """Defer heavy tool/resource registration until after stdio initialize can bind."""
        self._lazy_registration = register
        self._lazy_registration_complete = False
        self._lazy_registration_error = None
        self._lazy_registration_lock = threading.Lock()
        self._lazy_registration_thread = None

    def start_lazy_registration_background(self) -> None:
        """Begin deferred registration without blocking process startup."""
        if self._lazy_registration is None or self._lazy_registration_complete:
            return
        if getattr(self, "_lazy_registration_thread", None) is not None:
            return

        thread = threading.Thread(
            target=self.ensure_registered,
            name="kicad-mcp-register-tools",
            daemon=True,
        )
        self._lazy_registration_thread = thread
        thread.start()

    def ensure_registered(self) -> None:
        """Materialize deferred tools, resources, and prompts exactly once."""
        register = self._lazy_registration
        if register is None:
            return
        if self._lazy_registration_complete:
            return
        lock = getattr(self, "_lazy_registration_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._lazy_registration_lock = lock
        with lock:
            if self._lazy_registration_complete:
                return
            if self._lazy_registration_error is not None:
                raise self._lazy_registration_error
            try:
                register()
            except Exception as exc:
                self._lazy_registration_error = exc
                raise
            self._lazy_registration_complete = True

    async def _ensure_registered_async(self) -> None:
        await anyio.to_thread.run_sync(self.ensure_registered)

    def tool(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, object] | None = None,
        structured_output: bool | None = None,
    ) -> Callable[[AnyFunction], AnyFunction]:
        def decorator(func: AnyFunction) -> AnyFunction:
            merged = infer_tool_annotations(name or func.__name__, explicit=annotations)
            published_description = description
            if published_description is None:
                published_description = inspect.getdoc(func) or None
            if published_description is not None:
                words = [word for word in published_description.replace("-", " ").split() if word]
                if len(words) < 10:
                    published_description = (
                        f"{published_description.rstrip()} This KiCad MCP Pro tool "
                        "supports production EDA automation workflows for MCP clients."
                    )
            return super(KiCadFastMCP, self).tool(
                name=name,
                title=title,
                description=published_description,
                annotations=merged or None,
                icons=icons,
                meta=meta,
                structured_output=structured_output,
            )(func)

        return decorator

    def _filter_tools(self, tools: list[mcp_types.Tool]) -> list[mcp_types.Tool]:
        allowed_tool_names = getattr(self, "allowed_tool_names", None)
        if allowed_tool_names is not None:
            tools = [tool for tool in tools if tool.name in allowed_tool_names]
        if (
            getattr(self, "allow_experimental_tools", False)
            or get_config().enable_experimental_tools
        ):
            return tools
        return [
            tool for tool in tools if getattr(tool, "name", None) not in EXPERIMENTAL_TOOL_NAMES
        ]

    def list_tools_sync(self) -> list[mcp_types.Tool]:
        """List filtered tools without needing to drive an asyncio event loop."""
        self.ensure_registered()
        tools = self._tool_manager.list_tools()
        rendered = [
            mcp_types.Tool(
                name=info.name,
                title=info.title,
                description=info.description,
                inputSchema=info.parameters,
                outputSchema=info.output_schema,
                annotations=info.annotations,
                icons=info.icons,
                _meta=info.meta,
            )
            for info in tools
        ]
        return self._filter_tools(rendered)

    def streamable_http_app(self) -> Starlette:
        app = super().streamable_http_app()
        cfg = get_config()
        if cfg.legacy_sse:
            sse_routes = self.sse_app().routes
            existing_paths = {getattr(route, "path", None) for route in app.routes}
            for route in sse_routes:
                route_path = getattr(route, "path", None)
                if route_path in {"/sse", "/messages"} and route_path not in existing_paths:
                    app.routes.append(route)
                    existing_paths.add(route_path)
        origins = cfg.cors_origin_list
        if origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "MCP-Protocol-Version",
                    "MCP-Session-Id",
                ],
            )
            app.add_middleware(_OriginValidationMiddleware)
        return app

    async def list_tools(self) -> list[mcp_types.Tool]:
        """Hide experimental tools from discovery unless explicitly enabled."""
        await self._ensure_registered_async()
        tools = await super().list_tools()
        return self._filter_tools(tools)

    async def list_resources(self) -> list[mcp_types.Resource]:
        """Materialize resources before discovery when stdio startup was deferred."""
        await self._ensure_registered_async()
        return await super().list_resources()

    async def list_resource_templates(self) -> list[mcp_types.ResourceTemplate]:
        """Materialize resource templates before discovery when startup was deferred."""
        await self._ensure_registered_async()
        return await super().list_resource_templates()

    async def read_resource(self, uri: AnyUrl | str) -> Iterable[ReadResourceContents]:
        """Materialize resources before reading them when startup was deferred."""
        await self._ensure_registered_async()
        return await super().read_resource(uri)

    async def list_prompts(self) -> list[mcp_types.Prompt]:
        """Materialize prompts before discovery when stdio startup was deferred."""
        await self._ensure_registered_async()
        return await super().list_prompts()

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> mcp_types.GetPromptResult:
        """Materialize prompts before rendering them when startup was deferred."""
        await self._ensure_registered_async()
        return await super().get_prompt(name, arguments)

    async def call_tool(  # type: ignore[override]
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> object:
        """Call a tool with metrics, audit logging, rate limits, and structured errors."""
        started = time.perf_counter()
        status = "ok"
        error_code: str | None = None
        limiter = _tool_limiter(name)
        result: object
        try:
            await self._ensure_registered_async()
            if limiter is None:
                result = await super().call_tool(name, arguments)
            else:
                async with limiter:
                    result = await super().call_tool(name, arguments)
            failure_message = _tool_failure_message(name, result)
            if failure_message is not None:
                result = _structured_tool_error_from_message(failure_message, tool_name=name)
            status, error_code = _status_from_result(result)
            return result
        except ToolError as exc:
            result = _structured_tool_error(exc, tool_name=name)
            status, error_code = _status_from_result(result)
            return result
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            _record_tool_metric(name, status, elapsed_ms)
            _audit_tool_call(
                tool_name=name,
                arguments=arguments,
                status=status,
                elapsed_ms=elapsed_ms,
                error_code=error_code,
            )


class _OriginValidationMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin POST requests that are not on the configured allowlist."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        cfg = get_config()
        if (
            cfg.auth_token
            and request.method.upper() == "POST"
            and request.url.path == cfg.mount_path
        ):
            origin = request.headers.get("origin")
            if origin and origin not in cfg.cors_origin_list:
                return PlainTextResponse("Origin not allowed for this MCP server.", status_code=403)
        return await call_next(request)


def _server_base_url(cfg: KiCadMCPConfig) -> str:
    host = cfg.host if cfg.host not in {"0.0.0.0", "::"} else "127.0.0.1"  # noqa: S104
    return f"http://{host}:{cfg.port}"


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return ""
    return authorization[len(prefix) :].strip()


def _prometheus_metrics_payload() -> str:
    lines = [
        "# HELP kicad_mcp_tool_calls_total Total MCP tool calls observed by this process.",
        "# TYPE kicad_mcp_tool_calls_total counter",
    ]
    with _METRICS_LOCK:
        if not _TOOL_CALL_COUNTS:
            lines.append('kicad_mcp_tool_calls_total{tool="none",status="none"} 0')
        for (tool, status), count in sorted(_TOOL_CALL_COUNTS.items()):
            lines.append(
                "kicad_mcp_tool_calls_total"
                f'{{tool="{_label_value(tool)}",status="{_label_value(status)}"}} {count}'
            )

        lines.extend(
            [
                "# HELP kicad_mcp_tool_latency_p50_ms Sliding-window p50 tool latency in ms.",
                "# TYPE kicad_mcp_tool_latency_p50_ms gauge",
            ]
        )
        for tool, samples in sorted(_TOOL_LATENCIES_MS.items()):
            lines.append(
                "kicad_mcp_tool_latency_p50_ms"
                f'{{tool="{_label_value(tool)}"}} {_percentile(samples, 0.50):.3f}'
            )
        lines.extend(
            [
                "# HELP kicad_mcp_tool_latency_p95_ms Sliding-window p95 tool latency in ms.",
                "# TYPE kicad_mcp_tool_latency_p95_ms gauge",
            ]
        )
        for tool, samples in sorted(_TOOL_LATENCIES_MS.items()):
            lines.append(
                "kicad_mcp_tool_latency_p95_ms"
                f'{{tool="{_label_value(tool)}"}} {_percentile(samples, 0.95):.3f}'
            )
    lines.extend(
        [
            "# HELP kicad_mcp_active_sessions Active Streamable HTTP sessions.",
            "# TYPE kicad_mcp_active_sessions gauge",
            "kicad_mcp_active_sessions 0",
            "",
        ]
    )
    return "\n".join(lines)


def _register_profile_components(
    server: KiCadFastMCP,
    enabled: set[str],
    cfg: KiCadMCPConfig,
) -> None:
    """Register all profile-specific MCP surfaces on an already-created server."""
    from .prompts import workflows
    from .resources import board_state, studio_context
    from .tools import (
        dfm,
        emc_compliance,
        export,
        library,
        manufacturing,
        pcb,
        power_integrity,
        project,
        routing,
        schematic,
        signal_integrity,
        simulation,
        validation,
        variants,
        version_control,
    )

    validate_callable_imports()

    router.register(server)
    project.register(server)

    if "pcb_read" in enabled or "pcb_write" in enabled:
        pcb.register(server)
    if "schematic" in enabled:
        schematic.register(server)
        variants.register(server)
    if "library" in enabled:
        library.register(server)
    if "export" in enabled or "release_export" in enabled:
        export.register(server, include_low_level_exports="export" in enabled)
    if "validation" in enabled:
        validation.register(server)
    if "dfm" in enabled:
        dfm.register(server)
    if "routing" in enabled:
        routing.register(server)
    if "power_integrity" in enabled:
        power_integrity.register(server)
    if "emc" in enabled:
        emc_compliance.register(server)
    if "signal_integrity" in enabled:
        signal_integrity.register(server)
    if "simulation" in enabled:
        simulation.register(server)
    if "version_control" in enabled:
        version_control.register(server)
    if "manufacturing" in enabled:
        manufacturing.register(server)

    board_state.register(server)
    studio_context.register(server)
    workflows.register(server)

    if cfg.studio_watch_dir is not None:
        ensure_studio_project_watcher(cfg.studio_watch_dir)


def build_server(profile: str | None = None, *, defer_registration: bool = False) -> FastMCP:
    """Build a FastMCP server instance for the active profile."""
    cfg = get_config()
    selected_profile = profile or cfg.profile
    enabled = set(categories_for_profile(selected_profile))
    token_verifier = _StaticTokenVerifier(cfg.auth_token) if cfg.auth_token else None
    auth = None
    if cfg.auth_token:
        base_url = _server_base_url(cfg)
        auth = AuthSettings(
            issuer_url=base_url,
            resource_server_url=base_url,
            required_scopes=["mcp"],
        )

    server = KiCadFastMCP(
        name="kicad-mcp-pro",
        instructions=(
            "KiCad MCP Pro Server for project setup, schematic capture, PCB editing, "
            "validation, and manufacturing export. Start with kicad_get_version(), "
            "kicad_set_project(), and project_get_design_spec()."
        ),
        website_url="https://oaslananka.github.io/kicad-mcp-pro",
        host=cfg.host,
        port=cfg.port,
        streamable_http_path=cfg.mount_path,
        mount_path=cfg.mount_path,
        log_level=cfg.log_level,
        json_response=True,
        stateless_http=not cfg.stateful_http,
        auth=auth,
        token_verifier=token_verifier,
    )
    server.allow_experimental_tools = selected_profile == "agent_full"
    server.allowed_tool_names = {
        tool_name for category in enabled for tool_name in router.TOOL_CATEGORIES[category]["tools"]
    }

    @server.custom_route("/.well-known/mcp-server", methods=["GET"], include_in_schema=False)
    async def _well_known_mcp(_request: Request) -> JSONResponse:
        return JSONResponse(get_wellknown_metadata())

    @server.custom_route("/well-known/mcp-server", methods=["GET"], include_in_schema=False)
    async def _well_known_mcp_compat(_request: Request) -> JSONResponse:
        return JSONResponse(get_wellknown_metadata())

    @server.custom_route(
        "/.well-known/mcp-server/token-rotate",
        methods=["POST"],
        include_in_schema=False,
    )
    async def _rotate_token(request: Request) -> JSONResponse:
        if token_verifier is None or not cfg.auth_token:
            return JSONResponse({"error": "Bearer token auth is not enabled."}, status_code=404)
        token = _bearer_token(request)
        if await token_verifier.verify_token(token) is None:
            return JSONResponse({"error": "Unauthorized."}, status_code=401)
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "Request body must be JSON."}, status_code=400)
        raw_token = payload.get("new_token") if isinstance(payload, dict) else None
        new_token = raw_token.strip() if isinstance(raw_token, str) else ""
        if not new_token:
            return JSONResponse({"error": "new_token must be a non-empty string."}, status_code=400)
        cfg.auth_token = new_token
        token_verifier.rotate(new_token)
        return JSONResponse({"rotated": True})

    if cfg.enable_metrics:

        @server.custom_route("/metrics", methods=["GET"], include_in_schema=False)
        async def _metrics(_request: Request) -> PlainTextResponse:
            return PlainTextResponse(
                _prometheus_metrics_payload(),
                media_type="text/plain; version=0.0.4",
            )

    def register() -> None:
        _register_profile_components(server, enabled, cfg)

    if defer_registration:
        server.set_lazy_registration(register)
    else:
        register()

    return server


def create_server(profile: str | None = None) -> _SyncServerHandle:
    """Backward-compatible helper used by benchmark and verification scripts."""
    return _SyncServerHandle(build_server(profile))


def _ipc_status_summary() -> str:
    try:
        get_board()
    except KiCadConnectionError as exc:
        return f"unavailable ({str(exc).splitlines()[0]})"
    return "connected (PCB editor available)"


def _print_startup_diagnostics(cfg: KiCadMCPConfig, *, probe_runtime: bool = True) -> None:
    """Emit a concise startup summary without writing directly to stdio transport."""
    if cfg.transport == "stdio" and cfg.auth_token:
        logger.warning(
            "stdio_auth_token_ignored",
            message="KICAD_MCP_AUTH_TOKEN has no effect when the server runs over stdio.",
        )
    kicad_version = "deferred" if not probe_runtime else find_kicad_version(cfg.kicad_cli)
    ipc_status = "deferred" if not probe_runtime else _ipc_status_summary()
    logger.info(
        "startup_diagnostics",
        profile=cfg.profile,
        kicad_cli=str(cfg.kicad_cli),
        kicad_version=kicad_version or "unknown",
        project_dir=str(cfg.project_dir) if cfg.project_dir else None,
        gate_mode="release-export-only",
        ipc_status=ipc_status,
    )


def _apply_cli_env(
    transport: str | None = None,
    host: str | None = None,
    port: int | None = None,
    project_dir: str | None = None,
    log_level: str | None = None,
    log_format: str | None = None,
    profile: str | None = None,
    experimental: bool | None = None,
) -> None:
    cli_env = {
        "KICAD_MCP_TRANSPORT": transport,
        "KICAD_MCP_HOST": host,
        "KICAD_MCP_PORT": (
            str(port) if port is not None and not isinstance(port, OptionInfo) else None
        ),
        "KICAD_MCP_LOG_LEVEL": log_level,
        "KICAD_MCP_LOG_FORMAT": log_format,
        "KICAD_MCP_PROFILE": profile,
        "KICAD_MCP_PROJECT_DIR": project_dir,
    }
    for key, value in cli_env.items():
        if value is not None and not isinstance(value, OptionInfo):
            os.environ[key] = value
    if experimental is not None and not isinstance(experimental, OptionInfo):
        os.environ["KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS"] = "true" if experimental else "false"


def _run_server_from_options(
    *,
    transport: str | None = None,
    host: str | None = None,
    port: int | None = None,
    project_dir: str | None = None,
    log_level: str | None = None,
    log_format: str | None = None,
    profile: str | None = None,
    experimental: bool | None = None,
) -> None:
    """Apply CLI overrides and start the MCP server."""
    _apply_cli_env(
        transport=transport,
        host=host,
        port=port,
        project_dir=project_dir,
        log_level=log_level,
        log_format=log_format,
        profile=profile,
        experimental=experimental,
    )
    reset_config()
    cfg = get_config()
    setup_logging(cfg.log_level, cfg.log_format)

    selected_transport = "stdio" if cfg.transport == "stdio" else "streamable-http"
    if cfg.transport == "sse":
        if cfg.legacy_sse:
            selected_transport = "sse"
            logger.warning(
                "legacy_sse_enabled",
                message="Legacy SSE transport is enabled for backward compatibility.",
            )
        else:
            logger.warning(
                "legacy_sse_disabled",
                message="Ignoring KICAD_MCP_TRANSPORT=sse because KICAD_MCP_LEGACY_SSE is false.",
            )
    defer_registration = selected_transport == "stdio"
    server = build_server(cfg.profile, defer_registration=defer_registration)
    _print_startup_diagnostics(cfg, probe_runtime=not defer_registration)
    logger.info(
        "starting_kicad_mcp_pro",
        version=__version__,
        transport=selected_transport,
        profile=cfg.profile,
    )

    if selected_transport == "stdio":
        if hasattr(server, "start_lazy_registration_background"):
            cast(_LazyRegistrationServer, server).start_lazy_registration_background()
        server.run(transport="stdio")
        return

    if selected_transport == "sse":
        server.run(transport="sse", mount_path=cfg.mount_path)
        return

    server.run(transport="streamable-http", mount_path=cfg.mount_path)


@app.callback(invoke_without_command=True)
def main_callback(
    transport: str | None = typer.Option(None, help="Transport: stdio, http, sse, streamable-http"),
    host: str | None = typer.Option(None, help="HTTP bind host"),
    port: int | None = typer.Option(None, help="HTTP bind port"),
    project_dir: str | None = typer.Option(None, help="Active KiCad project directory"),
    log_level: str | None = typer.Option(None, help="Log level"),
    log_format: str | None = typer.Option(None, help="Log format: console or json"),
    profile: str | None = typer.Option(
        None, help=f"Server profile: {', '.join(available_profiles())}"
    ),
    experimental: bool | None = typer.Option(None, help="Enable experimental tools"),
) -> None:
    """Start the KiCad MCP Pro server when no subcommand is supplied."""
    _apply_cli_env(
        transport=transport,
        host=host,
        port=port,
        project_dir=project_dir,
        log_level=log_level,
        log_format=log_format,
        profile=profile,
        experimental=experimental,
    )
    current_context = click.get_current_context(silent=True)
    if current_context is not None and current_context.invoked_subcommand is not None:
        return
    _run_server_from_options()


@app.command()
def serve(
    transport: str | None = typer.Option(None, help="Transport: stdio, http, sse, streamable-http"),
    host: str | None = typer.Option(None, help="HTTP bind host"),
    port: int | None = typer.Option(None, help="HTTP bind port"),
    project_dir: str | None = typer.Option(None, help="Active KiCad project directory"),
    log_level: str | None = typer.Option(None, help="Log level"),
    log_format: str | None = typer.Option(None, help="Log format: console or json"),
    profile: str | None = typer.Option(
        None, help=f"Server profile: {', '.join(available_profiles())}"
    ),
    experimental: bool | None = typer.Option(None, help="Enable experimental tools"),
) -> None:
    """Start the MCP server explicitly."""
    _run_server_from_options(
        transport=transport,
        host=host,
        port=port,
        project_dir=project_dir,
        log_level=log_level,
        log_format=log_format,
        profile=profile,
        experimental=experimental,
    )


def _echo_report(report: DiagnosticReport, *, as_json: bool) -> None:
    if as_json:
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(f"Status: {report.status}")
    for check in report.checks:
        suffix = f" Hint: {check.hint}" if check.hint else ""
        typer.echo(f"- {check.name}: {check.status} - {check.message}{suffix}")


def _diagnostic_command(builder: Callable[[], DiagnosticReport], *, as_json: bool) -> None:
    try:
        if as_json:
            with contextlib.redirect_stdout(io.StringIO()):
                report = builder()
        else:
            report = builder()
    except Exception as exc:
        payload = {
            "ok": False,
            "status": "error",
            "error": {
                "code": "CONFIGURATION_ERROR",
                "message": str(exc),
                "hint": "Fix malformed KiCad MCP configuration and retry.",
                "retryable": False,
            },
        }
        error = cast(dict[str, object], payload["error"])
        typer.echo(json.dumps(payload, indent=2) if as_json else str(error["message"]))
        raise typer.Exit(2) from exc
    _echo_report(report, as_json=as_json)
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def health(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Report fast package and configuration health without requiring KiCad IPC."""
    _diagnostic_command(build_health_report, as_json=json_output)


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run deeper diagnostics without treating unavailable KiCad as fatal."""
    _diagnostic_command(build_doctor_report, as_json=json_output)


@app.command("version")
def version_command(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Print package version information."""
    with contextlib.redirect_stdout(io.StringIO()):
        cfg = get_config()
    payload = {
        "package": {"name": "kicad-mcp-pro", "version": __version__},
        "mcp": {"transport_default": cfg.transport, "profile": cfg.profile},
        "python": {"version": sys.version.split()[0]},
    }
    typer.echo(json.dumps(payload, indent=2) if json_output else __version__)


def main() -> None:
    """CLI entrypoint used by the package script."""
    app()


if __name__ == "__main__":
    main()
