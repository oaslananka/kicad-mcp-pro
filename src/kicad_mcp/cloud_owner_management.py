"""Owner-approved Cloud management client, independent of project file access.

The CLI never receives browser cookies or a device signing key. A one-use
browser approval creates one short-lived management token per Cloud origin.
Tokens remain in the Windows user credential vault or an owner-private
POSIX registry. No redirect follows an Authorization header.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import ssl
import time
import webbrowser
from pathlib import Path
from typing import Any

import urllib3

from kicad_mcp.cloud_local_registry import default_registry_root
from kicad_mcp.cloud_pair import _origin
from kicad_mcp.cloud_pair_keys import (
    LocalApprovalDeniedError,
    _read_private_json,
    _write_private_json,
)

_TOKEN = re.compile(r"kmpc1_[A-Za-z0-9_-]{43}\Z", re.ASCII)
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
_MAX_RESPONSE = 65_536
_PART = "owner_api"


class CloudManagementError(ValueError):
    """User-safe failure; never carries a bearer token or connection string."""


def _verified_origin(origin: str) -> str:
    try:
        return _origin(origin)[2]
    except (ValueError, TypeError) as exc:
        raise CloudManagementError("Use a trusted HTTPS Cloud origin.") from exc


def _record(origin: str) -> str:
    return hashlib.sha256(origin.encode("ascii")).hexdigest()[:32]


def _posix_file(origin: str) -> tuple[Path, str]:
    return default_registry_root(), "owner-api-" + _record(origin) + ".json"


def load_token(origin: str) -> str | None:
    """Read only the current user's previously approved management token."""
    origin = _verified_origin(origin)
    try:
        if os.name == "nt":
            from kicad_mcp.cloud_windows_credentials import read_credential

            raw = read_credential(_record(origin), _PART)
            token = raw.decode("ascii") if raw is not None else None
        else:
            root, filename = _posix_file(origin)
            if not (root / filename).exists():
                return None
            value = _read_private_json(root, filename)
            token = value.get("token")
        if token is None:
            return None
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise CloudManagementError("Stored Cloud access is invalid. Reauthorize this computer.")
        return token
    except (OSError, UnicodeError, LocalApprovalDeniedError) as exc:
        raise CloudManagementError("Private Cloud credential storage is unavailable.") from exc


def save_token(origin: str, token: str) -> None:
    origin = _verified_origin(origin)
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise CloudManagementError("Cloud did not return a valid management credential.")
    try:
        if os.name == "nt":
            from kicad_mcp.cloud_windows_credentials import (
                create_credential,
                delete_credential,
                read_credential,
            )

            record = _record(origin)
            if read_credential(record, _PART) is not None:
                delete_credential(record, _PART)
            create_credential(record, _PART, token.encode("ascii"))
        else:
            root, filename = _posix_file(origin)
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            _write_private_json(root, filename, {"token": token})
    except (OSError, LocalApprovalDeniedError) as exc:
        raise CloudManagementError("Could not save Cloud access in private credentials.") from exc


def forget_token(origin: str) -> None:
    origin = _verified_origin(origin)
    try:
        if os.name == "nt":
            from kicad_mcp.cloud_windows_credentials import delete_credential

            delete_credential(_record(origin), _PART)
        else:
            from kicad_mcp.cloud_pair_keys import _open_owner_private_dir

            root, filename = _posix_file(origin)
            if not root.is_dir():
                return
            fd = _open_owner_private_dir(root / filename)
            try:
                try:
                    os.unlink(filename, dir_fd=fd)
                except FileNotFoundError:
                    pass
            finally:
                os.close(fd)
    except (OSError, LocalApprovalDeniedError) as exc:
        raise CloudManagementError("Could not remove private Cloud credentials.") from exc


class CloudOwnerApi:
    """Bound, no-redirect HTTPS JSON access to one verified Cloud origin."""

    def __init__(self, origin: str) -> None:
        self.origin = _verified_origin(origin)

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        if (
            method not in {"GET", "POST"}
            or not path.startswith("/api/owner/")
            or ("://" in path or "\\" in path or "#" in path)
        ):
            raise CloudManagementError("Unsupported Cloud management request.")
        if token is not None and not _TOKEN.fullmatch(token):
            raise CloudManagementError("Stored Cloud access is invalid.")
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if len(body) > 4096:
                raise CloudManagementError("Cloud management request is too large.")
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        pool = urllib3.PoolManager(
            cert_reqs=ssl.CERT_REQUIRED,
            ssl_context=ssl.create_default_context(),
            timeout=urllib3.Timeout(connect=5, read=9),
            retries=False,
        )
        try:
            response = pool.request(
                method,
                self.origin + path,
                headers=headers,
                body=body,
                redirect=False,
                preload_content=False,
            )
            try:
                if response.status < 200 or response.status >= 300:
                    raise CloudManagementError(
                        "Cloud management request failed (HTTP " + str(response.status) + ")."
                    )
                content = response.read(_MAX_RESPONSE + 1)
                if len(content) > _MAX_RESPONSE:
                    raise CloudManagementError("Cloud management response is too large.")
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise CloudManagementError("Cloud returned an invalid management response.")
                return result
            finally:
                response.release_conn()
        except (urllib3.exceptions.HTTPError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CloudManagementError(
                "Cloud is unavailable. Check the connection and retry."
            ) from exc
        finally:
            pool.clear()

    def authorized(
        self, method: str, path: str, *, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        token = load_token(self.origin)
        if token is None:
            raise CloudManagementError(
                "Cloud management is not connected. Run: kicad-mcp-pro cloud authorize"
            )
        return self.request(method, path, payload=payload, token=token)


def authorize(
    origin: str,
    *,
    no_browser: bool = False,
    label: str | None = None,
    timeout_seconds: int = 600,
) -> None:
    """One human-approved browser journey, then reusable private CLI access."""
    api = CloudOwnerApi(origin)
    current = load_token(api.origin)
    if current:
        try:
            api.request("GET", "/api/owner/v1/devices", token=current)
            print("Cloud management already connected.")
            return
        except CloudManagementError:
            # Do not silently replace credentials on a temporary outage.
            raise CloudManagementError(
                "Existing Cloud access could not be verified. Try again later or log out."
            ) from None
    request_id = secrets.token_urlsafe(32)
    if not _REQUEST_ID.fullmatch(request_id):
        raise CloudManagementError("Could not create a Cloud approval request.")
    hostname = label if label is not None else socket.gethostname()
    safe_label = re.sub(r"[^A-Za-z0-9 ._()-]", "", hostname)[:64].strip() or "My computer"
    started = api.request(
        "POST", "/api/owner/cli/start", payload={"requestId": request_id, "label": safe_label}
    )
    expected_url = api.origin + "/api/owner/cli/approve?request_id=" + request_id
    if started.get("status") != "pending" or started.get("approveUrl") != expected_url:
        raise CloudManagementError("Cloud returned an untrusted approval destination.")
    print("Approve command-line access in your browser: " + expected_url)
    if not no_browser:
        try:
            if not webbrowser.open(expected_url, new=2, autoraise=True):
                print("Open the link above to continue.")
        except (OSError, webbrowser.Error):
            print("Open the link above to continue.")
    deadline = time.monotonic() + min(600, max(1, timeout_seconds))
    while time.monotonic() < deadline:
        state = api.request("POST", "/api/owner/cli/poll", payload={"requestId": request_id})
        status = state.get("status")
        if status == "approved":
            token = state.get("token")
            if not isinstance(token, str) or not _TOKEN.fullmatch(token):
                raise CloudManagementError("Cloud approval lacked a valid token.")
            save_token(api.origin, token)
            print("Cloud management connected. Use cloud devices, clients, access, usage or logs.")
            return
        if status in {"expired", "denied", "claimed"}:
            raise CloudManagementError("Cloud approval was not completed. Start a new login.")
        if status != "pending":
            raise CloudManagementError("Unexpected Cloud approval state.")
        time.sleep(2)
    raise CloudManagementError("Cloud approval timed out. Start a new login.")
