"""Human-first Cloud owner commands over the browser-approved management API."""

from __future__ import annotations

import json
from typing import Any

import typer

from kicad_mcp.cloud_owner_management import (
    CloudManagementError,
    CloudOwnerApi,
    authorize,
    forget_token,
    load_token,
)


def _display(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    for key, rows in value.items():
        if isinstance(rows, list):
            if not rows:
                typer.echo("No " + key.replace("_", " ") + " found.")
                continue
            typer.echo(key.replace("_", " ").title() + ":")
            for row in rows:
                if isinstance(row, dict):
                    text = "  " + " | ".join(
                        str(k) + ": " + str(v)
                        for k, v in row.items()
                        if not isinstance(v, (list, dict))
                    )
                    typer.echo(text)
                    for nested_key, nested_rows in row.items():
                        if isinstance(nested_rows, list):
                            for item in nested_rows:
                                typer.echo(
                                    "    "
                                    + nested_key
                                    + ": "
                                    + json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                                )
                else:
                    typer.echo("  " + str(row))
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


def register_owner_commands(app: typer.Typer, default_origin: str) -> None:
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
        """Revoke only this CLI's management token; preserve all Cloud projects."""
        try:
            api = CloudOwnerApi(cloud_origin)
            token = load_token(api.origin)
            if not token:
                typer.echo("Cloud CLI is already disconnected.")
                return
            response = api.request("POST", "/api/owner/v1/logout", token=token)
            if response.get("revoked") is not True:
                raise CloudManagementError("Cloud did not confirm revocation.")
            forget_token(api.origin)
            typer.echo("Cloud CLI access revoked. Projects and devices are unchanged.")
        except CloudManagementError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

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
