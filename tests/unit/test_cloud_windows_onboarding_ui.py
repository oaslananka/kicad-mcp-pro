"""Isolated native Windows UI enrollment lifecycle; no Cloud/network/credentials."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.services import cloud_windows_onboarding_ui as onboarding
from kicad_mcp.services.cloud_onboarding import SetupStatus

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows UI enrollment only")


@pytest.fixture
def project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    (tmp_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(onboarding, "selected_project", lambda: None)
    return tmp_path


def test_pairing_waits_for_owner_then_registers_without_enabling(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_for_approval = threading.Event()
    approved = threading.Event()
    calls: list[str] = []

    def enroll(*, origin: str, alias: str, owner_approval):
        assert origin == onboarding.DEFAULT_CLOUD_ORIGIN
        assert alias == "My computer"
        owner_approval(origin + "/devices/pairing", "challenge-id", "SAMPLE-CODE")
        ready_for_approval.set()
        assert approved.wait(timeout=5)
        calls.append("enroll")
        return SimpleNamespace(device_id="device-1")

    def register(device, *, alias: str, filename_stem: str):
        assert device.device_id == "device-1"
        assert (alias, filename_stem) == ("board", "board")
        calls.append("register")
        return SimpleNamespace(project_id="project-1")

    def bind(project_record, selected_dir, *, owner_confirm):
        assert selected_dir == project
        assert owner_confirm(selected_dir)
        assert project_record.project_id == "project-1"
        calls.append("bind")

    monkeypatch.setattr(onboarding, "enroll_windows_device", enroll)
    monkeypatch.setattr(onboarding, "register_windows_project", register)
    monkeypatch.setattr(onboarding, "bind_owner_selected_project", bind)
    monkeypatch.setattr(
        onboarding, "remember_selected_project", lambda record: calls.append("remember")
    )

    service = onboarding.WindowsCloudOnboardingService()
    session = service.start_setup(project)
    assert session.approval_url is None  # Async browser link is not yet ready
    assert ready_for_approval.wait(timeout=5)
    current = service.get_setup_status(session.session_id)
    assert current.status == SetupStatus.PAIRING_PENDING
    assert current.approval_url == (
        onboarding.DEFAULT_CLOUD_ORIGIN + "/devices/pairing#challenge=challenge-id&code=SAMPLE-CODE"
    )
    assert current.user_code == "SAMPLE-CODE"
    assert service.cancel_setup(session.session_id) is False
    assert calls == []  # Browser approval is mandatory
    approved.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if service.get_setup_status(session.session_id).status == SetupStatus.PROJECT_REGISTERED:
            break
        time.sleep(0.02)
    final = service.get_setup_status(session.session_id)
    assert final.status == SetupStatus.PROJECT_REGISTERED
    assert final.project_id == "project-1"
    assert calls == ["enroll", "register", "bind", "remember"]


def test_cancel_before_link_prevents_registration(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reached_worker = threading.Event()
    release_worker = threading.Event()
    registered: list[bool] = []

    def enroll(*, origin: str, alias: str, owner_approval):
        reached_worker.set()
        assert release_worker.wait(timeout=5)
        owner_approval(origin + "/devices/pairing", "challenge", "code")
        raise AssertionError("Owner callback must abort before registration")

    monkeypatch.setattr(onboarding, "enroll_windows_device", enroll)
    monkeypatch.setattr(
        onboarding, "register_windows_project", lambda *a, **k: registered.append(True)
    )
    service = onboarding.WindowsCloudOnboardingService()
    session = service.start_setup(project)
    assert reached_worker.wait(timeout=5)
    assert service.cancel_setup(session.session_id)
    release_worker.set()
    assert service.get_setup_status(session.session_id).status == SetupStatus.CANCELLED
    time.sleep(0.05)
    assert registered == []


def test_other_project_requires_explicit_handoff(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = SimpleNamespace(
        origin=onboarding.DEFAULT_CLOUD_ORIGIN,
        device_id="device",
        project_id="project",
    )
    monkeypatch.setattr(onboarding, "selected_project", lambda: recorded)
    monkeypatch.setattr(
        onboarding,
        "inspect_owner_selected_project",
        lambda _record: SimpleNamespace(directory=project / "other", filename_stem="board"),
    )
    service = onboarding.WindowsCloudOnboardingService()
    with pytest.raises(ValueError, match="explicit owner handoff"):
        service.start_setup(project)
