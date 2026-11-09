"""Isolated native Windows UI enrollment lifecycle; no Cloud/network/credentials."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.services import cloud_windows_onboarding_ui as onboarding
from kicad_mcp.services.cloud_onboarding import SetupStatus


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


@pytest.fixture
def deferred_pairing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold only the module's worker to test owner boundaries deterministically."""

    class DeferredThread:
        def __init__(self, *, target: object, args: tuple[str, str], daemon: bool) -> None:
            assert daemon is True
            self.target, self.args = target, args

        def start(self) -> None:
            pass

    monkeypatch.setattr(
        onboarding,
        "threading",
        SimpleNamespace(RLock=threading.RLock, Thread=DeferredThread),
    )


def test_windows_owner_setup_rejects_untrusted_or_non_project_folders(
    project: Path,
) -> None:
    service = onboarding.WindowsCloudOnboardingService()
    with pytest.raises(ValueError, match="Untrusted Cloud origin"):
        service.start_setup(project, cloud_origin="https://untrusted.example")
    with pytest.raises(ValueError, match="Invalid local project"):
        service.start_setup(project / "board.kicad_pro")
    other = project / "empty"
    other.mkdir()
    with pytest.raises(ValueError, match="exactly one KiCad project"):
        service.start_setup(other)
    (other / "one.kicad_pro").touch()
    (other / "two.kicad_pro").touch()
    with pytest.raises(ValueError, match="exactly one KiCad project"):
        service.start_setup(other)


def test_windows_same_owner_registration_is_reused_without_new_approval(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = SimpleNamespace(
        origin=onboarding.DEFAULT_CLOUD_ORIGIN,
        device_id="previous-device",
        project_id="previous-project",
    )
    monkeypatch.setattr(onboarding, "selected_project", lambda: record)
    monkeypatch.setattr(
        onboarding,
        "inspect_owner_selected_project",
        lambda _record: SimpleNamespace(directory=project, filename_stem="board"),
    )
    service = onboarding.WindowsCloudOnboardingService()
    current = service.start_setup(project)
    status = service.get_setup_status(current.session_id)
    assert status.status == SetupStatus.PROJECT_REGISTERED
    assert status.device_id == "previous-device"
    assert status.project_id == "previous-project"
    assert service.cancel_setup(current.session_id) is False
    assert current.approval_url is None


def test_windows_pending_pairing_same_project_is_idempotent_not_hijacked(
    project: Path, deferred_pairing
) -> None:
    service = onboarding.WindowsCloudOnboardingService()
    first = service.start_setup(project)
    assert service.start_setup(project) is first
    other = project / "other"
    other.mkdir()
    (other / "other.kicad_pro").touch()
    with pytest.raises(ValueError, match="Another owner pairing"):
        service.start_setup(other)
    unknown = service.get_setup_status("unknown")
    assert unknown.status == SetupStatus.FAILED
    assert "Unknown pairing" in unknown.error
    assert service.cancel_setup("unknown") is False
    assert service.cancel_setup(first.session_id) is True
    assert service.get_setup_status(first.session_id).status == SetupStatus.CANCELLED
    # Work started after local cancellation must never call enrollment.
    service._enroll(first.session_id, "board")


def test_windows_pairing_exception_fails_closed_without_connecting(
    project: Path, monkeypatch: pytest.MonkeyPatch, deferred_pairing
) -> None:
    service = onboarding.WindowsCloudOnboardingService()
    session = service.start_setup(project)

    def fail(*, origin: str, alias: str, owner_approval):
        raise OSError("private credential path")

    monkeypatch.setattr(onboarding, "enroll_windows_device", fail)
    service._enroll(session.session_id, "board")
    status = service.get_setup_status(session.session_id)
    assert status.status == SetupStatus.FAILED
    assert "no Connector was enabled" in status.error
    assert "private credential path" not in status.error
    assert service.cancel_setup(session.session_id) is False


@pytest.mark.parametrize("cancellation_stage", ["device", "project"])
def test_windows_late_approval_cancellation_never_binds_local_project(
    project: Path, monkeypatch: pytest.MonkeyPatch, deferred_pairing, cancellation_stage: str
) -> None:
    service = onboarding.WindowsCloudOnboardingService()
    session = service.start_setup(project)
    registered: list[str] = []

    def enroll(*, origin: str, alias: str, owner_approval):
        if cancellation_stage == "device":
            service._cancelled.add(session.session_id)
        return SimpleNamespace(device_id="remote-device")

    def register(_device, *, alias: str, filename_stem: str):
        registered.append("registered")
        if cancellation_stage == "project":
            service._cancelled.add(session.session_id)
        return SimpleNamespace(project_id="remote-project")

    monkeypatch.setattr(onboarding, "enroll_windows_device", enroll)
    monkeypatch.setattr(onboarding, "register_windows_project", register)
    monkeypatch.setattr(
        onboarding,
        "bind_owner_selected_project",
        lambda *_args, **_kwargs: pytest.fail("No local project binding after owner cancellation"),
    )
    monkeypatch.setattr(
        onboarding,
        "remember_selected_project",
        lambda *_args: pytest.fail("No local identity after owner cancellation"),
    )
    service._enroll(session.session_id, "board")
    state = service.get_setup_status(session.session_id)
    assert state.project_id is None
    assert state.error is not None
    assert "Review" in state.error
    assert registered == ([] if cancellation_stage == "device" else ["registered"])
