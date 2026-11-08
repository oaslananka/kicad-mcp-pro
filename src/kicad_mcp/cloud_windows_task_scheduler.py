"""Current-user Windows Connector lifecycle via the existing Task Scheduler.

No task is registered from import, MCP stdio start, or Cloud setup. Only an
explicit owner-initiated enable call may install/launch the single namespaced,
least-privilege, interactive-user, on-logon task. Never overwrite or delete
unknown tasks. A task alone is not proof of a Cloud grant or connected socket.
"""

from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_connector import (
    activate,
    deactivate,
    local_state,
)
from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject

_DENIED = "Windows Connector scheduled task could not be verified."
_SID = re.compile(r"S-1-5-(?:\d+-){1,15}\d+\Z", re.ASCII)
_TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_TASK_ARGS = "-m kicad_mcp.cloud_windows_connector run"
_EXEC_TIMEOUT = 15


def _system_tool(name: str) -> str:
    """Pin Windows' own system utilities; never resolve them from PATH."""
    if os.name != "nt" or name not in {"schtasks.exe", "whoami.exe"}:
        raise LocalApprovalDeniedError(_DENIED)
    # Derive the genuine Windows system directory from kernel32, never
    # from a mutable environment variable or executable PATH entry.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetSystemDirectoryW.restype = ctypes.c_uint
    buf = ctypes.create_unicode_buffer(32768)
    used = kernel.GetSystemDirectoryW(buf, len(buf))
    if not 1 <= used < len(buf):
        raise LocalApprovalDeniedError(_DENIED)
    result = Path(buf.value) / name
    if not result.is_file():
        raise LocalApprovalDeniedError(_DENIED)
    return str(result)


def _current_sid() -> str:
    result = subprocess.run(
        [_system_tool("whoami.exe"), "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=_EXEC_TIMEOUT,
        check=False,
    )
    if result.returncode:
        raise LocalApprovalDeniedError(_DENIED)
    rows = list(csv.reader(io.StringIO(result.stdout)))
    if len(rows) != 1 or len(rows[0]) != 2:
        raise LocalApprovalDeniedError(_DENIED)
    sid = rows[0][1].strip()
    if _SID.fullmatch(sid) is None:
        raise LocalApprovalDeniedError(_DENIED)
    return sid


def _same_logon_user(user: str | None, sid: str) -> bool:
    """Recognize a Task Scheduler-normalized current-user name, not a new owner.

    Windows may serialize an originally SID-scoped LogonTrigger.UserId as the
    account's short display name after registering the task. The principal
    must still have exactly the current SID and InteractiveToken.
    """
    if user == sid:
        return True
    if not user:
        return False
    result = subprocess.run(
        [_system_tool("whoami.exe")],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=_EXEC_TIMEOUT,
        check=False,
    )
    if result.returncode:
        return False
    current = result.stdout.strip()
    if not current or chr(92) not in current:
        return False
    short = current.rsplit(chr(92), 1)[-1]
    return user.casefold() in {current.casefold(), short.casefold()}


def _task_name(sid: str) -> str:
    if not isinstance(sid, str) or _SID.fullmatch(sid) is None:
        raise LocalApprovalDeniedError(_DENIED)
    return "KiCadMCPPro-Cloud-Connector-" + hashlib.sha256(sid.encode("ascii")).hexdigest()[:16]


def _command_executable() -> str:
    executable = Path(sys.executable)
    if (
        os.name != "nt"
        or not executable.is_absolute()
        or not executable.is_file()
        or executable.suffix.lower() != ".exe"
        or str(executable).startswith(("\\\\", "//"))
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return str(executable)


def _task_xml(sid: str, executable: str) -> str:
    if _SID.fullmatch(sid) is None or not Path(executable).is_absolute():
        raise LocalApprovalDeniedError(_DENIED)
    root = ET.Element("Task", {"version": "1.3", "xmlns": _TASK_NS})
    info = ET.SubElement(root, "RegistrationInfo")
    ET.SubElement(info, "Description").text = "KiCad MCP Pro owner-managed, read-only Connector"
    triggers = ET.SubElement(root, "Triggers")
    logon = ET.SubElement(triggers, "LogonTrigger")
    ET.SubElement(logon, "Enabled").text = "true"
    ET.SubElement(logon, "UserId").text = sid
    principals = ET.SubElement(root, "Principals")
    principal = ET.SubElement(principals, "Principal", {"id": "Owner"})
    ET.SubElement(principal, "UserId").text = sid
    ET.SubElement(principal, "LogonType").text = "InteractiveToken"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    settings = ET.SubElement(root, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("AllowHardTerminate", "true"),
        ("StartWhenAvailable", "true"),
        ("RunOnlyIfNetworkAvailable", "true"),
        ("Enabled", "true"),
        ("Hidden", "false"),
        ("AllowStartOnDemand", "true"),
        ("ExecutionTimeLimit", "PT0S"),
    ):
        ET.SubElement(settings, name).text = value
    actions = ET.SubElement(root, "Actions", {"Context": "Owner"})
    action = ET.SubElement(actions, "Exec")
    ET.SubElement(action, "Command").text = executable
    ET.SubElement(action, "Arguments").text = _TASK_ARGS
    return '<?xml version="1.0" encoding="utf-16"?>\n' + ET.tostring(root, encoding="unicode")


def _run_schtasks(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_system_tool("schtasks.exe"), *args],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=_EXEC_TIMEOUT,
        check=False,
    )


_TASK_NOT_FOUND_HRESULT = 0x80070002


def _query(sid: str) -> str | None:
    """Distinguish missing task from denied/broken Task Scheduler queries.

    Verified on Windows with schtasks /query /xml /hresult. Treat any other
    failure as unknown, never silently create/overwrite or claim task stopped.
    """
    result = _run_schtasks("/query", "/tn", _task_name(sid), "/xml", "/hresult")
    code = result.returncode & 0xFFFFFFFF
    if code == _TASK_NOT_FOUND_HRESULT:
        return None
    if code != 0 or not result.stdout.strip():
        raise LocalApprovalDeniedError(_DENIED)
    return result.stdout


def _require_owned_task(xml: str, sid: str, executable: str) -> None:
    """Accept only a task with exactly our user, trigger and single executable."""
    try:
        if not 1 <= len(xml) <= 32768:
            raise LocalApprovalDeniedError(_DENIED)
        root = SafeET.fromstring(xml, forbid_dtd=True)
        ns = {"t": _TASK_NS}
        if root.tag != f"{{{_TASK_NS}}}Task":
            raise LocalApprovalDeniedError(_DENIED)
        principal = root.findall("t:Principals/t:Principal", ns)
        trigger = root.findall("t:Triggers/*", ns)
        actions = root.findall("t:Actions/*", ns)
        actions_root = root.find("t:Actions", ns)
        if (
            len(principal) != 1
            or len(trigger) != 1
            or len(actions) != 1
            or principal[0].attrib.get("id") != "Owner"
            or actions_root is None
            or actions_root.attrib.get("Context") != "Owner"
            or trigger[0].tag != f"{{{_TASK_NS}}}LogonTrigger"
            or actions[0].tag != f"{{{_TASK_NS}}}Exec"
        ):
            raise LocalApprovalDeniedError(_DENIED)

        def get(item: ET.Element, node: str) -> str | None:
            return item.findtext(node, namespaces=ns)

        command = get(actions[0], "t:Command")
        if (
            get(principal[0], "t:UserId") != sid
            or get(principal[0], "t:LogonType") != "InteractiveToken"
            # Windows omits default LeastPrivilege/Enabled on export.
            or get(principal[0], "t:RunLevel") not in (None, "LeastPrivilege")
            or not _same_logon_user(get(trigger[0], "t:UserId"), sid)
            or get(trigger[0], "t:Enabled") not in (None, "true")
            or root.findtext("t:Settings/t:Enabled", namespaces=ns) == "false"
            or get(actions[0], "t:Arguments") != _TASK_ARGS
            or not command
            or os.path.normcase(command) != os.path.normcase(executable)
        ):
            raise LocalApprovalDeniedError(_DENIED)
    except (ET.ParseError, ValueError, TypeError, DefusedXmlException) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def ensure_owner_task() -> bool:
    """Install once without /F; existing tasks must match exactly."""
    sid = _current_sid()
    executable = _command_executable()
    previous = _query(sid)
    if previous is not None:
        _require_owned_task(previous, sid, executable)
        return False
    with tempfile.TemporaryDirectory(prefix="kicad-cloud-task-") as folder:
        file = Path(folder) / "task.xml"
        file.write_text(_task_xml(sid, executable), encoding="utf-16")
        result = _run_schtasks("/create", "/tn", _task_name(sid), "/xml", str(file))
    if result.returncode:
        raise LocalApprovalDeniedError(_DENIED)
    verified = _query(sid)
    if verified is None:
        raise LocalApprovalDeniedError(_DENIED)
    _require_owned_task(verified, sid, executable)
    return True


def start_owner_task() -> None:
    sid = _current_sid()
    existing = _query(sid)
    if existing is None:
        raise LocalApprovalDeniedError(_DENIED)
    _require_owned_task(existing, sid, _command_executable())
    if _run_schtasks("/run", "/tn", _task_name(sid)).returncode != 0:
        raise LocalApprovalDeniedError(_DENIED)


def stop_and_remove_owner_task() -> bool:
    """Never stop or delete a task with unexpected command/user/principal."""
    sid = _current_sid()
    existing = _query(sid)
    if existing is None:
        # An exact Windows ERROR_FILE_NOT_FOUND was verified. Repeating
        # disable after a successful uninstall is a harmless no-op.
        return True
    _require_owned_task(existing, sid, _command_executable())
    stopped = _run_schtasks("/end", "/tn", _task_name(sid))
    # Win32 Task Scheduler distinguishes an already-stopped instance from a
    # real failure. Never delete the task after an unknown stop failure: the
    # scheduled process might still be running under the owner's account.
    stop_code = stopped.returncode & 0xFFFFFFFF
    if stop_code not in (0, 0x8004130B):  # SCHED_E_TASK_NOT_RUNNING
        return False
    deleted = _run_schtasks("/delete", "/tn", _task_name(sid), "/f")
    if deleted.returncode != 0:
        return False
    # A successful CLI command is insufficient evidence for task deletion.
    # This distinguishes a safely removed task from an inaccessible one.
    return _query(sid) is None


def enable_windows_connector(
    project: WindowsRegisteredProject,
    *,
    owner_confirm: Callable[[WindowsRegisteredProject], bool],
) -> None:
    """Owner explicitly enables a task; rollback local permission if start fails."""
    activate(project, owner_confirm=owner_confirm)
    newly_created = False
    try:
        newly_created = ensure_owner_task()
        start_owner_task()
    except (OSError, ValueError, subprocess.SubprocessError):
        deactivate()
        if newly_created:
            try:
                stop_and_remove_owner_task()
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        raise


def disable_windows_connector() -> bool:
    """Revoke local reads first; remote Cloud grant must be revoked separately."""
    deactivate()
    return stop_and_remove_owner_task()


def scheduler_state() -> str:
    """Only claims configured; task XML does not prove a connected socket."""
    state = local_state()
    if state != "Configured (not connected)":
        return state
    try:
        sid = _current_sid()
        xml = _query(sid)
        if xml is None:
            return "Configured (task unverified)"
        _require_owned_task(xml, sid, _command_executable())
        return "Scheduled (connection unverified)"
    except (OSError, ValueError, subprocess.SubprocessError):
        return "Unavailable"
