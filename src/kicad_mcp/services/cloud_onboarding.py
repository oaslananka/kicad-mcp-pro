"""Shared Cloud onboarding service for CLI and graphical surfaces.

Orchestrates device pairing, project registration, active project selection,
cancellation, and error recovery without fabricating bearer tokens or bypasses.
"""

from __future__ import annotations

import os
import stat
import threading
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from kicad_mcp import cloud_pair
from kicad_mcp.cloud_local_registry import default_registry_root
from kicad_mcp.cloud_pair_keys import (
    _open_owner_private_dir,
    _read_owner_binding,
    _write_private_json,
)
from kicad_mcp.cloud_registered_pilot import _single_registered_identity

DEFAULT_CLOUD_ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"
_DEFAULT_DEVICE_ALIAS = "My computer"


class SetupStatus(StrEnum):
    NOT_ENROLLED = "not_enrolled"
    PAIRING_PENDING = "pairing_pending"
    PAIRED = "paired"
    PROJECT_REGISTERED = "project_registered"
    READY = "ready"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OnboardingStep(StrEnum):
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
    approval_url: str | None = None
    user_code: str | None = None
    device_id: str | None = None
    project_id: str | None = None
    key_slot: str | None = None
    error: str | None = None


@dataclass
class SetupProgress:
    session_id: str | None
    status: SetupStatus
    step: OnboardingStep
    device_id: str | None = None
    project_id: str | None = None
    approval_url: str | None = None
    user_code: str | None = None
    error: str | None = None


@dataclass
class RegisterProjectResult:
    success: bool
    project_id: str | None = None
    error: str | None = None


class CloudOnboardingService:
    """Service orchestrating device pairing and project onboarding."""

    def __init__(self, registry_root: Path | None = None) -> None:
        self.root = registry_root if registry_root is not None else default_registry_root()
        self._sessions: dict[str, SetupSession] = {}
        self._lock = threading.RLock()

    def _ensure_registry_dirs(self) -> tuple[Path, Path]:
        projects_dir = self.root / "projects"
        keys_dir = self.root / "keys"
        if self.root.is_symlink() or projects_dir.is_symlink() or keys_dir.is_symlink():
            raise ValueError("Invalid registry directory")
        self.root.mkdir(parents=True, mode=stat.S_IRWXU, exist_ok=True)
        if os.name == "posix":
            fd = _open_owner_private_dir(self.root / "check")
            os.close(fd)
        projects_dir.mkdir(mode=stat.S_IRWXU, exist_ok=True)
        keys_dir.mkdir(mode=stat.S_IRWXU, exist_ok=True)
        if os.name == "posix":
            for directory in (projects_dir, keys_dir):
                fd = _open_owner_private_dir(directory / "check")
                os.close(fd)
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

        # A valid registration for another authority must not be treated as an
        # empty local state. Re-enrollment requires an explicit handoff.
        return SetupProgress(
            session_id=None,
            status=SetupStatus.FAILED,
            step=OnboardingStep.IDLE,
            error="Existing registration belongs to a different Cloud origin.",
        )

    def start_setup(
        self,
        project_dir: Path,
        cloud_origin: str = DEFAULT_CLOUD_ORIGIN,
        alias: str | None = None,
        new_device: bool = False,
    ) -> SetupSession:
        """Start or resume onboarding without blocking. Returns SetupSession."""
        with self._lock:
            return self._start_setup(project_dir, cloud_origin, alias, new_device)

    def _start_setup(
        self, project_dir: Path, cloud_origin: str, alias: str | None, new_device: bool
    ) -> SetupSession:
        project_dir = project_dir.resolve()
        if not project_dir.is_dir() or len(list(project_dir.glob("*.kicad_pro"))) != 1:
            raise ValueError("Select a directory containing exactly one KiCad project")
        cloud_origin = cloud_pair._origin(cloud_origin)[2]
        _, keys_dir = self._ensure_registry_dirs()

        # Check for active session with same project and origin
        for sess in self._sessions.values():
            if (
                sess.project_dir.resolve() == project_dir.resolve()
                and sess.cloud_origin == cloud_origin
                and sess.current_step == OnboardingStep.DEVICE_PAIRING_PENDING
            ):
                return sess

        # A replacement requires the explicit handoff workflow.
        if new_device and any((self.root / "projects").iterdir()):
            raise ValueError("Existing registration requires explicit handoff")

        # Check if already registered
        if not new_device:
            current = self.inspect_current_setup(cloud_origin)
            if (
                current.status == SetupStatus.PROJECT_REGISTERED
                and Path(_single_registered_identity(self.root)["directory"]).resolve()
                == project_dir
            ):
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
            if current.status in (SetupStatus.PROJECT_REGISTERED, SetupStatus.FAILED):
                raise ValueError("Existing registration requires explicit handoff or repair")

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
        """Advance one session once at a time."""
        with self._lock:
            return self._get_setup_status(session_id)

    def _get_setup_status(self, session_id: str) -> SetupProgress:
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
                if not cloud_pair.enrollment_approved(session.cloud_origin, keyfile):
                    return SetupProgress(
                        session_id=session_id,
                        status=SetupStatus.PAIRING_PENDING,
                        step=session.current_step,
                        approval_url=session.approval_url,
                        user_code=session.user_code,
                    )
                device_id, _fingerprint = cloud_pair.redeem_enrollment(
                    session.cloud_origin, keyfile
                )
                session.device_id = device_id
                session.current_step = OnboardingStep.PROJECT_REGISTRATION_PENDING
                return SetupProgress(
                    session_id=session_id,
                    status=SetupStatus.PAIRED,
                    step=session.current_step,
                    device_id=device_id,
                )
            except (OSError, ValueError):
                return SetupProgress(
                    session_id=session_id,
                    status=SetupStatus.FAILED,
                    step=session.current_step,
                    error="Pairing status unavailable",
                )

        if session.current_step == OnboardingStep.PROJECT_REGISTRATION_PENDING:
            result = self.register_project_step(
                session.key_slot or "", session.project_dir, session.cloud_origin
            )
            if not result.success:
                return SetupProgress(
                    session_id=session_id,
                    status=SetupStatus.FAILED,
                    step=session.current_step,
                    error=result.error,
                )
            session.project_id = result.project_id
            session.current_step = OnboardingStep.COMPLETE

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

    def cancel_setup(self, session_id: str = "") -> bool:
        """Cancel a pending setup session and clean up unredeemed keys."""
        with self._lock:
            return self._cancel_setup(session_id)

    def _cancel_setup(self, session_id: str = "") -> bool:
        if not session_id:
            cancelled_any = False
            for sid in list(self._sessions.keys()):
                if self.cancel_setup(sid):
                    cancelled_any = True
            return cancelled_any or True

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
        try:
            if str(uuid.UUID(key_slot)) != key_slot:
                raise ValueError
        except (ValueError, AttributeError):
            return RegisterProjectResult(success=False, error="Invalid key slot")
        projects_dir, keys_dir = self._ensure_registry_dirs()
        if any(projects_dir.iterdir()):
            return RegisterProjectResult(
                success=False, error="Existing registration requires explicit handoff"
            )
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

        pros = list(project_dir.glob("*.kicad_pro")) if project_dir.is_dir() else []
        if len(pros) != 1:
            return RegisterProjectResult(success=False, error="Select exactly one KiCad project")
        stem = pros[0].stem

        try:
            project_res = cloud_pair.register_device_project(cloud_origin, keyfile, alias=stem)
        except cloud_pair.CloudPairingError as exc:
            # Preserves keyfile and binding!
            return RegisterProjectResult(success=False, error=str(exc))

        project_id = str(project_res["projectId"])
        if (
            cloud_pair._UUID.fullmatch(project_id) is None
            or project_res.get("ownerSub") != owner_sub
        ):
            return RegisterProjectResult(success=False, error="Project identity mismatch")
        record = {
            "ownerSub": owner_sub,
            "cloudOrigin": cloud_origin,
            "deviceId": device_id,
            "projectId": project_id,
            "keySlot": key_slot,
            "directory": str(project_dir.resolve()),
            "filenameStem": stem,
        }
        _write_private_json(projects_dir, f"{project_id}.json", record)
        self.select_active_project(project_id)
        return RegisterProjectResult(success=True, project_id=project_id)

    def select_active_project(self, project_id: str) -> bool:
        """Select only a verified local registration."""
        from kicad_mcp.services.connector_lifecycle import ConnectorLifecycleManager

        try:
            ConnectorLifecycleManager(self.root).set_active_project(project_id)
        except (OSError, ValueError):
            return False
        return True

    def get_active_project_id(self) -> str | None:
        from kicad_mcp.services.connector_lifecycle import ConnectorLifecycleManager

        return ConnectorLifecycleManager(self.root).get_active_project_id()
