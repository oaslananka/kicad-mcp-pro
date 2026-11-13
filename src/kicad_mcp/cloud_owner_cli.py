"""Human-first Cloud owner commands over the browser-approved management API."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import typer

from kicad_mcp.cloud_owner_management import (
    CloudManagementError,
    CloudOwnerApi,
    authorize,
    forget_token,
    load_token,
)


def _show_cloud_list_row(row: object) -> None:
    """One readable owner record; nested entries remain inspectable."""
    if not isinstance(row, dict):
        typer.echo("  " + str(row))
        return
    text = "  " + " | ".join(
        str(key) + ": " + str(item)
        for key, item in row.items()
        if not isinstance(item, (list, dict))
    )
    typer.echo(text)
    for key, nested in row.items():
        if isinstance(nested, list):
            for item in nested:
                typer.echo(
                    "    "
                    + key
                    + ": "
                    + json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                )


def _show_cloud_list(key: str, rows: list[object]) -> None:
    if not rows:
        typer.echo("No " + key.replace("_", " ") + " found.")
        return
    typer.echo(key.replace("_", " ").title() + ":")
    for row in rows:
        _show_cloud_list_row(row)


def _display(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    for key, rows in value.items():
        if isinstance(rows, list):
            _show_cloud_list(key, rows)
        elif isinstance(rows, dict):
            typer.echo(key.replace("_", " ").title() + ":")
            for name, amount in rows.items():
                typer.echo("  " + name + ": " + str(amount))
        else:
            typer.echo(key + ": " + str(rows))


def _request(
    origin: str, method: str, path: str, *, body: dict[str, object] | None = None
) -> dict[str, Any]:
    try:
        return CloudOwnerApi(origin).authorized(method, path, payload=body)
    except CloudManagementError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _select_paired_local_project(
    origin: str, directory: Path, filename: str | None
) -> tuple[str, object, str, Path]:
    """Resolve only one local file and its existing signed device identity."""
    from kicad_mcp.cloud_folder_browse_receiver import default_bindings_file
    from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser
    from kicad_mcp.cloud_windows_connector import selected_project

    try:
        device = selected_project()
        if device is None:
            raise CloudManagementError("Pair this computer first with cloud remote.")
        if device.origin != origin:
            raise CloudManagementError("This device belongs to a different Cloud site.")
        if directory.is_symlink() or directory.is_junction():
            raise CloudManagementError("Select a real local KiCad folder, not a link.")
        directory = directory.expanduser().resolve(strict=True)
        if not directory.is_dir():
            raise CloudManagementError("Select a local KiCad project folder, not a file.")
        browser = LocalFolderBrowser([directory.parent], default_bindings_file())
        selection = browser.choose_native(lambda: directory)
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, CloudManagementError):
            raise
        raise CloudManagementError("Local KiCad folder or device pairing is unavailable.") from exc

    options = selection.get("projects")
    if selection.get("status") != "selected" or not isinstance(options, list):
        raise CloudManagementError("The chosen folder has no selectable KiCad project.")
    matches = [
        entry
        for entry in options
        if isinstance(entry, dict)
        and (
            filename is None
            or filename in {entry.get("name"), str(entry.get("name")) + ".kicad_pro"}
        )
    ]
    if len(matches) != 1:
        available = ", ".join(str(x.get("name")) for x in options if isinstance(x, dict))
        raise CloudManagementError(
            "Select one KiCad project with --file (available: " + available[:250] + ")."
        )
    return device.device_id, browser, str(matches[0]["id"]), directory


def _commit_local_project_binding(
    api: CloudOwnerApi, browser: object, folder_token: str, project_id: str
) -> None:
    """Never leave a misleading new Cloud record when local mapping fails."""
    from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser

    if not isinstance(browser, LocalFolderBrowser):
        raise CloudManagementError("Local project browser is unavailable.")
    try:
        if browser.bind(folder_token, project_id) is not True:
            raise ValueError("local project map was not saved")
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        try:
            api.authorized(
                "POST", "/api/owner/v1/projects/remove", payload={"projectId": project_id}
            )
        except CloudManagementError as rollback_exc:
            raise CloudManagementError(
                "The local binding failed and the Cloud rollback could not be confirmed. "
                "Review this Cloud project ID: " + project_id
            ) from rollback_exc
        raise CloudManagementError(
            "The local project binding failed; its new Cloud record was removed."
        ) from exc


def _add_project_on_paired_device(
    origin: str, directory: Path, *, filename: str | None, name: str | None
) -> tuple[str, str]:
    """Register one owner-chosen local KiCad file without uploading its contents."""
    device_id, browser, folder_token, resolved = _select_paired_local_project(
        origin, directory, filename
    )
    label = name if name is not None else resolved.name
    if not label or len(label) > 64 or not label.strip():
        raise CloudManagementError("Cloud project name must contain 1 to 64 characters.")
    api = CloudOwnerApi(origin)
    reply = api.authorized(
        "POST",
        "/api/owner/v1/projects",
        payload={"deviceId": device_id, "alias": label},
    )
    project_id = reply.get("id")
    try:
        if not isinstance(project_id, str):
            raise ValueError("invalid Cloud project id")
        UUID(project_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise CloudManagementError("Cloud did not confirm a valid project identity.") from exc
    _commit_local_project_binding(api, browser, folder_token, project_id)
    return project_id, label


def show_cloud_projects(origin: str, json_output: bool = False) -> None:
    """List only projects actually returned by the owner Cloud account."""
    reply = _request(origin, "GET", "/api/owner/v1/devices")
    rows = []
    for device in reply.get("devices", []):
        if not isinstance(device, dict):
            continue
        for project in device.get("projects", []):
            if isinstance(project, dict):
                rows.append(
                    {
                        **project,
                        "deviceId": device.get("id"),
                        "device": device.get("alias"),
                        "online": device.get("connected", False),
                    }
                )
    _display({"projects": rows}, json_output)


def _disconnect_local_cloud_device(origin: str) -> bool:
    """Disconnect the locally paired device for this Cloud without deleting it."""
    if os.name == "nt":
        return _stop_windows_cloud_device(origin)
    if os.name == "posix" and sys.platform.startswith("linux"):
        return _stop_linux_cloud_device(origin)
    return False


def _stop_windows_cloud_device(origin: str) -> bool:
    from kicad_mcp.cloud_windows_connector import selected_project
    from kicad_mcp.cloud_windows_task_scheduler import disable_windows_connector

    try:
        selected = selected_project()
        if selected is None or selected.origin != origin:
            return False
        stopped = disable_windows_connector()
    except (OSError, ValueError, RuntimeError) as exc:
        raise CloudManagementError(
            "Cloud CLI logged out, but the local device could not be stopped. "
            "Run cloud disable and verify Cloud Devices."
        ) from exc
    if stopped is not True:
        raise CloudManagementError(
            "Cloud CLI logged out, but local device shutdown was not confirmed. "
            "Run cloud disable and verify Cloud Devices."
        )
    return True


def _stop_linux_cloud_device(origin: str) -> bool:
    from kicad_mcp.cloud_local_registry import default_registry_root
    from kicad_mcp.cloud_managed_connector import _disable
    from kicad_mcp.cloud_registered_pilot import _single_registered_identity

    root = default_registry_root()
    if not (root / "projects").exists():
        return False
    try:
        current = _single_registered_identity(root)
        if current.get("cloudOrigin") != origin:
            return False
        stopped = _disable()
    except (OSError, ValueError, RuntimeError) as exc:
        raise CloudManagementError(
            "Cloud CLI logged out, but Linux Connector shutdown needs local review."
        ) from exc
    if stopped != 0:
        raise CloudManagementError(
            "Cloud CLI logged out, but Linux Connector shutdown was not confirmed."
        )
    return True


def _logout_current_cloud_owner(api: CloudOwnerApi) -> tuple[bool, bool]:
    """Local disconnect is not contingent on a healthy Cloud HTTP connection."""
    token = load_token(api.origin)
    local_failure: CloudManagementError | None = None
    stopped = False
    try:
        stopped = _disconnect_local_cloud_device(api.origin)
    except CloudManagementError as exc:
        local_failure = exc

    if token:
        # Never silently erase credentials without Cloud confirming revocation.
        response = api.request("POST", "/api/owner/v1/logout", token=token)
        if response.get("revoked") is not True:
            raise CloudManagementError("Cloud did not confirm revocation.")
        forget_token(api.origin)
    if local_failure is not None:
        raise local_failure
    return bool(token), stopped


def _register_owner_session_commands(app: typer.Typer, default_origin: str) -> None:
    @app.command("authorize")
    def authorize_owner(
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        no_browser: bool = typer.Option(False, "--no-browser"),
        label: str | None = typer.Option(
            None, "--label", help="Computer name shown in Cloud approval."
        ),
    ) -> None:
        """Approve this CLI in your browser once to manage your Cloud account."""
        try:
            authorize(cloud_origin, no_browser=no_browser, label=label)
        except CloudManagementError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

    @app.command("logout")
    def logout_owner(
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
    ) -> None:
        """Log out this CLI and stop its same-Cloud local device Connector."""
        try:
            api = CloudOwnerApi(cloud_origin)
            had_token, stopped = _logout_current_cloud_owner(api)
            if not had_token and not stopped:
                typer.echo("Cloud CLI is already disconnected.")
                return
            typer.echo("Cloud CLI logged out." if had_token else "No active CLI token.")
            typer.echo(
                "Local Connector stopped; device pairing and KiCad projects preserved."
                if stopped
                else "No same-Cloud local device was connected."
            )
        except CloudManagementError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

    @app.command("add-project")
    def add_project_owner(
        path: Annotated[Path, typer.Option("--path", help="Local KiCad project folder.")],
        project_file: str | None = typer.Option(
            None, "--file", help="Project file name if the folder contains several."
        ),
        name: str | None = typer.Option(None, "--name", help="Cloud display name."),
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
    ) -> None:
        """Add one local KiCad project to this already paired Cloud device."""
        if os.name != "nt":
            typer.echo("Cloud add-project currently requires a paired Windows device.", err=True)
            raise typer.Exit(1)
        try:
            origin = CloudOwnerApi(cloud_origin).origin
            project_id, label = _add_project_on_paired_device(
                origin, path, filename=project_file, name=name
            )
        except CloudManagementError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo("Cloud project registered and bound locally: " + label)
        typer.echo("Project ID: " + project_id)
        typer.echo("Start or keep cloud remote connected to make this project available.")


def _register_owner_access_commands(app: typer.Typer, default_origin: str) -> None:
    @app.command("devices")
    def devices_owner(
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON."),
    ) -> None:
        """List your Cloud devices, online status and projects."""
        _display(_request(cloud_origin, "GET", "/api/owner/v1/devices"), json_output)

    @app.command("clients")
    def clients_owner(
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """List AI clients with owner-granted OAuth consent."""
        _display(_request(cloud_origin, "GET", "/api/owner/v1/clients"), json_output)

    @app.command("access")
    def access_owner(
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """List saved project/client permissions (current Cloud mode: read-only)."""
        _display(_request(cloud_origin, "GET", "/api/owner/v1/access"), json_output)

    @app.command("set-access")
    def set_access(
        project_id: str = typer.Option(..., "--project-id"),
        client_id: str = typer.Option(..., "--client-id"),
        enabled: bool = typer.Option(..., "--enabled/--disabled"),
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Allow or disable read-only Cloud access to one project for one AI client."""
        result = _request(
            cloud_origin,
            "POST",
            "/api/owner/v1/access/set",
            body={"projectId": project_id, "clientId": client_id, "enabled": enabled},
        )
        _display(result, json_output)

    @app.command("revoke-client")
    def revoke_client(
        client_id: str = typer.Option(..., "--client-id"),
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Revoke an AI client's Cloud project grants, without deleting files."""
        result = _request(
            cloud_origin, "POST", "/api/owner/v1/access/revoke", body={"clientId": client_id}
        )
        _display(result, json_output)


def _register_owner_project_commands(app: typer.Typer, default_origin: str) -> None:
    @app.command("rename-project")
    def rename_project(
        project_id: str = typer.Option(..., "--project-id"),
        alias: str = typer.Option(..., "--name"),
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Rename the Cloud label; never rename local KiCad files."""
        result = _request(
            cloud_origin,
            "POST",
            "/api/owner/v1/projects/rename",
            body={"projectId": project_id, "alias": alias},
        )
        _display(result, json_output)

    @app.command("remove-project")
    def remove_project(
        project_id: str = typer.Option(..., "--project-id"),
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Remove the selected Cloud project record, never local KiCad files."""
        result = _request(
            cloud_origin, "POST", "/api/owner/v1/projects/remove", body={"projectId": project_id}
        )
        _display(result, json_output)
        if not json_output:
            typer.echo("Local KiCad files were not changed.")


def _register_owner_activity_commands(app: typer.Typer, default_origin: str) -> None:
    @app.command("usage")
    def usage_owner(
        days: int = typer.Option(30, "--days", min=1, max=365),
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Show measured Cloud MCP tool calls, not invented plan limits."""
        _display(
            _request(cloud_origin, "GET", "/api/owner/v1/usage?days=" + str(days)), json_output
        )

    @app.command("logs")
    def logs_owner(
        limit: int = typer.Option(50, "--limit", min=1, max=100),
        cloud_origin: str = typer.Option(default_origin, "--cloud-origin"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Show activity for this Cloud owner, without exposing local paths."""
        _display(
            _request(cloud_origin, "GET", "/api/owner/v1/logs?limit=" + str(limit)), json_output
        )


def register_owner_commands(app: typer.Typer, default_origin: str) -> None:
    """Register the account, access, project and activity commands once."""
    _register_owner_session_commands(app, default_origin)
    _register_owner_access_commands(app, default_origin)
    _register_owner_project_commands(app, default_origin)
    _register_owner_activity_commands(app, default_origin)
