"""Tests for shared CloudOnboardingService."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.services.cloud_onboarding import (
    CloudOnboardingService,
    OnboardingStep,
    SetupStatus,
)


@pytest.fixture
def tmp_registry(tmp_path: Path) -> Path:
    reg = tmp_path / "cloud_registry"
    reg.mkdir(mode=stat.S_IRWXU)
    (reg / "projects").mkdir(mode=stat.S_IRWXU)
    (reg / "keys").mkdir(mode=stat.S_IRWXU)
    if hasattr(os, "chmod"):
        os.chmod(reg, stat.S_IRWXU)  # nosec B103 # nosemgrep
        os.chmod(reg / "projects", stat.S_IRWXU)  # nosec B103 # nosemgrep
        os.chmod(reg / "keys", stat.S_IRWXU)  # nosec B103 # nosemgrep
    return reg


def test_inspect_clean_setup(tmp_registry) -> None:
    """Clean environment reports unregistered state."""
    service = CloudOnboardingService(registry_root=tmp_registry)
    status = service.inspect_current_setup("https://kicad-mcp-pro.oaslananka.dev")
    assert status.status == SetupStatus.NOT_ENROLLED
    assert status.device_id is None
    assert status.project_id is None


def test_start_setup_initializes_pairing_session(tmp_registry, tmp_path) -> None:
    """start_setup starts pairing flow and returns approval url."""
    proj = tmp_path / "my_project"
    proj.mkdir()
    (proj / "board.kicad_pro").write_text("(kicad_project)")

    service = CloudOnboardingService(registry_root=tmp_registry)

    with patch("kicad_mcp.cloud_pair.start_enrollment") as mock_start:
        mock_start.return_value = (
            "https://kicad-mcp-pro.oaslananka.dev/devices/pair?c=12345",
            "challenge_12345",
            "ABCD-1234",
            300,
        )
        session = service.start_setup(
            project_dir=proj,
            cloud_origin="https://kicad-mcp-pro.oaslananka.dev",
            alias="Test Computer",
        )
        assert session.session_id is not None
        assert session.current_step == OnboardingStep.DEVICE_PAIRING_PENDING
        assert "devices/pair" in session.approval_url
        assert session.user_code == "ABCD-1234"


def test_failure_after_pairing_preserves_paired_keys(tmp_registry, tmp_path) -> None:
    """If project registration fails after pairing succeeds, pairing keys are preserved."""
    proj = tmp_path / "my_project"
    proj.mkdir()
    (proj / "board.kicad_pro").write_text("(kicad_project)")

    service = CloudOnboardingService(registry_root=tmp_registry)

    # Simulate established key and binding
    slot = "a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8d"
    keyfile = tmp_registry / "keys" / f"{slot}.pem"
    keyfile.write_text("DUMMY_KEY")
    binding_file = tmp_registry / "keys" / f"{slot}.pem.cloud-binding-v1.json"
    valid_binding = {
        "origin": "https://kicad-mcp-pro.oaslananka.dev",
        "deviceId": "a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8d",
        "fingerprint": "a" * 64,
        "ownerSub": "usr-456",
    }
    binding_file.write_text(json.dumps(valid_binding))
    if hasattr(os, "chmod"):
        os.chmod(keyfile, 0o600)
        os.chmod(binding_file, 0o600)

    from kicad_mcp.cloud_pair import CloudPairingError

    with (
        patch(
            "kicad_mcp.services.cloud_onboarding._read_owner_binding",
            return_value=valid_binding,
        ),
        patch(
            "kicad_mcp.cloud_pair.register_device_project",
            side_effect=CloudPairingError("Project registration rejected"),
        ),
    ):
        result = service.register_project_step(
            key_slot=slot,
            project_dir=proj,
            cloud_origin="https://kicad-mcp-pro.oaslananka.dev",
        )
        assert result.success is False
        assert result.error == "Project registration rejected"
        # The key and binding must still exist!
        assert keyfile.exists()
        assert binding_file.exists()


def test_cancel_pending_setup_does_not_corrupt_registry(tmp_registry, tmp_path) -> None:
    """Cancelling a pending setup session cleanly stops without corrupting registry."""
    service = CloudOnboardingService(registry_root=tmp_registry)
    with patch("kicad_mcp.cloud_pair.start_enrollment") as mock_start:
        mock_start.return_value = ("http://url", "chal", "code", 300)
        proj = tmp_path / "p"
        proj.mkdir()
        (proj / "x.kicad_pro").write_text("(kicad_project)")
        session = service.start_setup(proj, cloud_origin="https://kicad-mcp-pro.oaslananka.dev")
        cancelled = service.cancel_setup(session.session_id)
        assert cancelled is True
        progress = service.get_setup_status(session.session_id)
        assert progress.status == SetupStatus.CANCELLED


def test_repeated_start_reuses_pending_session(tmp_registry: Path, tmp_path: Path) -> None:
    """Repeated calls with same params return the active session without duplicate devices."""
    service = CloudOnboardingService(registry_root=tmp_registry)
    with patch("kicad_mcp.cloud_pair.start_enrollment") as mock_start:
        mock_start.return_value = ("http://url", "chal", "code", 300)
        proj = tmp_path / "p"
        proj.mkdir()
        (proj / "x.kicad_pro").write_text("(kicad_project)")
        s1 = service.start_setup(proj, cloud_origin="https://kicad-mcp-pro.oaslananka.dev")
        s2 = service.start_setup(proj, cloud_origin="https://kicad-mcp-pro.oaslananka.dev")
        assert s1.session_id == s2.session_id


def test_poll_does_not_redeem_until_signed_approval(tmp_registry, tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "board.kicad_pro").write_text("project")
    service = CloudOnboardingService(tmp_registry)
    with patch("kicad_mcp.cloud_pair.start_enrollment", return_value=("url", "id", "code", 300)):
        session = service.start_setup(project)
    (tmp_registry / "keys" / f"{session.key_slot}.challenge.json").write_text("{}")
    with (
        patch("kicad_mcp.cloud_pair.enrollment_approved", return_value=False),
        patch("kicad_mcp.cloud_pair.redeem_enrollment") as redeem,
    ):
        assert service.get_setup_status(session.session_id).status == SetupStatus.PAIRING_PENDING
        redeem.assert_not_called()


def test_register_rejects_path_traversal_without_network(tmp_registry, tmp_path) -> None:
    service = CloudOnboardingService(tmp_registry)
    with patch("kicad_mcp.cloud_pair.register_device_project") as register:
        result = service.register_project_step("../../outside", tmp_path)
        assert not result.success
        register.assert_not_called()


def test_approval_status_is_signed_and_invalid_response_fails(tmp_path) -> None:
    import base64
    import time

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import cloud_pair

    key = Ed25519PrivateKey.generate()
    challenge = "a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8d"
    device_code = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    data = {
        "origin": "https://cloud.example",
        "challenge": challenge,
        "secret": device_code,
        "expiry": time.time_ns() // 1_000_000 + 60000,
    }

    def post(origin, path, body, status):
        assert path == "/api/v1/pairing/device/status"
        signature = base64.urlsafe_b64decode(body["signature"] + "==")
        key.public_key().verify(
            signature,
            b"kicad-cloud-pairing-status-v1\x00"
            + challenge.encode()
            + b"\x00"
            + device_code.encode(),
        )
        return {"approved": False}

    with (
        patch("kicad_mcp.cloud_pair._read_private_json", return_value=data),
        patch("kicad_mcp.cloud_pair._load_owner_key", return_value=key),
        patch("kicad_mcp.cloud_pair._post", side_effect=post),
    ):
        assert not cloud_pair.enrollment_approved("https://cloud.example", tmp_path / "key.pem")
        data["origin"] = "https://other.example"
        with pytest.raises(cloud_pair.CloudPairingError):
            cloud_pair.enrollment_approved("https://cloud.example", tmp_path / "key.pem")
