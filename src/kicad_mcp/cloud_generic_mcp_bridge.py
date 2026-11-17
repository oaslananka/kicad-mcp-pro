"""Project-bound adapter to the EXISTING local MCP registry, not duplicated tools.

Only authenticated signed Connector sessions may construct this adapter.
Transport authorization and signed write-proof verification are separate.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

from mcp.client.session import ClientSession

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.operating_modes import OperatingMode, tool_required_mode
from kicad_mcp.tools.router import tools_for_profile

_MAX_TOOL_NAME = 128
_MAX_ARGUMENT_BYTES = 32_768
_MAX_RESULT_BYTES = 524_288
_DENIED = "local_mcp_operation_not_authorized"
_PROJECT_SWITCH_NAMES = frozenset(
    {
        "kicad_set_project",
        "kicad_create_new_project",
        "kicad_init",
        "project_set_project",
        "project_open",
    }
)
_UNSAFE_NAME_PARTS = ("manufactur", "mfg_", "jobset_", "signoff", "release_gate")


def is_generic_cloud_tool_safe(name: str) -> bool:
    """No cross-project switching, human manufacturing or experimental commands."""
    return (
        isinstance(name, str)
        and name not in _PROJECT_SWITCH_NAMES
        and not any(part in name for part in _UNSAFE_NAME_PARTS)
        and not name.startswith(("vcs_restore_", "project_import_", "pcb_import_"))
    )


def _safe_arguments(value: object, *, depth: int = 0) -> bool:
    """Reject remote paths that could target other files or other local projects.

    Existing KiCad tools still validate paths; this is an additional Cloud
    boundary that never guesses a filesystem folder from remote parameters.
    """
    if depth > 12:
        return False
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _safe_arguments(item, depth=depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_safe_arguments(item, depth=depth + 1) for item in value)
    if isinstance(value, str):
        if len(value) > 16_384 or "\x00" in value:
            return False
        if value.lower().startswith(("file:", "smb:", "ssh:", "ftp:")):
            return False
        path = value.replace("\\", "/")
        # Always prevent device/UNC roots, Windows drive paths and traversal;
        # a safe relative export inside the project may still be permitted.
        if re.search(r"(?i)(?:^|\s)[a-z]:/", path) or path.startswith(("//", "/")):
            return False
        if ".." in PurePosixPath(path).parts or ".." in PureWindowsPath(value).parts:
            return False
    return True


def _redact_private_paths(value: object, project_dir: str, home: str, depth: int = 0) -> object:
    """Do not disclose the Windows account path or local project root to Cloud."""
    if depth > 16:
        raise GenericMcpDeniedError(_DENIED)
    if isinstance(value, list):
        return [_redact_private_paths(v, project_dir, home, depth + 1) for v in value]
    if isinstance(value, dict):
        return {
            str(k): _redact_private_paths(v, project_dir, home, depth + 1) for k, v in value.items()
        }
    if isinstance(value, str):
        for prefix in (project_dir, project_dir.replace("\\", "/"), home, home.replace("\\", "/")):
            if prefix:
                value = value.replace(prefix, "[local-path]")
        return re.sub(
            r"(?i)(?:file://|[a-z]:[\\/]|\\\\[^\s\"<>]+)[^\s\"<>]*", "[local-path]", value
        )
    return value


class GenericMcpDeniedError(ValueError):
    """An operation is not in the owner-approved, project-scoped MCP surface."""


class GenericProjectMcpBridge:
    """Delegate to locally installed, project-scoped MCP without copying methods.

    This class is a local execution seam, NOT a public transport. A caller
    verifies Cloud OAuth, owner grants, authenticated device/session and (for
    mutations) a fresh signed single-use authorization before passing
    write_approved=True.
    """

    def __init__(
        self,
        *,
        verified: VerifiedLocalBinding,
        operator_project: OperatorProject,
        current_authorization: Callable[[], bool],
        allow_native_write: bool = False,
        now_ms: Callable[[], int] | None = None,
        profile: str = "expert",
    ) -> None:
        if (
            verified.device_id != operator_project.device_id
            or verified.project_id != operator_project.project_id
            or verified.operations != frozenset({"mcp_bridge"})
            or not callable(current_authorization)
            or type(allow_native_write) is not bool
            or profile not in {"expert", "review", "build", "default"}
        ):
            raise GenericMcpDeniedError(_DENIED)
        self._verified = verified
        self._project = operator_project
        self._authorized = current_authorization
        self._now = now_ms if now_ms is not None else lambda: time.time_ns() // 1_000_000
        self._write = allow_native_write
        self.profile = profile
        self._registered = frozenset(tools_for_profile(profile))

    def assert_current(self, project_id: str, session_id: str) -> None:
        try:
            if (
                project_id != self._verified.project_id
                or session_id != self._verified.session_id
                or type(self._now()) is not int
                or not 0 < self._now() < self._verified.session_expires_unix_ms
                or self._authorized() is not True
            ):
                raise GenericMcpDeniedError(_DENIED)
        except Exception as exc:
            raise GenericMcpDeniedError(_DENIED) from exc

    def _access_mode(self, name: str) -> str:
        if (
            not isinstance(name, str)
            or len(name) > _MAX_TOOL_NAME
            or name not in self._registered
            or not is_generic_cloud_tool_safe(name)
        ):
            raise GenericMcpDeniedError(_DENIED)
        required = tool_required_mode(name)
        if required == OperatingMode.READONLY:
            return "readonly"
        if required == OperatingMode.WRITE:
            return "write"
        # HUMAN_ONLY, manufacturing, experimental and unknown modes are
        # deliberately not transferable through general Cloud authority.
        raise GenericMcpDeniedError(_DENIED)

    async def list_tools(
        self, session: ClientSession, *, project_id: str, session_id: str
    ) -> list[dict[str, object]]:
        self.assert_current(project_id, session_id)
        result = await session.list_tools()
        tools: list[dict[str, object]] = []
        for tool in result.tools:
            try:
                mode = self._access_mode(tool.name)
            except GenericMcpDeniedError:
                continue
            if mode == "write" and not self._write:
                continue
            item: dict[str, object] = {
                "name": tool.name,
                "description": (tool.description or "")[:2048],
                "inputSchema": tool.input_schema,
                "accessMode": mode,
            }
            if len(json.dumps(item, ensure_ascii=False, default=str).encode("utf-8")) <= 32_768:
                tools.append(item)
        self.assert_current(project_id, session_id)
        return tools

    async def call_tool(
        self,
        session: ClientSession,
        *,
        project_id: str,
        session_id: str,
        name: str,
        arguments: dict[str, object],
        write_approved: bool,
        not_after_unix_ms: int | None = None,
    ) -> dict[str, object]:
        self.assert_current(project_id, session_id)
        mode = self._access_mode(name)
        if mode == "write" and (not self._write or write_approved is not True):
            raise GenericMcpDeniedError(_DENIED)
        if not isinstance(arguments, dict) or not _safe_arguments(arguments):
            raise GenericMcpDeniedError(_DENIED)
        try:
            encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise GenericMcpDeniedError(_DENIED) from exc
        if len(encoded.encode("utf8")) > _MAX_ARGUMENT_BYTES:
            raise GenericMcpDeniedError(_DENIED)
        # Tool is retrieved from *this local worker's* registered surface, not
        # from untrusted metadata sent by Cloud.
        catalog = await self.list_tools(session, project_id=project_id, session_id=session_id)
        if not any(item["name"] == name for item in catalog):
            raise GenericMcpDeniedError(_DENIED)
        self.assert_current(project_id, session_id)
        if mode == "write" and (
            type(not_after_unix_ms) is not int or self._now() >= not_after_unix_ms
        ):
            raise GenericMcpDeniedError("signed_mcp_write_deadline_expired")
        result = await session.call_tool(name, arguments=arguments)
        self.assert_current(project_id, session_id)
        raw_data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        data = _redact_private_paths(raw_data, str(self._project.directory), str(Path.home()))
        if not isinstance(data, dict):
            raise GenericMcpDeniedError(_DENIED)
        if (
            len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf8"))
            > _MAX_RESULT_BYTES
        ):
            raise GenericMcpDeniedError("local_mcp_result_too_large")
        return data
