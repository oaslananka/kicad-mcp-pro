"""Shared Cloud onboarding service for CLI and graphical surfaces.

Orchestrates device pairing, project registration, active project selection,
cancellation, and error recovery without fabricating bearer tokens or bypasses.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from kicad_mcp.cloud_local_registry import default_registry_root
from kicad_mcp import cloud_pair
from kicad_mcp.cloud_pair_keys import _read_owner_binding
from kicad_mcp.cloud_registered_pilot import _single_registered_identity

DEFAULT_CLOUD_ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"
_DEFAULT_DEVICE_ALIAS = "My computer"


class SetupStatus(str, Enum):
    NOT_ENROLLED = "not_enrolled"
    PAIRING_PENDING = "pairing_pending"
    PAIRED = "paired"
    PROJECT_REGISTERED = "project_registered"
    READY = "ready"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OnboardingStep(str, Enum):
    IDLE = "idle"
    DEVICE_PAIRING_PENDING = "device_pairing_pending"
    PROJECT_REGISTRATION_PENDING = "project_registration_pending"
    CONNECTOR_STARTING = "connector_starting"
    COMPLETE = "complete"


@dataclass
class SetupSession:
    session_id: str
    cloud_origin: str
    project_dir: Path
    alias: str
    current_step: OnboardingStep
    approval_url: Optional[str] = None
    user_code: Optional[str] = None
    device_id: Optional[str] = None
    project_id: Optional[str] = None
    key_slot: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SetupProgress:
    session_id: Optional[str]
    status: SetupStatus
    step: OnboardingStep
    device_id: Optional[str] = None
    project_id: Optional[str] = None
    approval_url: Optional[str] = None
    user_code: Optional[str] = None
    error: Optional[str] = None


@dataclass
class RegisterProjectResult:
    success: bool
    project_id: Optional[str] = None
    error: Optional[str] = None


class CloudOnboardingService:
    """Service orchestrating device pairing and project onboarding."""

    def __init__(self, registry_root: Optional[Path] = None) -> None:
        self.root = registry_root if registry_root is not None else default_registry_root()
        self._sessions: dict[str, SetupSession] = {}

    def _ensure_registry_dirs(self) -> tuple[Path, Path]:
        projects_dir = self.root / "projects"
        keys_dir = self.root / "keys"
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        projects_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        keys_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if hasattr(os, "chmod"):
            os.chmod(self.root, 0o700)
            os.chmod(projects_dir, 0o700)
            os.chmod(keys_dir, 0o700)
        return projects_dir, keys_dir

    def inspect_current_setup(self, cloud_origin: str) -> SetupProgress:
        """Inspect current local registration for the given Cloud origin."""
        projects_dir = self.root / "projects"
        if not (projects_dir.exists() and any(projects_dir.iterdir())):
            return SetupProgress(
                session_id=None,
                status=SetupStatus.NOT_ENROLLED,
                step=OnboardingStep.IDLE,
            )

        try:
            existing = _single_registered_identity(self.root)
        except Exception:
            return SetupProgress(
                session_id=None,
                status=SetupStatus.FAILED,
                step=OnboardingStep.IDLE,
                error="Existing registration needs local repair.",
            )

        if existing.get("cloudOrigin") == cloud_origin:
            return SetupProgress(
                session_id=None,
                status=SetupStatus.PROJECT_REGISTERED,
                step=OnboardingStep.COMPLETE,
                device_id=existing.get("deviceId"),
                project_id=existing.get("projectId"),
            )

        return SetupProgress(
            session_id=None,
            status=SetupStatus.NOT_ENROLLED,
            step=OnboardingStep.IDLE,
        )

    def start_setup(
        self,
        project_dir: Path,
        cloud_origin: str = DEFAULT_CLOUD_ORIGIN,
        alias: Optional[str] = None,
        new_device: bool = False,
    ) -> SetupSession:
        """Start or resume onboarding without blocking. Returns SetupSession."""
        _, keys_dir = self._ensure_registry_dirs()

        # Check for active session with same project and origin
        for sess in self._sessions.values():
            if (
                sess.project_dir.resolve() == project_dir.resolve()
                and sess.cloud_origin == cloud_origin
                and sess.current_step == OnboardingStep.DEVICE_PAIRING_PENDING
            ):
                return sess

        # Check if already registered
        if not new_device:
            current = self.inspect_current_setup(cloud_origin)
            if current.status == SetupStatus.PROJECT_REGISTERED:
                session_id = str(uuid.uuid4())
                sess = SetupSession(
                    session_id=session_id,
                    cloud_origin=cloud_origin,
                    project_dir=project_dir,
                    alias=alias or _DEFAULT_DEVICE_ALIAS,
                    current_step=OnboardingStep.COMPLETE,
                    device_id=current.device_id,
                    project_id=current.project_id,
                )
                self._sessions[session_id] = sess
                return sess

        device_alias = alias or _DEFAULT_DEVICE_ALIAS
        slot = str(uuid.uuid4())
        keyfile = keys_dir / f"{slot}.pem"

        approval_url, challenge, code, expires_in = cloud_pair.start_enrollment(
            cloud_origin, device_alias, keyfile
        )

        session_id = str(uuid.uuid4())
        session = SetupSession(
            session_id=session_id,
            cloud_origin=cloud_origin,
            project_dir=project_dir,
            alias=device_alias,
            current_step=OnboardingStep.DEVICE_PAIRING_PENDING,
            approval_url=approval_url,
            user_code=code,
            key_slot=slot,
        )
        self._sessions[session_id] = session
        return session

    def get_setup_status(self, session_id: str) -> SetupProgress:
        """Get progress for a setup session."""
        session = self._sessions.get(session_id)
        if not session:
            return SetupProgress(
                session_id=session_id,
                status=SetupStatus.FAILED,
                step=OnboardingStep.IDLE,
                error="Session not found",
            )

        if session.current_step == OnboardingStep.DEVICE_PAIRING_PENDING:
            # Check if approval can be redeemed
            keyfile = self.root / "keys" / f"{session.key_slot}.pem"
            chal_file = keyfile.with_suffix(".challenge.json")
            if not chal_file.exists():
                return SetupProgress(
                    session_id=session_id,
                    status=SetupStatus.FAILED,
                    step=session.current_step,
                    error="Challenge context missing",
                )
            try:
                device_id, fingerprint = cloud_pair.redeem_enrollment(session.cloud_origin, keyfile)
                session.device_id = device_id
                session.current_step = OnboardingStep.PROJECT_REGISTRATION_PENDING
                return SetupProgress(
                    session_id=session_id,
                    status=SetupStatus.PAIRED,
                    step=session.current_step,
                    device_id=device_id,
                )
            except cloud_pair.CloudPairingError:
                # Still waiting for user approval
                return SetupProgress(
                    session_id=session_id,
                    status=SetupStatus.PAIRING_PENDING,
                    step=session.current_step,
                    approval_url=session.approval_url,
                    user_code=session.user_code,
                )

        if session.current_step == OnboardingStep.PROJECT_REGISTRATION_PENDING:
            return SetupProgress(
                session_id=session_id,
                status=SetupStatus.PAIRED,
                step=session.current_step,
                device_id=session.device_id,
            )

        if session.current_step == OnboardingStep.COMPLETE:
            return SetupProgress(
                session_id=session_id,
                status=SetupStatus.PROJECT_REGISTERED,
                step=session.current_step,
                device_id=session.device_id,
                project_id=session.project_id,
            )

        return SetupProgress(
            session_id=session_id,
            status=SetupStatus.CANCELLED if session.error == "cancelled" else SetupStatus.FAILED,
            step=session.current_step,
            error=session.error,
        )

    def cancel_setup(self, session_id: str) -> bool:
        """Cancel a pending setup session and clean up unredeemed keys."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session.current_step = OnboardingStep.IDLE
        session.error = "cancelled"

        if session.key_slot:
            keyfile = self.root / "keys" / f"{session.key_slot}.pem"
            chal_file = keyfile.with_suffix(".challenge.json")
            # Only remove unredeemed keys (challenge file still exists)
            if chal_file.exists():
                chal_file.unlink(missing_ok=True)
                keyfile.unlink(missing_ok=True)

        return True

    def register_project_step(
        self,
        key_slot: str,
        project_dir: Path,
        cloud_origin: str = DEFAULT_CLOUD_ORIGIN,
    ) -> RegisterProjectResult:
        """Register project using an already-paired key, preserving paired keys on failure."""
        projects_dir, keys_dir = self._ensure_registry_dirs()
        keyfile = keys_dir / f"{key_slot}.pem"
        if not keyfile.exists():
            return RegisterProjectResult(success=False, error="Keyfile does not exist")

        try:
            bound = _read_owner_binding(keyfile)
        except Exception as exc:
            return RegisterProjectResult(success=False, error=f"Invalid key binding: {exc}")

        owner_sub = bound.get("ownerSub")
        device_id = bound.get("deviceId")
        if not owner_sub or not device_id:
            return RegisterProjectResult(success=False, error="Owner identity or device ID missing")

        stem = project_dir.name
        pros = list(project_dir.glob("*.kicad_pro"))
        if pros:
            stem = pros[0].stem

        try:
            project_res = cloud_pair.register_device_project(cloud_origin, keyfile, alias=stem)
        except cloud_pair.CloudPairingError as exc:
            # Preserves keyfile and binding!
            return RegisterProjectResult(success=False, error=str(exc))

        project_id = str(project_res["projectId"])
        record = {
            "ownerSub": owner_sub,
            "cloudOrigin": cloud_origin,
            "deviceId": device_id,
            "projectId": project_id,
            "keySlot": key_slot,
            "directory": str(project_dir.resolve()),
            "filenameStem": stem,
        }
        record_file = projects_dir / f"{project_id}.json"
        with open(record_file, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        if hasattr(os, "chmod"):
            os.chmod(record_file, 0o600)

        # Set as active project
        self.select_active_project(project_id)
        return RegisterProjectResult(success=True, project_id=project_id)

    def select_active_project(self, project_id: str) -> bool:
        """Set the active Cloud project pointer."""
        record_file = self.root / "projects" / f"{project_id}.json"
        if not record_file.exists():
            return False
        active_file = self.root / "active_project.json"
        with open(active_file, "w", encoding="utf-8") as f:
            json.dump({"activeProjectId": project_id, "updatedAt": time.time()}, f)
        if hasattr(os, "chmod"):
            os.chmod(active_file, 0o600)
        return True

    def get_active_project_id(self) -> Optional[str]:
        """Read the currently active Cloud project ID."""
        active_file = self.root / "active_project.json"
        if active_file.exists():
            try:
                with open(active_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("activeProjectId")
            except Exception:
                pass
        # Fall back to single project in registry if only one exists
        projects_dir = self.root / "projects"
        if projects_dir.exists():
            projs = list(projects_dir.glob("*.json"))
            if len(projs) == 1:
                return projs[0].stem
        return None
