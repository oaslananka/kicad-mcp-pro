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
# The MCP SDK's default local read timeout is shorter than real KiCad DRC/ ERC.
# Keep this below the Cloud's 75-second overall deadline, including startup.
_LONG_READ_MCP_TOOLS = frozenset({"run_drc", "run_erc"})
_LONG_READ_MCP_TIMEOUT_SECONDS = 70.0
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


def _safe_string_argument(value: str) -> bool:
    if len(value) > 16_384 or "\x00" in value:
        return False
    value = value.strip()
    if value.lower().startswith(("file:", "smb:", "ssh:", "ftp:")):
        return False
    path = value.replace("\\", "/")
    # Never allow device/UNC roots, Windows drive paths or path traversal.
    if re.search(r"(?i)(?:^|\s)[a-z]:", path) or path.startswith(("//", "/")):
        return False
    return ".." not in PurePosixPath(path).parts and ".." not in PureWindowsPath(value).parts


# Only reviewed arguments whose implementation performs a net lookup/filter,
# never a filesystem operation, may carry absolute-looking KiCad net names.
_HIERARCHICAL_NET_ARGUMENTS = {
    "pcb_get_tracks": "filter_net",
    "pcb_add_track": "net_name",
    "pcb_add_track_segment": "net_name",
    "pcb_add_via": "net_name",
}


def _safe_hierarchical_net(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 16_384
        and value.startswith("/")
        and value == value.strip()
        and ":" not in value
        and "\\" not in value
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
        and all(part not in {"", ".", ".."} for part in value[1:].split("/"))
    )


def _safe_arguments(value: object, *, depth: int = 0, tool_name: str = "") -> bool:
    """Fail closed on remote paths and unbounded recursion."""
    if depth > 12:
        return False
    if isinstance(value, dict):
        return all(
            isinstance(key, str)
            and (
                _safe_arguments(item, depth=depth + 1)
                or (
                    depth == 0
                    and key == _HIERARCHICAL_NET_ARGUMENTS.get(tool_name)
                    and _safe_hierarchical_net(item)
                )
            )
            for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_safe_arguments(item, depth=depth + 1) for item in value)
    if isinstance(value, str):
        return _safe_string_argument(value)
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


def _compact_redundant_json_before_redaction(data: dict[str, object]) -> dict[str, object]:
    """Avoid interpreting escaped JSON formatting as local Windows paths.

    Some MCP servers duplicate structured findings in a serialized text item.
    Compare their unmodified values *before* path redaction, then preserve the
    whole structured result and replace only proven-identical redundant text.
    """
    if len(json.dumps(data, ensure_ascii=False).encode("utf8")) <= 60_000:
        return data
    structured = data.get("structuredContent")
    items = data.get("content")
    if not isinstance(structured, dict) or not isinstance(items, list) or len(items) != 1:
        return data
    item = items[0]
    if (
        not isinstance(item, dict)
        or set(item) != {"type", "text"}
        or item.get("type") != "text"
        or not isinstance(item.get("text"), str)
    ):
        return data
    try:
        if json.loads(item["text"]) != structured:
            return data
    except (TypeError, ValueError):
        return data
    human = structured.get("text")
    if not isinstance(human, str) or not human:
        human = structured.get("summary")
    if not isinstance(human, str) or not human:
        human = "Full findings are available in structuredContent."
    return {**data, "content": [{"type": "text", "text": human}]}


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

    def _assert_write_deadline(self, mode: str, not_after_unix_ms: int | None) -> None:
        """Recheck the single-use write deadline without changing read policy."""
        if mode == "write" and (
            type(not_after_unix_ms) is not int or self._now() >= not_after_unix_ms
        ):
            raise GenericMcpDeniedError("signed_mcp_write_deadline_expired")

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
        if not isinstance(arguments, dict) or not _safe_arguments(arguments, tool_name=name):
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
        self._assert_write_deadline(mode, not_after_unix_ms)
        if mode == "readonly" and name in _LONG_READ_MCP_TOOLS:
            result = await session.call_tool(
                name, arguments=arguments, read_timeout_seconds=_LONG_READ_MCP_TIMEOUT_SECONDS
            )
        else:
            # Normal reads and signed writes retain their existing SDK deadline.
            result = await session.call_tool(name, arguments=arguments)
        self.assert_current(project_id, session_id)
        raw_data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        raw_data = _compact_redundant_json_before_redaction(raw_data)
        data = _redact_private_paths(raw_data, str(self._project.directory), str(Path.home()))
        if not isinstance(data, dict):
            raise GenericMcpDeniedError(_DENIED)
        if (
            len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf8"))
            > _MAX_RESULT_BYTES
        ):
            raise GenericMcpDeniedError("local_mcp_result_too_large")
        return data
