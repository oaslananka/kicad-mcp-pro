"""Device-side receiver for bounded Cloud local-folder browse frames.

The signed Windows Connector answers only four owner-initiated operations:
``list``, ``bind``, ``choose`` and ``path``. Every frame carries opaque
folder tokens, never a browser-supplied path; the device re-derives every
filesystem location from its own root-confined browser state. No design file
content, no arbitrary pathnames and no deletion cross this module.

Any frame that does not validate exactly fails closed and terminates the
signed session; Cloud treats a closed socket as "folder unavailable".
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from kicad_mcp.cloud_local_folder_browser import (
    KICAD_PROJECT_SUFFIX,
    MAX_CHILDREN,
    MAX_NAME,
    LocalFolderBrowser,
)
from kicad_mcp.cloud_outbound_handshake import CloudHandshakeDeniedError
from kicad_mcp.cloud_windows_native_picker import choose_project_folder

_DENIED = "handshake denied"
_REQUEST_KIND = "connector.local_browser_request"
_RESULT_KIND = "connector.local_browser_result"
_MAX_REQUEST_BYTES = 1024
# Cloud's connector.local_browser_result schema rejects anything larger.
_MAX_RESULT_BYTES = 8192
_REQUEST_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.ASCII)
_FOLDER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}", re.ASCII)
_PROJECT_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.ASCII
)
_WINDOWS_PROJECT_FILE = re.compile(r"[A-Za-z]:\\.*", re.ASCII)
_OPERATIONS = ("list", "bind", "choose", "path")


def _no_control_characters(value: str) -> bool:
    return all(ord(character) > 0x1F and ord(character) != 0x7F for character in value)


class LocalFolderBrowseService(Protocol):
    """The validated device-side browser port, keyed by opaque tokens only."""

    def list(self, folder_id: str) -> dict[str, object]: ...

    def bind(self, folder_id: str, project_id: str) -> bool: ...

    def choose(self) -> dict[str, object]: ...

    def project_path(self, project_id: str) -> str | None: ...


def _required_folder_frame_fields(operation: str, message: dict[str, object]) -> set[str]:
    """Require opaque local tokens only for operations that actually use them."""
    expected = {"kind", "version", "requestId", "operation"}
    if operation in ("list", "bind"):
        expected.add("folderId")
        folder_id = message.get("folderId")
        if not isinstance(folder_id, str) or _FOLDER_ID.fullmatch(folder_id) is None:
            raise CloudHandshakeDeniedError(_DENIED)
    if operation in ("bind", "path"):
        expected.add("projectId")
        project_id = message.get("projectId")
        if not isinstance(project_id, str) or _PROJECT_ID.fullmatch(project_id) is None:
            raise CloudHandshakeDeniedError(_DENIED)
    return expected


def _decode_request(raw: object) -> dict[str, object]:
    """Strict bounded frame decode; any deviation denies the whole session."""
    if not isinstance(raw, str) or not 1 <= len(raw.encode("utf-8")) <= _MAX_REQUEST_BYTES:
        raise CloudHandshakeDeniedError(_DENIED)
    try:
        message = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise CloudHandshakeDeniedError(_DENIED) from exc
    if not isinstance(message, dict) or message.get("kind") != _REQUEST_KIND:
        raise CloudHandshakeDeniedError(_DENIED)
    if type(message.get("version")) is not int or message["version"] != 1:
        raise CloudHandshakeDeniedError(_DENIED)
    operation = message.get("operation")
    if operation not in _OPERATIONS:
        raise CloudHandshakeDeniedError(_DENIED)
    request_id = message.get("requestId")
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise CloudHandshakeDeniedError(_DENIED)
    if set(message) != _required_folder_frame_fields(operation, message):
        raise CloudHandshakeDeniedError(_DENIED)
    return message


def _bounded_text(value: object, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limit
        or not _no_control_characters(value)
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    return value


def _validated_list(listing: object, request_id: str, folder_id: str) -> dict[str, object]:
    """Re-validate locally produced state before it may leave the device."""
    if not isinstance(listing, dict):
        raise CloudHandshakeDeniedError(_DENIED)
    if set(listing) != {"folderId", "name", "parentId", "project", "more", "folders"}:
        raise CloudHandshakeDeniedError(_DENIED)
    if (
        _bounded_text(listing["folderId"], 64) != folder_id
        or not isinstance(listing["project"], bool)
        or not isinstance(listing["more"], bool)
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    name = _bounded_text(listing["name"], MAX_NAME)
    parent_id = listing["parentId"]
    if parent_id is not None:
        _bounded_text(parent_id, 64)
    raw_folders = listing["folders"]
    if not isinstance(raw_folders, list) or len(raw_folders) > MAX_CHILDREN:
        raise CloudHandshakeDeniedError(_DENIED)
    folders: list[dict[str, object]] = []
    for item in raw_folders:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "name", "project"}
            or type(item["project"]) is not bool
        ):
            raise CloudHandshakeDeniedError(_DENIED)
        folders.append(
            {
                "id": _bounded_text(item["id"], 64),
                "name": _bounded_text(item["name"], MAX_NAME),
                "project": item["project"],
            }
        )
    return {
        "kind": _RESULT_KIND,
        "version": 1,
        "requestId": request_id,
        "operation": "list",
        "folderId": folder_id,
        "name": name,
        "parentId": parent_id,
        "project": listing["project"],
        "more": listing["more"],
        "folders": folders,
    }


def _validated_choose(selection: object, request_id: str) -> dict[str, object]:
    if not isinstance(selection, dict) or set(selection) not in (
        {"status"},
        {"status", "folderId", "name", "projects"},
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    status = selection["status"]
    if status not in ("selected", "cancelled", "invalid"):
        raise CloudHandshakeDeniedError(_DENIED)
    answer: dict[str, object] = {
        "kind": _RESULT_KIND,
        "version": 1,
        "requestId": request_id,
        "operation": "choose",
        "status": status,
    }
    if status != "selected":
        return answer
    projects_raw = selection["projects"]
    if (
        not isinstance(selection["folderId"], str)
        or not isinstance(projects_raw, list)
        or not 1 <= len(projects_raw) <= 25
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    projects = []
    for item in projects_raw:
        if not isinstance(item, dict) or set(item) != {"id", "name"}:
            raise CloudHandshakeDeniedError(_DENIED)
        projects.append(
            {
                "id": _bounded_text(item["id"], 64),
                "name": _bounded_text(item["name"], MAX_NAME),
            }
        )
    answer["folderId"] = _bounded_text(selection["folderId"], 64)
    answer["name"] = _bounded_text(selection["name"], MAX_NAME)
    answer["projects"] = projects
    return answer


def _validated_path(path: object, request_id: str) -> dict[str, object]:
    answer: dict[str, object] = {
        "kind": _RESULT_KIND,
        "version": 1,
        "requestId": request_id,
        "operation": "path",
    }
    if path is None:
        answer["path"] = None
        return answer
    if not isinstance(path, str) or len(path) > 2048:
        raise CloudHandshakeDeniedError(_DENIED)
    lowered = path.lower()
    if (
        not lowered.endswith(KICAD_PROJECT_SUFFIX)
        or _WINDOWS_PROJECT_FILE.fullmatch(path) is None
        or not _no_control_characters(path)
    ):
        raise CloudHandshakeDeniedError(_DENIED)
    answer["path"] = path
    return answer


def handle_folder_frame(service: LocalFolderBrowseService, raw: object) -> dict[str, object]:
    """Execute exactly one validated owner folder operation; never invent state.

    Expected local browser failures (expired tokens, vanished folders) fail
    closed exactly like hostile input: the signed session ends and Cloud
    reports the folder as unavailable instead of guessing.
    """
    request = _decode_request(raw)
    request_id = cast(str, request["requestId"])
    operation = cast(str, request["operation"])
    try:
        if operation == "list":
            folder_id = cast(str, request["folderId"])
            return _validated_list(service.list(folder_id), request_id, folder_id)
        if operation == "bind":
            return {
                "kind": _RESULT_KIND,
                "version": 1,
                "requestId": request_id,
                "operation": "bind",
                "ok": service.bind(cast(str, request["folderId"]), cast(str, request["projectId"])),
            }
        if operation == "choose":
            return _validated_choose(service.choose(), request_id)
        return _validated_path(service.project_path(cast(str, request["projectId"])), request_id)
    except CloudHandshakeDeniedError:
        raise
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise CloudHandshakeDeniedError(_DENIED) from exc


class BrowserFolderService:
    """Adapter from the root-confined LocalFolderBrowser to the frame port.

    ``authorization`` is re-checked before every operation so a locally
    revoked Connector cannot keep serving an already signed session.
    """

    def __init__(
        self,
        browser: LocalFolderBrowser,
        *,
        native_picker: Callable[[], Path | None] = choose_project_folder,
        authorization: Callable[[], bool] | None = None,
    ) -> None:
        self._browser = browser
        self._native_picker = native_picker
        self._authorization = authorization

    def _authorized(self) -> None:
        if self._authorization is not None and self._authorization() is not True:
            raise CloudHandshakeDeniedError(_DENIED)

    def list(self, folder_id: str) -> dict[str, object]:
        self._authorized()
        return cast(dict[str, object], self._browser.list_folder(folder_id))

    def bind(self, folder_id: str, project_id: str) -> bool:
        self._authorized()
        return bool(self._browser.bind(folder_id, project_id))

    def choose(self) -> dict[str, object]:
        self._authorized()
        return self._browser.choose_native(self._native_picker)

    def project_path(self, project_id: str) -> str | None:
        self._authorized()
        try:
            UUID(project_id)
        except (ValueError, AttributeError) as exc:
            raise CloudHandshakeDeniedError(_DENIED) from exc
        return self._browser.get_project_path(project_id)


def default_bindings_file() -> Path:
    """Fixed per-user application-owned mapping file; never caller supplied."""
    return Path.home() / ".kicad-mcp-cloud" / "connector" / "folder-bindings.json"


def device_folder_service(
    selected_directory: Path,
    *,
    bindings_file: Path | None = None,
    native_picker: Callable[[], Path | None] = choose_project_folder,
    authorization: Callable[[], bool] | None = None,
) -> LocalFolderBrowseService:
    """Root-confined browser rooted at the owner-selected project's parent.

    Browsing stays inside the existing KiCad projects area; the native picker
    is a separate owner-driven dialog and remains bounded by the same
    1-25 project files rule. No absolute path ever leaves the device except
    the per-project mapping check answer.
    """
    if not isinstance(selected_directory, Path) or not selected_directory.is_absolute():
        raise CloudHandshakeDeniedError(_DENIED)
    parent = selected_directory.parent
    root = parent if parent != selected_directory else selected_directory
    return BrowserFolderService(
        LocalFolderBrowser(
            [root], bindings_file if bindings_file is not None else default_bindings_file()
        ),
        native_picker=native_picker,
        authorization=authorization,
    )
