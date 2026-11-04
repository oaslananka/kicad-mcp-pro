"""Strict offline-only validation of a future single KiCad write command.

No transport, signer, permission, replay protection or KiCad execution lives
here. A parse result is NOT authorization to mutate. A reviewed outbound
Connector must independently authenticate a signed one-time command, query
current owner/client/project grant, check expected board bytes, and execute
an atomic local KiCad transaction. Existing read-only transport cannot call
this module to perform writes.
"""

from __future__ import annotations

import json
import math
import re
from typing import cast

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

MAX_WRITE_FRAME_BYTES = 1024
MAX_WRITE_DEADLINE_MS = 10_000
_DENIED = "request denied"
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.ASCII,
)
_REFERENCE = re.compile(r"[A-Z]{1,3}[1-9][0-9]{0,5}", re.ASCII)
_SHA256 = re.compile(r"[a-f0-9]{64}", re.ASCII)
_FRAME_FIELDS = frozenset(
    {
        "kind",
        "version",
        "requestId",
        "deviceId",
        "projectId",
        "sessionId",
        "deadlineUnixMs",
        "command",
    }
)
_COMMAND_FIELDS = frozenset(
    {
        "operation",
        "reference",
        "xMm",
        "yMm",
        "rotationDeg",
        "expectedBoardSha256",
    }
)


class LocalWriteDeniedError(ValueError):
    """Generic failure without attacker-controlled content or local paths."""


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) != len({key for key, _ in pairs}):
        raise LocalWriteDeniedError(_DENIED)
    return dict(pairs)


def _reject_nonstandard(_: str) -> None:
    raise LocalWriteDeniedError(_DENIED)


def _coordinate(value: object, *, maximum: float) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return -maximum <= value <= maximum and math.isfinite(value)


def parse_local_write_contract(
    frame: object,
    *,
    verified: VerifiedLocalBinding,
    operator_project: OperatorProject,
    now_unix_ms: int,
) -> dict[str, object]:
    """Check only shape and local binding, never invoke a KiCad operation."""
    if not isinstance(frame, bytes) or not 1 <= len(frame) <= MAX_WRITE_FRAME_BYTES:
        raise LocalWriteDeniedError(_DENIED)
    if type(now_unix_ms) is not int or now_unix_ms <= 0:
        raise LocalWriteDeniedError(_DENIED)
    try:
        parsed: object = json.loads(
            frame.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_nonstandard,
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    if not isinstance(parsed, dict) or parsed.keys() != _FRAME_FIELDS:
        raise LocalWriteDeniedError(_DENIED)
    body = cast(dict[str, object], parsed)
    untrusted_command = body["command"]
    if not isinstance(untrusted_command, dict) or untrusted_command.keys() != _COMMAND_FIELDS:
        raise LocalWriteDeniedError(_DENIED)
    command = cast(dict[str, object], untrusted_command)
    deadline = body["deadlineUnixMs"]
    if (
        body["kind"] != "connector.write_request"
        or type(body["version"]) is not int
        or body["version"] != 1
        or not isinstance(body["requestId"], str)
        or _UUID.fullmatch(body["requestId"]) is None
        or not all(
            isinstance(item, str) and _UUID.fullmatch(item)
            for item in (
                body["deviceId"],
                body["projectId"],
                body["sessionId"],
                verified.device_id,
                verified.project_id,
                verified.session_id,
                operator_project.device_id,
                operator_project.project_id,
            )
        )
        or body["deviceId"] != verified.device_id
        or body["projectId"] != verified.project_id
        or body["sessionId"] != verified.session_id
        or body["deviceId"] != operator_project.device_id
        or body["projectId"] != operator_project.project_id
        or type(verified.session_expires_unix_ms) is not int
        or not now_unix_ms < verified.session_expires_unix_ms
        or type(deadline) is not int
        or not now_unix_ms
        < deadline
        <= min(
            now_unix_ms + MAX_WRITE_DEADLINE_MS,
            verified.session_expires_unix_ms,
        )
        or command["operation"] != "pcb_move_footprint"
        or command["operation"] not in verified.operations
        or not isinstance(command["reference"], str)
        or _REFERENCE.fullmatch(command["reference"]) is None
        or not _coordinate(command["xMm"], maximum=1000)
        or not _coordinate(command["yMm"], maximum=1000)
        or not (command["rotationDeg"] is None or _coordinate(command["rotationDeg"], maximum=360))
        or not isinstance(command["expectedBoardSha256"], str)
        or _SHA256.fullmatch(command["expectedBoardSha256"]) is None
    ):
        raise LocalWriteDeniedError(_DENIED)
    return body
