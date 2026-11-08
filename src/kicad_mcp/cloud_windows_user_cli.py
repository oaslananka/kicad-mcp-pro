"""Interactive Windows Cloud CLI onboarding over owner-only local primitives.

The CLI chooses a KiCad folder, requires local owner confirmation and browser
device approval, and only then creates user-vault bindings and schedules the
readonly Connector. This never writes a KiCad project or issues a Cloud grant.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import typer

from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_connector import (
    local_state,
    remember_selected_project,
    selected_project,
)
from kicad_mcp.cloud_windows_enrollment import (
    WindowsEnrolledDevice,
    WindowsEnrollmentDeniedError,
    WindowsEnrollmentTimeoutError,
    WindowsRegisteredProject,
    enroll_windows_device,
    register_windows_project,
)
from kicad_mcp.cloud_windows_local_selection import (
    bind_owner_selected_project,
    inspect_owner_selected_project,
)
from kicad_mcp.cloud_windows_project_path import (
    _pinned_project,
    read_windows_project_presence,
)
from kicad_mcp.cloud_windows_task_scheduler import (
    disable_windows_connector,
    enable_windows_connector,
    scheduler_state,
)


def _choose_project(
    project_dir: Path | None, *, browse: bool, picker: Callable[[], Path]
) -> tuple[Path, str]:
    """Choose a single actual KiCad file from a pinned local folder; no GUI by default."""
    if browse:
        folder = picker()
    elif project_dir is not None:
        folder = project_dir
    else:
        cwd = Path.cwd()
        try:
            with _pinned_project(cwd):
                has_files = any(
                    entry.is_file() and entry.suffix in {".kicad_pro", ".kicad_pcb", ".kicad_sch"}
                    for entry in cwd.iterdir()
                )
        except (OSError, ValueError):
            has_files = False
        folder = cwd if has_files else Path(typer.prompt("KiCad project folder (absolute path)"))
    if not isinstance(folder, Path):
        raise typer.BadParameter("Invalid local KiCad project directory.")
    if not folder.is_absolute():
        folder = Path.cwd() / folder

    try:
        with _pinned_project(folder):
            candidates: list[tuple[int, str]] = []
            with os.scandir(folder) as entries:
                for i, entry in enumerate(entries):
                    if i >= 128:
                        raise LocalApprovalDeniedError("Project folder has too many entries.")
                    suffix = Path(entry.name).suffix
                    if suffix in {".kicad_pro", ".kicad_sch", ".kicad_pcb"}:
                        priority = {".kicad_pro": 0, ".kicad_sch": 1, ".kicad_pcb": 2}[suffix]
                        candidates.append((priority, Path(entry.name).stem))
            if not candidates:
                raise LocalApprovalDeniedError("No KiCad project found in selected folder.")
            candidates.sort()
            stem = candidates[0][1]
            present = read_windows_project_presence(folder, stem)
            if not any(present.values()):
                raise LocalApprovalDeniedError("No valid KiCad project files found.")
            return folder, stem
    except (OSError, ValueError, RuntimeError) as exc:
        raise typer.BadParameter(
            "Selected Windows project folder is unavailable or contains an unsafe link."
        ) from exc


def setup_windows(
    *,
    origin: str,
    alias: str,
    project_dir: Path | None,
    browse: bool,
    new_device: bool,
    approval: Callable[[str, str, str], None],
    picker: Callable[[], Path],
    owner_terminal: Callable[[], bool],
) -> None:
    if not owner_terminal():
        raise typer.BadParameter(
            "Cloud pairing requires an interactive owner terminal; "
            "use cloud status for noninteractive checks."
        )
    directory, stem = _choose_project(project_dir, browse=browse, picker=picker)
    try:
        existing = selected_project()
    except (OSError, ValueError, RuntimeError) as exc:
        raise typer.BadParameter(
            "Existing Windows Cloud registration needs local repair; no new device was created."
        ) from exc
    if existing is not None:
        if new_device:
            raise typer.BadParameter(
                "An owner-private device is already registered. Review/revoke it in "
                "Cloud Devices before selecting a distinct new device."
            )
        selected = inspect_owner_selected_project(existing)
        if (
            existing.origin != origin
            or selected.directory != directory
            or selected.filename_stem != stem
        ):
            raise typer.BadParameter(
                "A different Cloud origin or KiCad project is already selected. "
                "The existing registration has not been replaced."
            )
        typer.echo(f"Existing Windows Cloud device: {existing.device_id}")
        typer.echo(f"Local Connector: {scheduler_state()}")
        if local_state() != "Off":
            typer.echo("No new device registration or project grant was created.")
            return
        if not typer.confirm("Start the existing read-only Connector?", default=False):
            typer.echo("Connector remains Off. No device changed.")
            return
        try:
            enable_windows_connector(existing, owner_confirm=lambda _project: True)
        except (OSError, ValueError, RuntimeError) as exc:
            raise typer.BadParameter(
                "Background Connector could not start. The device registration was preserved."
            ) from exc
        typer.echo(f"Connector scheduled; connection not yet verified. Check {origin}/devices.")
        return

    typer.echo(f"KiCad project: {directory} ({stem})")
    typer.echo("Cloud will register a device/project identity; local project files stay local.")
    if not typer.confirm(
        "Approve pairing and the selected read-only local Connector?", default=False
    ):
        raise typer.BadParameter("Owner cancelled Cloud setup. No device was registered.")

    try:
        device: WindowsEnrolledDevice = enroll_windows_device(
            origin=origin, alias=alias, owner_approval=approval
        )
        project: WindowsRegisteredProject = register_windows_project(
            device, alias=stem, filename_stem=stem
        )
        bind_owner_selected_project(project, directory, owner_confirm=lambda _path: True)
        remember_selected_project(project)
    except (WindowsEnrollmentTimeoutError, WindowsEnrollmentDeniedError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    except (OSError, ValueError, RuntimeError) as exc:
        raise typer.BadParameter(
            "Windows Cloud registration was not fully completed. "
            "Review your Cloud Devices page before retrying; no Connector was started."
        ) from exc

    try:
        enable_windows_connector(project, owner_confirm=lambda _project: True)
    except (OSError, ValueError, RuntimeError) as exc:
        raise typer.BadParameter(
            "Cloud device/project registered locally, but Windows Connector did not start. "
            "Use cloud status and cloud enable to retry; Cloud permissions were not granted."
        ) from exc
    typer.echo("Device and project registered; Connector scheduled (connection unverified).")
    typer.echo(f"Cloud owner must separately approve access: {origin}/devices")
    typer.echo("Local read operations are limited to project_summary.")


def show_status() -> None:
    state = scheduler_state()
    typer.echo(f"Local Windows Connector: {state}")
    try:
        project = selected_project()
        if project is None:
            typer.echo("No owner-selected local Windows Cloud project.")
            return
        selected = inspect_owner_selected_project(project)
        typer.echo(f"Cloud: {project.origin}")
        typer.echo(f"Device: {project.device_id}")
        typer.echo(f"Project: {selected.filename_stem} ({project.project_id})")
        typer.echo(f"Directory: {selected.directory}")
        typer.echo("Cloud owner grants/revocation are managed in the Devices page.")
    except (OSError, ValueError):
        typer.echo("Existing local registration needs repair. Cloud access not verified.")
        raise typer.Exit(code=1) from None


def enable_existing(*, owner_terminal: Callable[[], bool]) -> None:
    if not owner_terminal():
        raise typer.BadParameter("Enabling a Connector requires an interactive owner terminal.")
    try:
        project = selected_project()
        if project is None:
            raise typer.BadParameter("No registered Windows project; run cloud setup.")
        if local_state() != "Off":
            typer.echo(f"Connector: {scheduler_state()}")
            return
        if not typer.confirm(
            "Enable the owner-selected read-only Windows Connector?", default=False
        ):
            typer.echo("Local Connector remains Off.")
            return
        enable_windows_connector(project, owner_confirm=lambda _project: True)
        typer.echo("Connector scheduled. Cloud connection/grants not verified.")
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, typer.BadParameter):
            raise
        raise typer.BadParameter("Windows Connector could not be enabled.") from exc


def disable_local() -> None:
    """Never confuse local disconnection with Cloud owner/device revocation."""
    try:
        stopped = disable_windows_connector()
    except (OSError, ValueError, RuntimeError) as exc:
        raise typer.BadParameter(
            "Local Connector disable could not be fully verified; check cloud status."
        ) from exc
    if stopped:
        typer.echo("Local Windows Connector is Off.")
    else:
        typer.echo(
            "Local read authority was revoked; background task stop was not verified.",
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo("Cloud device/project grants must be revoked separately in Cloud Devices.")
