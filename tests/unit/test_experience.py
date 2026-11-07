"""Tests for experience view model, readiness calculation, and next action derivation."""

import pytest
from pathlib import Path

from kicad_mcp.services.experience import (
    ReadinessStatus,
    EngineCapabilities,
    ExperienceSnapshot,
    calculate_experience_snapshot,
    sanitize_experience_for_cloud,
)


def test_local_mode_ready_without_cloud_account():
    """Local mode with valid project and available CLI must be Ready without Cloud account."""
    snapshot = calculate_experience_snapshot(
        mode="local",
        project_dir=Path("/workspace/project"),
        has_kicad_project=True,
        cli_available=True,
        ipc_available=False,  # IPC unavailable does not block saved-file workflow
    )
    assert snapshot.readiness == ReadinessStatus.READY.value
    assert snapshot.engine_capabilities.file_available is True
    assert snapshot.engine_capabilities.cli_available is True
    assert snapshot.engine_capabilities.ipc_available is False
    assert snapshot.reason_code == "local_ready"
    assert "open_project" in snapshot.available_actions or "configure_ai" in snapshot.available_actions


def test_local_mode_requires_project_selection():
    """Local mode with no project directory selected must require project selection."""
    snapshot = calculate_experience_snapshot(
        mode="local",
        project_dir=None,
        has_kicad_project=False,
        cli_available=True,
        ipc_available=False,
    )
    assert snapshot.readiness == ReadinessStatus.PROJECT_SELECTION_REQUIRED.value
    assert snapshot.next_action is not None
    assert snapshot.next_action.id == "select_project"
    assert snapshot.reason_code == "project_selection_required"


def test_cloud_mode_requires_device_approval():
    """Cloud mode with account signed in but unapproved device requires device approval."""
    snapshot = calculate_experience_snapshot(
        mode="cloud",
        project_dir=Path("/workspace/project"),
        has_kicad_project=True,
        cli_available=True,
        account_authenticated=True,
        device_paired=False,
    )
    assert snapshot.readiness == ReadinessStatus.DEVICE_APPROVAL_REQUIRED.value
    assert snapshot.next_action.id == "approve_device"
    assert snapshot.reason_code == "device_approval_required"


def test_revoked_grant_overrides_cached_ready():
    """Revoked device/client grant must override any ready state with priority."""
    snapshot = calculate_experience_snapshot(
        mode="cloud",
        project_dir=Path("/workspace/project"),
        has_kicad_project=True,
        cli_available=True,
        account_authenticated=True,
        device_paired=True,
        device_revoked=True,
    )
    assert snapshot.readiness == ReadinessStatus.DEVICE_REVOKED.value
    assert snapshot.reason_code == "device_revoked"
    assert snapshot.next_action.id == "reconnect_device"


def test_unrelated_computer_or_project_does_not_satisfy_current_step():
    """Different computer or project registration does not satisfy the active target."""
    snapshot = calculate_experience_snapshot(
        mode="cloud",
        project_dir=Path("/workspace/project-alpha"),
        has_kicad_project=True,
        cli_available=True,
        account_authenticated=True,
        device_paired=True,
        active_cloud_project_id="proj-beta-unrelated",
        target_local_project_id="proj-alpha",
    )
    assert snapshot.readiness == ReadinessStatus.PROJECT_SELECTION_REQUIRED.value
    assert snapshot.reason_code == "active_project_mismatch"


def test_cloud_sanitization_removes_local_paths_and_secrets():
    """Cloud snapshot must not expose local filesystem paths or secret keys."""
    snapshot = calculate_experience_snapshot(
        mode="local",
        project_dir=Path("C:/Users/SecretUser/Projects/ConfidentialBoard"),
        has_kicad_project=True,
        cli_available=True,
    )
    sanitized = sanitize_experience_for_cloud(snapshot)
    assert "C:/Users" not in str(sanitized)
    assert "ConfidentialBoard" not in str(sanitized)
    assert "private_key" not in sanitized
    assert "secret" not in str(sanitized)
