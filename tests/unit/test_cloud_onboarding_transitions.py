"""Transition tests for the real local Cloud onboarding state machine.

All network and identity responses are isolated synthetic fixtures. No device is
enrolled and no external Cloud endpoint is contacted by this suite.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.services.cloud_onboarding import (
    DEFAULT_CLOUD_ORIGIN,
    CloudOnboardingService,
    OnboardingStep,
    RegisterProjectResult,
    SetupSession,
    SetupStatus,
)

DEVICE = "00000000-0000-4000-8000-000000000001"
PROJECT = "00000000-0000-4000-8000-000000000002"
SLOT = "00000000-0000-4000-8000-000000000003"


@pytest.fixture
def fixture(tmp_path: Path) -> tuple[CloudOnboardingService, Path, Path]:
    root = tmp_path / "cloud"
    for folder in (root, root / "projects", root / "keys"):
        folder.mkdir(mode=0o700)
    project = tmp_path / "board"
    project.mkdir()
    (project / "board.kicad_pro").write_text("{}", encoding="utf-8")
    return CloudOnboardingService(root), root, project


def registered(project: Path) -> dict[str, str]:
    return {
        "cloudOrigin": DEFAULT_CLOUD_ORIGIN,
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "directory": str(project),
    }


def existing_record(root: Path) -> None:
    (root / "projects" / "registered.json").write_text("{}", encoding="utf-8")


def test_existing_registration_resumes_without_pairing(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    existing_record(root)
    with (
        patch(
            "kicad_mcp.services.cloud_onboarding._single_registered_identity",
            return_value=registered(project),
        ),
        patch("kicad_mcp.cloud_pair.start_enrollment") as enroll,
    ):
        status = service.inspect_current_setup(DEFAULT_CLOUD_ORIGIN)
        assert status.status == SetupStatus.PROJECT_REGISTERED
        assert status.device_id == DEVICE
        assert status.project_id == PROJECT
        session = service.start_setup(project)
        assert session.current_step == OnboardingStep.COMPLETE
        assert service.get_setup_status(session.session_id).project_id == PROJECT
        enroll.assert_not_called()


def test_wrong_cloud_origin_requires_explicit_handoff(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    existing_record(root)
    with (
        patch(
            "kicad_mcp.services.cloud_onboarding._single_registered_identity",
            return_value={**registered(project), "cloudOrigin": "https://other.example"},
        ),
        patch("kicad_mcp.cloud_pair.start_enrollment") as enroll,
    ):
        assert service.inspect_current_setup(DEFAULT_CLOUD_ORIGIN).status == SetupStatus.FAILED
        with pytest.raises(ValueError, match="handoff or repair"):
            service.start_setup(project)
        enroll.assert_not_called()


def test_broken_registration_does_not_become_an_empty_setup(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    existing_record(root)
    with patch(
        "kicad_mcp.services.cloud_onboarding._single_registered_identity",
        side_effect=ValueError("invalid registry"),
    ):
        assert service.inspect_current_setup(DEFAULT_CLOUD_ORIGIN).status == SetupStatus.FAILED
        with pytest.raises(ValueError, match="handoff or repair"):
            service.start_setup(project)


def test_new_device_requires_explicit_replacement(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    existing_record(root)
    with patch("kicad_mcp.cloud_pair.start_enrollment") as enroll:
        with pytest.raises(ValueError, match="explicit handoff"):
            service.start_setup(project, new_device=True)
        enroll.assert_not_called()


def test_missing_and_ambiguous_project_files_are_denied(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, _, project = fixture
    (project / "another.kicad_pro").write_text("{}", encoding="utf-8")
    with patch("kicad_mcp.cloud_pair.start_enrollment") as enroll:
        with pytest.raises(ValueError, match="exactly one"):
            service.start_setup(project)
        with pytest.raises(ValueError, match="exactly one"):
            service.start_setup(project / "not-there")
        enroll.assert_not_called()


def pending(
    service: CloudOnboardingService, root: Path, project: Path, *, challenge: bool = True
) -> SetupSession:
    keyfile = root / "keys" / f"{SLOT}.pem"
    keyfile.write_text("synthetic-key", encoding="utf-8")
    if challenge:
        keyfile.with_suffix(".challenge.json").write_text("{}", encoding="utf-8")
    session = SetupSession(
        session_id="session-one",
        cloud_origin=DEFAULT_CLOUD_ORIGIN,
        project_dir=project,
        alias="test",
        current_step=OnboardingStep.DEVICE_PAIRING_PENDING,
        approval_url="https://example.test/pair",
        user_code="TEST",
        key_slot=SLOT,
    )
    service._sessions[session.session_id] = session
    return session


def test_poll_missing_session_and_challenge_is_fail_closed(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    assert service.get_setup_status("unknown").status == SetupStatus.FAILED
    session = pending(service, root, project, challenge=False)
    result = service.get_setup_status(session.session_id)
    assert result.status == SetupStatus.FAILED
    assert result.error == "Challenge context missing"


def test_pairing_pending_approved_and_registered_transitions(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    session = pending(service, root, project)
    with (
        patch("kicad_mcp.cloud_pair.enrollment_approved", side_effect=[False, True]),
        patch("kicad_mcp.cloud_pair.redeem_enrollment", return_value=(DEVICE, "fingerprint")),
    ):
        assert service.get_setup_status(session.session_id).status == SetupStatus.PAIRING_PENDING
        paired = service.get_setup_status(session.session_id)
        assert paired.status == SetupStatus.PAIRED
        assert paired.device_id == DEVICE
        assert paired.step == OnboardingStep.PROJECT_REGISTRATION_PENDING
    with patch.object(
        service, "register_project_step", return_value=RegisterProjectResult(True, PROJECT)
    ) as register:
        complete = service.get_setup_status(session.session_id)
        assert complete.status == SetupStatus.PROJECT_REGISTERED
        assert complete.project_id == PROJECT
        assert service.get_setup_status(session.session_id).project_id == PROJECT
        register.assert_called_once()


def test_redeem_and_registration_errors_do_not_fabricate_ready(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    session = pending(service, root, project)
    with patch("kicad_mcp.cloud_pair.enrollment_approved", side_effect=OSError("offline")):
        result = service.get_setup_status(session.session_id)
        assert result.status == SetupStatus.FAILED
        assert "offline" not in (result.error or "")
    session.current_step = OnboardingStep.PROJECT_REGISTRATION_PENDING
    with patch.object(
        service, "register_project_step", return_value=RegisterProjectResult(False, error="denied")
    ):
        result = service.get_setup_status(session.session_id)
        assert result.status == SetupStatus.FAILED
        assert result.error == "denied"
        assert session.current_step == OnboardingStep.PROJECT_REGISTRATION_PENDING


def test_cancel_removes_only_unredeemed_material(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    session = pending(service, root, project)
    keyfile = root / "keys" / f"{SLOT}.pem"
    challenge = keyfile.with_suffix(".challenge.json")
    assert service.cancel_setup(session.session_id)
    assert not keyfile.exists()
    assert not challenge.exists()
    assert service.get_setup_status(session.session_id).status == SetupStatus.CANCELLED
    assert not service.cancel_setup("absent")


def test_paired_key_is_retained_on_cancel_and_bulk_cancel_is_bounded(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    session = pending(service, root, project, challenge=False)
    keyfile = root / "keys" / f"{SLOT}.pem"
    assert service.cancel_setup()
    assert keyfile.exists()
    assert service.get_setup_status(session.session_id).status == SetupStatus.CANCELLED


def test_registered_project_checks_binding_and_owner_before_writing(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    keyfile = root / "keys" / f"{SLOT}.pem"
    keyfile.write_text("synthetic-key", encoding="utf-8")
    with (
        patch(
            "kicad_mcp.services.cloud_onboarding._read_owner_binding",
            return_value={"deviceId": DEVICE, "ownerSub": "owner-one"},
        ),
        patch(
            "kicad_mcp.cloud_pair.register_device_project",
            return_value={"projectId": PROJECT, "ownerSub": "owner-two"},
        ),
    ):
        result = service.register_project_step(SLOT, project)
        assert not result.success
        assert result.error == "Project identity mismatch"
        assert not any((root / "projects").iterdir())


def test_successful_registration_records_exact_owner_project_binding(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    keyfile = root / "keys" / f"{SLOT}.pem"
    keyfile.write_text("synthetic-key", encoding="utf-8")
    with (
        patch(
            "kicad_mcp.services.cloud_onboarding._read_owner_binding",
            return_value={"deviceId": DEVICE, "ownerSub": "owner-one"},
        ),
        patch(
            "kicad_mcp.cloud_pair.register_device_project",
            return_value={"projectId": PROJECT, "ownerSub": "owner-one"},
        ) as network,
        patch.object(service, "select_active_project", return_value=True) as select,
    ):
        result = service.register_project_step(SLOT, project)
    assert result.success
    assert result.project_id == PROJECT
    assert keyfile.exists()
    network.assert_called_once()
    select.assert_called_once_with(PROJECT)
    record = (root / "projects" / f"{PROJECT}.json").read_text(encoding="utf-8")
    saved = json.loads(record)
    assert saved["directory"] == str(project.resolve())
    assert saved["ownerSub"] == "owner-one"


def test_invalid_registration_rejects_missing_key_or_corrupt_binding(
    fixture: tuple[CloudOnboardingService, Path, Path],
) -> None:
    service, root, project = fixture
    assert not service.register_project_step(SLOT, project).success
    keyfile = root / "keys" / f"{SLOT}.pem"
    keyfile.write_text("synthetic-key", encoding="utf-8")
    with patch(
        "kicad_mcp.services.cloud_onboarding._read_owner_binding",
        side_effect=ValueError("bad binding"),
    ):
        result = service.register_project_step(SLOT, project)
    assert not result.success
    # Error must be containable at the owner API, never interpreted as success.
    assert "Invalid key binding" in (result.error or "")
