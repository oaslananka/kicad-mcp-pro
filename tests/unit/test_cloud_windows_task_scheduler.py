"""Windows Task Scheduler owner-only contract tests (NO real task writes)."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from defusedxml import ElementTree as SafeET

from kicad_mcp import cloud_windows_task_scheduler as scheduler
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError

SID = "S-1-5-21-100-200-300-1001"


def _fixture_task() -> tuple[str, str]:
    executable = r"C:\Users\Tester\.venv\Scripts\python.exe"
    return scheduler._task_xml(SID, executable), executable


def test_local_task_xml_is_least_privilege_owner_logon_only() -> None:
    xml, executable = _fixture_task()
    scheduler._require_owned_task(xml, SID, executable)
    assert "InteractiveToken" in xml
    assert "LeastPrivilege" in xml
    assert "IgnoreNew" in xml
    assert scheduler._TASK_ARGS in xml
    assert "SYSTEM" not in xml
    assert "/f" not in xml
    assert scheduler._task_name(SID).startswith("KiCadMCPPro-Cloud-Connector-")


@pytest.mark.parametrize(
    "change",
    [
        ("Owner", "Other"),
        ("InteractiveToken", "Password"),
        ("LeastPrivilege", "HighestAvailable"),
        ("kicad_mcp.cloud_windows_connector", "attacker_module"),
        (SID, "S-1-5-21-100-200-300-1002"),
    ],
)
def test_task_ownership_fails_on_mutated_principal_or_execution(
    change: tuple[str, str],
) -> None:
    xml, executable = _fixture_task()
    mutated = xml.replace(change[0], change[1])
    with pytest.raises(LocalApprovalDeniedError):
        scheduler._require_owned_task(mutated, SID, executable)


def test_task_ownership_denies_extra_action_and_trigger() -> None:
    xml, exe = _fixture_task()
    ns = f"{{{scheduler._TASK_NS}}}"
    for parent_name, extra_name in (("Actions", "ComHandler"), ("Triggers", "BootTrigger")):
        root = SafeET.fromstring(xml)
        parent = root.find(f"{ns}{parent_name}")
        assert parent is not None
        ET.SubElement(parent, ns + extra_name)
        with pytest.raises(LocalApprovalDeniedError):
            scheduler._require_owned_task(ET.tostring(root, encoding="unicode"), SID, exe)


def test_task_ownership_denies_xml_dtd_and_oversize() -> None:
    _xml, exe = _fixture_task()
    with pytest.raises(LocalApprovalDeniedError):
        scheduler._require_owned_task(
            '<!DOCTYPE root [<!ENTITY xx "attacker">]><root>&xx;</root>', SID, exe
        )
    with pytest.raises(LocalApprovalDeniedError):
        scheduler._require_owned_task("a" * 32769, SID, exe)


def test_ensure_owner_task_never_overwrites_existing_and_verifies_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml, exe = _fixture_task()
    seen: list[tuple[str, ...]] = []
    queried = 0

    def query(sid: str) -> str | None:
        nonlocal queried
        assert sid == SID
        queried += 1
        return None if queried == 1 else xml

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        assert args[0] == "/create" and "/f" not in args
        file = Path(args[-1])
        assert file.is_file()
        assert file.read_text(encoding="utf-16") == xml
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(scheduler, "_current_sid", lambda: SID)
    monkeypatch.setattr(scheduler, "_command_executable", lambda: exe)
    monkeypatch.setattr(scheduler, "_query", query)
    monkeypatch.setattr(scheduler, "_run_schtasks", run)
    assert scheduler.ensure_owner_task() is True
    assert len(seen) == 1


def test_ensure_owner_task_refuses_foreign_task_without_overwriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml, exe = _fixture_task()
    monkeypatch.setattr(scheduler, "_current_sid", lambda: SID)
    monkeypatch.setattr(scheduler, "_command_executable", lambda: exe)
    monkeypatch.setattr(
        scheduler, "_query", lambda _sid: xml.replace("LeastPrivilege", "HighestAvailable")
    )
    monkeypatch.setattr(
        scheduler,
        "_run_schtasks",
        lambda *_a: pytest.fail("must never overwrite another scheduled task"),
    )
    with pytest.raises(LocalApprovalDeniedError):
        scheduler.ensure_owner_task()


def test_start_and_stop_recheck_principal_and_never_touch_other_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml, exe = _fixture_task()
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(scheduler, "_current_sid", lambda: SID)
    monkeypatch.setattr(scheduler, "_command_executable", lambda: exe)
    monkeypatch.setattr(scheduler, "_query", lambda _sid: xml)

    def call(*args: str) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(scheduler, "_run_schtasks", call)
    scheduler.start_owner_task()
    assert scheduler.stop_and_remove_owner_task() is True
    assert [call[0] for call in seen] == ["/run", "/end", "/delete"]
    assert all("/tn" in call and scheduler._task_name(SID) in call for call in seen)

    seen.clear()
    monkeypatch.setattr(scheduler, "_query", lambda _sid: xml.replace(exe, "C:\\wrong.exe"))
    with pytest.raises(LocalApprovalDeniedError):
        scheduler.stop_and_remove_owner_task()
    assert not seen


def test_scheduled_task_does_not_imply_connected_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml, exe = _fixture_task()
    monkeypatch.setattr(scheduler, "local_state", lambda: "Configured (not connected)")
    monkeypatch.setattr(scheduler, "_current_sid", lambda: SID)
    monkeypatch.setattr(scheduler, "_command_executable", lambda: exe)
    monkeypatch.setattr(scheduler, "_query", lambda _sid: xml)
    assert scheduler.scheduler_state() == "Scheduled (connection unverified)"
    monkeypatch.setattr(scheduler, "_query", lambda _sid: None)
    assert scheduler.scheduler_state() == "Configured (task unverified)"


def test_scheduler_enable_rolls_back_local_marker_after_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(scheduler, "activate", lambda *_a, **_k: called.append("activate"))
    monkeypatch.setattr(scheduler, "ensure_owner_task", lambda: called.append("install") or True)
    monkeypatch.setattr(
        scheduler,
        "start_owner_task",
        lambda: (_ for _ in ()).throw(LocalApprovalDeniedError("start denied")),
    )
    monkeypatch.setattr(scheduler, "deactivate", lambda: called.append("revoke") or True)
    monkeypatch.setattr(
        scheduler, "stop_and_remove_owner_task", lambda: called.append("stop") or False
    )
    with pytest.raises(LocalApprovalDeniedError):
        scheduler.enable_windows_connector(None, owner_confirm=lambda _: True)  # type: ignore[arg-type]
    assert called == ["activate", "install", "revoke", "stop"]


def test_system_tool_is_os_pinned_readonly() -> None:
    import os

    if os.name != "nt":
        pytest.skip("Native Windows only")
    for name in ("schtasks.exe", "whoami.exe"):
        result = scheduler._system_tool(name)
        assert Path(result).is_file()
        assert result.lower().endswith("system32\\" + name)
    with pytest.raises(LocalApprovalDeniedError):
        scheduler._system_tool("malicious.exe")


def test_task_query_distinguishes_verified_missing_from_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, ...]] = []

    def response(code: int, output: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["schtasks"], code, output, "opaque")

    def simulate(*args: str) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        return result

    monkeypatch.setattr(scheduler, "_run_schtasks", simulate)
    result = response(0x80070002)
    assert scheduler._query(SID) is None
    assert seen == [("/query", "/tn", scheduler._task_name(SID), "/xml", "/hresult")]
    result = response(5)
    with pytest.raises(LocalApprovalDeniedError):
        scheduler._query(SID)
    result = response(0, "")
    with pytest.raises(LocalApprovalDeniedError):
        scheduler._query(SID)
    xml, _exe = _fixture_task()
    result = response(0, xml)
    assert scheduler._query(SID) == xml


def test_disable_idempotent_only_after_verified_task_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "_current_sid", lambda: SID)
    monkeypatch.setattr(scheduler, "_query", lambda _sid: None)
    monkeypatch.setattr(
        scheduler, "_run_schtasks", lambda *_a: pytest.fail("no task can be touched")
    )
    assert scheduler.stop_and_remove_owner_task() is True

    def denied(_sid: str) -> str | None:
        raise LocalApprovalDeniedError("denied")

    monkeypatch.setattr(scheduler, "_query", denied)
    with pytest.raises(LocalApprovalDeniedError):
        scheduler.stop_and_remove_owner_task()
