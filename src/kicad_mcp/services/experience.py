"""Read-only experience view model, readiness calculation, and next action derivation.

Derives experience state from real runtime data without assuming static setup completion.
Supports both account-free local mode and authenticated cloud mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ReadinessStatus(str, Enum):
    """Operation-specific readiness state."""
    READY = "ready"
    ACCOUNT_REQUIRED = "account_required"
    DEVICE_APPROVAL_REQUIRED = "device_approval_required"
    DEVICE_REVOKED = "device_revoked"
    PROJECT_SELECTION_REQUIRED = "project_selection_required"
    AI_CONNECTION_REQUIRED = "ai_connection_required"
    PROJECT_GRANT_REQUIRED = "project_grant_required"
    CONNECTOR_DISABLED = "connector_disabled"
    CONNECTOR_CONNECTING = "connector_connecting"
    CONNECTOR_UNREACHABLE = "connector_unreachable"
    ENGINE_CAPABILITY_UNAVAILABLE = "engine_capability_unavailable"
    UNKNOWN_STALE = "unknown_stale"


@dataclass(frozen=True)
class EngineCapabilities:
    """Sanitized KiCad engine availability."""
    cli_available: bool = False
    ipc_available: bool = False
    file_available: bool = False
    drc_available: bool = False


@dataclass(frozen=True)
class NextAction:
    """Actionable next step for the user."""
    id: str
    title: str
    description: str
    target_route: str


@dataclass
class ExperienceSnapshot:
    """Consolidated experience view model for desktop, local web, and cloud."""
    mode: str  # "local" | "cloud"
    readiness: str  # ReadinessStatus value
    reason_code: str
    engine_capabilities: EngineCapabilities
    project: Optional[dict[str, Any]] = None
    computer: Optional[dict[str, Any]] = None
    ai_client: Optional[dict[str, Any]] = None
    account: Optional[dict[str, Any]] = None
    device_pairing: Optional[dict[str, Any]] = None
    project_registration: Optional[dict[str, Any]] = None
    client_grant: Optional[dict[str, Any]] = None
    local_connector: dict[str, Any] = field(default_factory=lambda: {"enabled": True, "running": True})
    cloud_connector: dict[str, Any] = field(default_factory=lambda: {"enabled": False, "connected": False})
    next_action: Optional[NextAction] = None
    available_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to dictionary representation."""
        data = asdict(self)
        if self.next_action:
            data["next_action"] = asdict(self.next_action)
        data["engine_capabilities"] = asdict(self.engine_capabilities)
        return data


def calculate_experience_snapshot(
    *,
    mode: str = "local",
    project_dir: Optional[Path | str] = None,
    has_kicad_project: bool = False,
    cli_available: bool = False,
    ipc_available: bool = False,
    account_authenticated: bool = False,
    device_paired: bool = False,
    device_revoked: bool = False,
    client_granted: bool = True,
    cloud_connector_enabled: bool = False,
    cloud_connector_status: str = "idle",
    active_cloud_project_id: Optional[str] = None,
    target_local_project_id: Optional[str] = None,
    computer_id: Optional[str] = None,
    ai_client_name: Optional[str] = None,
) -> ExperienceSnapshot:
    """Derive an experience snapshot from real state."""
    p_path = Path(project_dir) if project_dir else None
    valid_project = bool(p_path and has_kicad_project)

    engine_caps = EngineCapabilities(
        cli_available=cli_available,
        ipc_available=ipc_available,
        file_available=bool(valid_project and (cli_available or p_path.is_dir())),
        drc_available=cli_available,
    )

    available_actions: list[str] = ["select_project", "configure_ai"]

    project_info: Optional[dict[str, Any]] = None
    if p_path:
        project_info = {
            "path": str(p_path),
            "name": p_path.name,
            "valid": valid_project,
        }

    computer_info: Optional[dict[str, Any]] = None
    if computer_id or device_paired:
        computer_info = {
            "id": computer_id or "local",
            "alias": "This computer",
            "registered": device_paired,
        }

    ai_client_info: Optional[dict[str, Any]] = None
    if ai_client_name:
        ai_client_info = {
            "name": ai_client_name,
            "configured": True,
            "grant_status": "granted" if client_granted else "pending",
        }

    # 1. Device revocation overrides everything
    if device_revoked:
        return ExperienceSnapshot(
            mode=mode,
            readiness=ReadinessStatus.DEVICE_REVOKED.value,
            reason_code="device_revoked",
            engine_capabilities=engine_caps,
            project=project_info,
            computer=computer_info,
            ai_client=ai_client_info,
            next_action=NextAction(
                id="reconnect_device",
                title="Reconnect device",
                description="Device access was revoked. Re-enroll to restore access.",
                target_route="/cloud/pair",
            ),
            available_actions=["reconnect_device", "configure_ai"],
        )

    # 2. Cloud mode checks
    if mode == "cloud":
        if not account_authenticated:
            return ExperienceSnapshot(
                mode=mode,
                readiness=ReadinessStatus.ACCOUNT_REQUIRED.value,
                reason_code="account_required",
                engine_capabilities=engine_caps,
                project=project_info,
                computer=computer_info,
                ai_client=ai_client_info,
                next_action=NextAction(
                    id="sign_in",
                    title="Sign in",
                    description="Sign in to your Cloud account to use web AI.",
                    target_route="/cloud/login",
                ),
                available_actions=["sign_in", "use_local_mode"],
            )

        if not device_paired:
            return ExperienceSnapshot(
                mode=mode,
                readiness=ReadinessStatus.DEVICE_APPROVAL_REQUIRED.value,
                reason_code="device_approval_required",
                engine_capabilities=engine_caps,
                project=project_info,
                computer=computer_info,
                ai_client=ai_client_info,
                next_action=NextAction(
                    id="approve_device",
                    title="Approve computer",
                    description="Approve this computer in your browser to enable secure connection.",
                    target_route="/cloud/pair",
                ),
                available_actions=["approve_device", "use_local_mode"],
            )

        if not valid_project:
            return ExperienceSnapshot(
                mode=mode,
                readiness=ReadinessStatus.PROJECT_SELECTION_REQUIRED.value,
                reason_code="project_selection_required",
                engine_capabilities=engine_caps,
                project=project_info,
                computer=computer_info,
                ai_client=ai_client_info,
                next_action=NextAction(
                    id="select_project",
                    title="Select project",
                    description="Choose a KiCad project folder to share with web AI.",
                    target_route="/projects",
                ),
                available_actions=["select_project", "use_local_mode"],
            )

        # One active project check: if active cloud project differs from target local project
        if (
            active_cloud_project_id
            and target_local_project_id
            and active_cloud_project_id != target_local_project_id
        ):
            return ExperienceSnapshot(
                mode=mode,
                readiness=ReadinessStatus.PROJECT_SELECTION_REQUIRED.value,
                reason_code="active_project_mismatch",
                engine_capabilities=engine_caps,
                project=project_info,
                computer=computer_info,
                ai_client=ai_client_info,
                next_action=NextAction(
                    id="select_active_project",
                    title="Switch active project",
                    description="The selected local project does not match the active Cloud project.",
                    target_route="/projects",
                ),
                available_actions=["select_active_project", "use_local_mode"],
            )

        if not client_granted:
            return ExperienceSnapshot(
                mode=mode,
                readiness=ReadinessStatus.PROJECT_GRANT_REQUIRED.value,
                reason_code="project_grant_required",
                engine_capabilities=engine_caps,
                project=project_info,
                computer=computer_info,
                ai_client=ai_client_info,
                next_action=NextAction(
                    id="grant_access",
                    title="Grant project access",
                    description="Grant the connected AI client permission to inspect this project.",
                    target_route="/cloud/grants",
                ),
                available_actions=["grant_access", "change_project"],
            )

        if not cloud_connector_enabled:
            return ExperienceSnapshot(
                mode=mode,
                readiness=ReadinessStatus.CONNECTOR_DISABLED.value,
                reason_code="connector_disabled",
                engine_capabilities=engine_caps,
                project=project_info,
                computer=computer_info,
                ai_client=ai_client_info,
                next_action=NextAction(
                    id="enable_connector",
                    title="Start connector",
                    description="Turn on the Cloud connector to connect to web AI.",
                    target_route="/cloud/connector",
                ),
                available_actions=["enable_connector"],
            )

        if cloud_connector_status == "connecting":
            return ExperienceSnapshot(
                mode=mode,
                readiness=ReadinessStatus.CONNECTOR_CONNECTING.value,
                reason_code="connector_connecting",
                engine_capabilities=engine_caps,
                project=project_info,
                computer=computer_info,
                ai_client=ai_client_info,
                next_action=NextAction(
                    id="wait_connector",
                    title="Connecting...",
                    description="Connecting outbound link to Cloud...",
                    target_route="/cloud/connector",
                ),
                available_actions=["stop_connector"],
            )

        if cloud_connector_status == "unreachable":
            return ExperienceSnapshot(
                mode=mode,
                readiness=ReadinessStatus.CONNECTOR_UNREACHABLE.value,
                reason_code="connector_unreachable",
                engine_capabilities=engine_caps,
                project=project_info,
                computer=computer_info,
                ai_client=ai_client_info,
                next_action=NextAction(
                    id="repair_connector",
                    title="Retry connection",
                    description="Cloud connector link unreachable. Check network or credentials.",
                    target_route="/cloud/connector",
                ),
                available_actions=["retry_connector", "stop_connector"],
            )

        # Cloud Ready
        return ExperienceSnapshot(
            mode=mode,
            readiness=ReadinessStatus.READY.value,
            reason_code="cloud_ready",
            engine_capabilities=engine_caps,
            project=project_info,
            computer=computer_info,
            ai_client=ai_client_info,
            cloud_connector={"enabled": True, "connected": True},
            next_action=None,
            available_actions=["open_project", "configure_ai", "stop_connector"],
        )

    # 3. Local mode checks (account-free)
    if not valid_project:
        return ExperienceSnapshot(
            mode=mode,
            readiness=ReadinessStatus.PROJECT_SELECTION_REQUIRED.value,
            reason_code="project_selection_required",
            engine_capabilities=engine_caps,
            project=project_info,
            computer=computer_info,
            next_action=NextAction(
                id="select_project",
                title="Select project",
                description="Choose a KiCad project directory to begin working locally.",
                target_route="/projects",
            ),
            available_actions=["select_project", "use_cloud_mode"],
        )

    if not cli_available and not ipc_available:
        return ExperienceSnapshot(
            mode=mode,
            readiness=ReadinessStatus.ENGINE_CAPABILITY_UNAVAILABLE.value,
            reason_code="kicad_missing",
            engine_capabilities=engine_caps,
            project=project_info,
            computer=computer_info,
            next_action=NextAction(
                id="install_kicad",
                title="Install KiCad",
                description="KiCad CLI or application was not detected on this computer.",
                target_route="/settings/diagnostics",
            ),
            available_actions=["diagnostics", "select_project"],
        )

    # Local Ready (even without Cloud account or IPC)
    available_actions.extend(["open_project", "run_drc"])
    return ExperienceSnapshot(
        mode=mode,
        readiness=ReadinessStatus.READY.value,
        reason_code="local_ready",
        engine_capabilities=engine_caps,
        project=project_info,
        computer=computer_info,
        ai_client=ai_client_info,
        next_action=None,
        available_actions=available_actions,
    )


def sanitize_experience_for_cloud(snapshot: ExperienceSnapshot) -> dict[str, Any]:
    """Sanitize experience snapshot for safe remote transmission to Cloud.

    Never exposes full local filesystem paths, private keys, tokens, or credential material.
    """
    raw = snapshot.to_dict()

    # Redact project path: keep only sanitized project existence
    if raw.get("project"):
        raw["project"] = {
            "name": "Project",
            "valid": bool(raw["project"].get("valid", False)),
        }

    # Ensure no secrets or local filesystem paths leaked in any nested fields
    def _strip_secrets(d: Any) -> Any:
        if isinstance(d, dict):
            clean = {}
            for k, v in d.items():
                if any(sec in k.lower() for sec in ("key", "secret", "token", "password", "path")):
                    if k in ("valid", "cli_available", "ipc_available", "file_available", "drc_available"):
                        clean[k] = v
                    continue
                clean[k] = _strip_secrets(v)
            return clean
        if isinstance(d, list):
            return [_strip_secrets(item) for item in d]
        return d

    return _strip_secrets(raw)
