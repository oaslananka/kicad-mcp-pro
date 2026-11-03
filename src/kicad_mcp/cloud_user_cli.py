"""Human-first Cloud setup shortcuts on top of existing signed device enrollment.

Account sign-in takes place in the user's normal browser; there is deliberately
no fabricated CLI bearer token or automatic project grant.
"""

from __future__ import annotations

import webbrowser

import typer

DEFAULT_CLOUD_ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"
cloud_app = typer.Typer(help="Sign in, pair a device and manage the optional Cloud Connector.")


def _verified_origin(value: str) -> str:
    from kicad_mcp.cloud_pair import CloudPairingError, _origin

    try:
        return _origin(value)[2]
    except CloudPairingError as exc:
        raise typer.BadParameter("Cloud origin must be an HTTPS site origin.") from exc


@cloud_app.command()
def login(
    cloud_origin: str = typer.Option(
        DEFAULT_CLOUD_ORIGIN, "--cloud-origin", help="Trusted HTTPS Cloud origin."
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Display the login URL without launching a browser."
    ),
) -> None:
    """Open first-party Cloud sign-in, supporting GitHub and Google when configured."""
    origin = _verified_origin(cloud_origin)
    url = origin + "/sign-in"
    typer.echo(f"Cloud sign-in: {url}")
    if not no_browser:
        try:
            opened = webbrowser.open(url, new=2, autoraise=True)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            typer.echo("Open the link above in your preferred browser.")
    typer.echo("Sign in or create your Cloud account with an available provider.")
    typer.echo("Browser login does not grant device or project access.")
    typer.echo("To pair this computer, run: kicad-mcp-pro cloud connect")


@cloud_app.command()
def connect(
    alias: str = typer.Option("My computer", "--alias", help="Display name for this new device."),
    cloud_origin: str = typer.Option(
        DEFAULT_CLOUD_ORIGIN, "--cloud-origin", help="Trusted HTTPS Cloud origin."
    ),
) -> None:
    """Pair a new computer via browser sign-in and explicit device approval."""
    if not alias or len(alias) > 80 or any(ord(char) < 32 for char in alias):
        raise typer.BadParameter("Device name must be 1 to 80 printable characters.")
    origin = _verified_origin(cloud_origin)
    # An owner with one valid local project registration should not enroll
    # another device/key just because they repeated the quickstart command.
    from kicad_mcp.cloud_local_registry import default_registry_root
    from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
    from kicad_mcp.cloud_registered_pilot import _single_registered_identity

    folder = default_registry_root() / "projects"
    try:
        has_registration = folder.exists() and any(folder.iterdir())
    except OSError as exc:
        raise typer.BadParameter("Unable to inspect existing Cloud registration.") from exc
    if has_registration:
        try:
            existing = _single_registered_identity(default_registry_root())
        except (OSError, ValueError, LocalApprovalDeniedError) as exc:
            raise typer.BadParameter("Existing Cloud registration needs local repair.") from exc
        if existing["cloudOrigin"] != origin:
            raise typer.BadParameter("A different Cloud origin is already registered.")
        typer.echo("Already paired with this Cloud; no new device was enrolled.")
        typer.echo("Use cloud status, then cloud enable when you want local reads.")
        return

    from kicad_mcp.cloud_pair import main as pair

    result = pair(["--cloud-origin", origin, "--alias", alias, "--begin-pairing"])
    if result:
        raise typer.Exit(result)
    typer.echo("Pairing completed. Enable the device and choose project access in Cloud.")
    typer.echo("Pairing alone does not enable the persistent Connector.")


@cloud_app.command()
def status() -> None:
    """Show local Connector status without accessing account secrets."""
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["status"])
    if result:
        raise typer.Exit(result)


@cloud_app.command()
def enable() -> None:
    """Explicitly enable the Connector for one already-registered local project."""
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["enable"])
    if result:
        raise typer.Exit(result)


@cloud_app.command()
def disable() -> None:
    """Disable local Connector authority and stop its user service."""
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["disable"])
    if result:
        raise typer.Exit(result)
