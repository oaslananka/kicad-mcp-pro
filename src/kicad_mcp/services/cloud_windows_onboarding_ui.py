"""Owner-initiated Windows Cloud pairing for the local dashboard.

Reuses the existing Windows Credential Manager identity and read-only Connector
instead of the POSIX PEM enrollment path. Never stores keys in a web session,
starts Cloud access automatically, or treats scheduled as connected.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from urllib.parse import quote

from kicad_mcp.cloud_windows_connector import remember_selected_project, selected_project
from kicad_mcp.cloud_windows_enrollment import enroll_windows_device, register_windows_project
from kicad_mcp.cloud_windows_local_selection import (
    bind_owner_selected_project,
    inspect_owner_selected_project,
)
from kicad_mcp.services.cloud_onboarding import (
    DEFAULT_CLOUD_ORIGIN,
    OnboardingStep,
    SetupProgress,
    SetupSession,
    SetupStatus,
)


class WindowsCloudOnboardingService:
    """One owner-approved pairing at a time, asynchronously and fail-closed."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, SetupSession] = {}
        self._statuses: dict[str, SetupStatus] = {}
        self._cancelled: set[str] = set()

    def start_setup(
        self,
        project_dir: Path,
        cloud_origin: str = DEFAULT_CLOUD_ORIGIN,
        alias: str | None = None,
    ) -> SetupSession:
        if cloud_origin != DEFAULT_CLOUD_ORIGIN:
            raise ValueError("Untrusted Cloud origin")
        directory = project_dir.resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("Invalid local project")
        matches = sorted(directory.glob("*.kicad_pro"))
        if len(matches) != 1 or not matches[0].is_file():
            raise ValueError("Choose a folder with exactly one KiCad project")
        stem = matches[0].stem

        with self._lock:
            existing = selected_project()
            if existing is not None:
                local = inspect_owner_selected_project(existing)
                selected = (existing.origin, local.directory, local.filename_stem)
                requested = (cloud_origin, directory, stem)
                if selected != requested:
                    raise ValueError("Existing registration needs explicit owner handoff")
                session = SetupSession(
                    session_id=str(uuid.uuid4()),
                    cloud_origin=cloud_origin,
                    project_dir=directory,
                    alias=alias or "My computer",
                    current_step=OnboardingStep.COMPLETE,
                    device_id=existing.device_id,
                    project_id=existing.project_id,
                )
                self._sessions[session.session_id] = session
                self._statuses[session.session_id] = SetupStatus.PROJECT_REGISTERED
                return session
            for sid, state in self._statuses.items():
                if state == SetupStatus.PAIRING_PENDING:
                    previous = self._sessions[sid]
                    if previous.project_dir == directory:
                        return previous
                    raise ValueError("Another owner pairing is in progress")
            session = SetupSession(
                session_id=str(uuid.uuid4()),
                cloud_origin=cloud_origin,
                project_dir=directory,
                alias=alias or "My computer",
                current_step=OnboardingStep.DEVICE_PAIRING_PENDING,
            )
            self._sessions[session.session_id] = session
            self._statuses[session.session_id] = SetupStatus.PAIRING_PENDING
            worker = threading.Thread(
                target=self._enroll, args=(session.session_id, stem), daemon=True
            )
            worker.start()
            return session

    def _enroll(self, sid: str, stem: str) -> None:
        def show_owner_link(page: str, challenge: str, code: str) -> None:
            with self._lock:
                if sid in self._cancelled:
                    raise ValueError("Owner cancelled pairing")
                session = self._sessions[sid]
                session.approval_url = (
                    page
                    + "#challenge="
                    + quote(challenge, safe="")
                    + "&code="
                    + quote(code, safe="")
                )
                session.user_code = code

        try:
            with self._lock:
                if sid in self._cancelled:
                    return
                session = self._sessions[sid]
                origin, alias, directory = (
                    session.cloud_origin,
                    session.alias,
                    session.project_dir,
                )
            device = enroll_windows_device(
                origin=origin, alias=alias, owner_approval=show_owner_link
            )
            with self._lock:
                if sid in self._cancelled:
                    self._sessions[
                        sid
                    ].error = (
                        "Pairing stopped after device approval. Review/revoke it in Cloud Devices."
                    )
                    return
                self._sessions[sid].current_step = OnboardingStep.PROJECT_REGISTRATION_PENDING
            project = register_windows_project(device, alias=stem, filename_stem=stem)
            with self._lock:
                if sid in self._cancelled:
                    self._sessions[
                        sid
                    ].error = "Pairing stopped after project registration. Review Cloud Devices."
                    return
            bind_owner_selected_project(project, directory, owner_confirm=lambda _path: True)
            remember_selected_project(project)
            with self._lock:
                current = self._sessions[sid]
                current.device_id = device.device_id
                current.project_id = project.project_id
                current.current_step = OnboardingStep.COMPLETE
                self._statuses[sid] = SetupStatus.PROJECT_REGISTERED
        except (OSError, RuntimeError, ValueError):
            with self._lock:
                if sid not in self._cancelled:
                    self._statuses[sid] = SetupStatus.FAILED
                    self._sessions[sid].error = (
                        "Windows pairing or project registration did not complete. "
                        "Inspect Cloud Devices before retrying; no Connector was enabled."
                    )

    def get_setup_status(self, session_id: str) -> SetupProgress:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return SetupProgress(
                    session_id=session_id,
                    status=SetupStatus.FAILED,
                    step=OnboardingStep.IDLE,
                    error="Unknown pairing session",
                )
            status = self._statuses[session_id]
            return SetupProgress(
                session_id=session_id,
                status=status,
                step=session.current_step,
                approval_url=session.approval_url,
                user_code=session.user_code,
                device_id=session.device_id,
                project_id=session.project_id,
                error=session.error,
            )

    def cancel_setup(self, session_id: str) -> bool:
        with self._lock:
            if session_id not in self._sessions:
                return False
            if self._statuses[session_id] != SetupStatus.PAIRING_PENDING:
                return False
            # Once a browser challenge exists, an external approval could still
            # complete while the worker is waiting. Refuse to claim cancellation
            # when it cannot revoke a possibly registered remote identity.
            session = self._sessions[session_id]
            if session.approval_url is not None:
                return False
            self._cancelled.add(session_id)
            self._statuses[session_id] = SetupStatus.CANCELLED
            self._sessions[
                session_id
            ].error = "Pairing cancelled locally. If already approved, check Cloud Devices."
            return True
