"""Offline-only, fail-closed local policy for a future KiCad Cloud connector.

This module has NO transport, credentials, WebSocket listener, project discovery,
native command execution, or MCP tool registration. In particular, callers
must not interpret an accepted envelope as authenticating its sender: only a
separately reviewed local transport may supply VerifiedLocalBinding.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_FRAME_BYTES = 1024
MAX_DEADLINE_MS = 30_000
MAX_SESSION_REMAINING_MS = 300_000
MAX_DIRECTORY_ENTRIES = 128
_READ_DENIED = "request denied"

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.ASCII,
)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", re.ASCII)
_FIELDS = frozenset(
    {"kind", "version", "requestId", "deviceId", "projectId", "operation", "deadlineUnixMs"}
)
# Normal presence-only entrypoints reject all native operations. A separately
# gated owner-foreground DRC preview can explicitly opt in during validation.
_SUPPORTED = frozenset({"project_summary"})


class LocalReadDeniedError(ValueError):
    """A generic, intentionally uninformative rejection."""


@dataclass(frozen=True)
class VerifiedLocalBinding:
    """Created ONLY after separate, reviewed transport/device authentication."""

    device_id: str
    project_id: str
    operations: frozenset[str]
    session_id: str
    session_expires_unix_ms: int


@dataclass(frozen=True)
class OperatorProject:
    """Explicitly owner-approved, out-of-band local path; never from Cloud JSON."""

    device_id: str
    project_id: str
    directory: Path
    filename_stem: str


def _uuid(value: object) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _pairs_unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({name for name, _ in pairs}) != len(pairs):
        raise LocalReadDeniedError(_READ_DENIED)
    return dict(pairs)


def _reject_constant(_: str) -> None:
    raise LocalReadDeniedError(_READ_DENIED)


def _validate_frame(
    frame: bytes,
    boundary: VerifiedLocalBinding,
    policy: OperatorProject,
    now_ms: int,
    *,
    allow_native_drc: bool = False,
) -> dict[str, object]:
    if not isinstance(frame, bytes) or not (1 <= len(frame) <= MAX_FRAME_BYTES):
        raise LocalReadDeniedError(_READ_DENIED)
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms <= 0:
        raise LocalReadDeniedError(_READ_DENIED)
    if not all(
        _uuid(n)
        for n in (boundary.device_id, boundary.project_id, policy.device_id, policy.project_id)
    ):
        raise LocalReadDeniedError(_READ_DENIED)
    try:
        body = json.loads(
            frame.decode("utf-8"), object_pairs_hook=_pairs_unique, parse_constant=_reject_constant
        )
    except (ValueError, TypeError) as exc:
        raise LocalReadDeniedError(_READ_DENIED) from exc
    if not isinstance(body, dict) or set(body) != _FIELDS:
        raise LocalReadDeniedError(_READ_DENIED)
    deadline = body.get("deadlineUnixMs")
    operation = body.get("operation")
    if (
        body.get("kind") != "connector.read_request"
        or type(body.get("version")) is not int
        or body["version"] != 1
        or not _uuid(body.get("requestId"))
        or body.get("deviceId") != boundary.device_id
        or body.get("projectId") != boundary.project_id
        or boundary.device_id != policy.device_id
        or boundary.project_id != policy.project_id
        or not _uuid(boundary.session_id)
        or type(boundary.session_expires_unix_ms) is not int
        or not (now_ms < boundary.session_expires_unix_ms <= now_ms + MAX_SESSION_REMAINING_MS)
        or not isinstance(operation, str)
        or (operation not in _SUPPORTED and not (allow_native_drc and operation == "run_drc"))
        or operation not in boundary.operations
        or type(deadline) is not int
        or not (
            now_ms < deadline <= min(now_ms + MAX_DEADLINE_MS, boundary.session_expires_unix_ms)
        )
    ):
        raise LocalReadDeniedError(_READ_DENIED)
    return body


def _open_operator_directory(folder: Path) -> int:
    """Open each directory hop without following symlinks (no TOCTOU walk)."""
    # Windows has no equivalent stdlib openat/O_NOFOLLOW directory walk.
    # Do not silently downgrade to a symlink-following path check.
    dir_flag = getattr(os, "O_DIRECTORY", None)
    nofollow_flag = getattr(os, "O_NOFOLLOW", None)
    if os.name != "posix" or type(dir_flag) is not int or type(nofollow_flag) is not int:
        raise LocalReadDeniedError(_READ_DENIED)
    # This is an owner-selected absolute directory, never a path supplied by
    # the Cloud request. Refuse lexical upward navigation before the openat
    # walk, even though O_NOFOLLOW already rejects symlink substitution.
    if not isinstance(folder, Path) or not folder.is_absolute():
        raise LocalReadDeniedError(_READ_DENIED)
    components = folder.parts[1:]
    if (
        not components
        or len(components) > 128
        or any(
            component in {"", ".", ".."} or "\x00" in component or len(os.fsencode(component)) > 255
            for component in components
        )
    ):
        raise LocalReadDeniedError(_READ_DENIED)
    flags = os.O_RDONLY | dir_flag | nofollow_flag
    descriptor = os.open("/", flags)
    try:
        for component in components:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_presence_only(policy: OperatorProject) -> dict[str, bool]:
    """Inspect only three fixed direct children using a no-follow directory FD."""
    path = policy.directory
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or not isinstance(policy.filename_stem, str)
        or not _NAME.fullmatch(policy.filename_stem)
        or policy.filename_stem in {".", ".."}
    ):
        raise LocalReadDeniedError(_READ_DENIED)
    descriptor: int | None = None
    try:
        descriptor = _open_operator_directory(path)
        members: set[str] = set()
        # os.listdir() eagerly materializes the entire directory before
        # our entry cap can run. Stop scandir at the 129th entry instead.
        with os.scandir(descriptor) as entries:
            for index, member in enumerate(entries):
                if index >= MAX_DIRECTORY_ENTRIES:
                    raise LocalReadDeniedError(_READ_DENIED)
                members.add(member.name)
        result: dict[str, bool] = {}
        for label, suffix in (
            ("projectPresent", ".kicad_pro"),
            ("boardPresent", ".kicad_pcb"),
            ("schematicPresent", ".kicad_sch"),
        ):
            name = policy.filename_stem + suffix
            if name not in members:
                result[label] = False
                continue
            entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            # A hard link can alias an unrelated regular file into the
            # approved folder without traversing a symlink. Presence for
            # multiply-linked inodes must not count as this project's file.
            if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
                raise LocalReadDeniedError(_READ_DENIED)
            result[label] = True
        return result
    except (OSError, ValueError) as exc:
        raise LocalReadDeniedError(_READ_DENIED) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def inspect_readonly(
    frame: bytes,
    *,
    verified: VerifiedLocalBinding,
    operator_project: OperatorProject,
    now_unix_ms: int,
) -> dict[str, object]:
    """Validate a Cloud v1 envelope against local approvals; return no paths/data.

    A future transport can use this only AFTER independent authenticated binding
    and grant checks. No caller currently wires it into a server or device.
    """
    request = _validate_frame(frame, verified, operator_project, now_unix_ms)
    status = _read_presence_only(operator_project)
    return {
        "kind": "connector.local_read_preview",
        "version": 1,
        "requestId": request["requestId"],
        "projectId": operator_project.project_id,
        "operation": "project_summary",
        "files": status,
    }
