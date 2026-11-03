"""Human-first Cloud setup shortcuts on top of existing signed device enrollment.

Account sign-in takes place in the user's normal browser; there is deliberately
no fabricated CLI bearer token or automatic project grant.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

DEFAULT_CLOUD_ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"
cloud_app = typer.Typer(help="Sign in, pair a device and manage the optional Cloud Connector.")


def _verified_origin(value: str) -> str:
    from kicad_mcp.cloud_pair import CloudPairingError, _origin

    try:
        return _origin(value)[2]
    except CloudPairingError as exc:
        raise typer.BadParameter("Cloud origin must be an HTTPS site origin.") from exc


def _owner_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _discover_kicad_project(folder: Path) -> tuple[Path, str]:
    from kicad_mcp.cloud_local_registry import _STEM

    if not folder.exists() or not folder.is_dir():
        raise typer.BadParameter(f"Project path is not a directory: {folder}")
    resolved = folder.resolve()
    pros = sorted(resolved.glob("*.kicad_pro"))
    if pros:
        return resolved, pros[0].stem
    schs = sorted(resolved.glob("*.kicad_sch"))
    if schs:
        return resolved, schs[0].stem
    pcbs = sorted(resolved.glob("*.kicad_pcb"))
    if pcbs:
        return resolved, pcbs[0].stem
    sub_pros = sorted(resolved.glob("*/*.kicad_pro"))
    if sub_pros:
        return sub_pros[0].parent.resolve(), sub_pros[0].stem
    stem = resolved.name
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", stem).strip("._-")
    if sanitized and _STEM.fullmatch(sanitized[:80]):
        return resolved, sanitized[:80]
    return resolved, "project"


def _write_project_record(root: Path, record: dict[str, str]) -> None:
    projects_dir = root / "projects"
    archive_dir = root / "archived-project-registrations"

    projects_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    archive_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(projects_dir, 0o700)
    os.chmod(archive_dir, 0o700)

    for existing in projects_dir.iterdir():
        if existing.is_file() and existing.suffix == ".json":
            target_arc = archive_dir / existing.name
            if target_arc.exists():
                target_arc = archive_dir / f"{existing.stem}.{uuid.uuid4().hex[:8]}.json"
            existing.rename(target_arc)

    project_id = record["projectId"]
    temp_name = f".{project_id}.{uuid.uuid4().hex}.tmp"
    temp_path = projects_dir / temp_name
    final_path = projects_dir / f"{project_id}.json"

    payload = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
    fd = os.open(
        temp_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, final_path)


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
    typer.echo("To pair this computer, run: kicad-mcp-pro cloud setup (or cloud connect)")


@cloud_app.command()
def connect(
    alias: str = typer.Option("My computer", "--alias", help="Display name for this new device."),
    cloud_origin: str = typer.Option(
        DEFAULT_CLOUD_ORIGIN, "--cloud-origin", help="Trusted HTTPS Cloud origin."
    ),
    new_device: bool = typer.Option(
        False,
        "--new-device",
        help="Pair a distinct new device after browser approval, preserving existing local keys.",
    ),
) -> None:
    """Start browser-approved device pairing without granting project access."""
    if not alias or len(alias) > 80 or any(ord(char) < 32 for char in alias):
        raise typer.BadParameter("Device name must be 1 to 80 printable characters.")
    origin = _verified_origin(cloud_origin)
    from kicad_mcp.cloud_local_registry import default_registry_root
    from kicad_mcp.cloud_registered_pilot import _single_registered_identity

    folder = default_registry_root() / "projects"
    try:
        has_registration = folder.exists() and any(folder.iterdir())
    except OSError as exc:
        raise typer.BadParameter("Unable to inspect existing Cloud registration.") from exc
    if has_registration:
        try:
            existing = _single_registered_identity(default_registry_root())
        except (OSError, ValueError) as exc:
            raise typer.BadParameter("Existing Cloud registration needs local repair.") from exc
        if existing["cloudOrigin"] != origin:
            raise typer.BadParameter("A different Cloud origin is already registered.")
        if not new_device:
            typer.echo("A private local registration exists for this Cloud origin.")
            typer.echo("Cloud enrollment has NOT been verified for this registration.")
            typer.echo(f"Check your enrolled devices at {origin}/devices.")
            typer.echo(
                "If the device is missing, run cloud connect --new-device "
                "from an interactive owner terminal."
            )
            typer.echo("The existing local registration and keys were not changed.")
            return
        typer.echo(
            "Starting a distinct browser-approved device pairing. "
            "Existing registration and keys will be preserved."
        )

    from kicad_mcp.cloud_pair import main as pair

    result = pair(["--cloud-origin", origin, "--alias", alias, "--begin-pairing"])
    if result:
        raise typer.Exit(result)
    typer.echo("Device pairing completed; the new device remains disabled by default.")
    typer.echo(
        "In Cloud Devices, explicitly enable the device and create a read-only project. "
        "The owner-private local project registry must also reference that new "
        "device, project and signing key before enabling the Connector."
    )
    typer.echo("Pairing alone does not enable the persistent Connector or project access.")


@cloud_app.command()
def setup(
    project_dir: Annotated[
        Path | None,
        typer.Option(
            "--project-dir",
            "-p",
            help="Path to KiCad project directory (defaults to current directory).",
        ),
    ] = None,
    alias: Annotated[
        str | None,
        typer.Option(
            "--alias",
            help="Display name for this device in Cloud (defaults to hostname or 'My computer').",
        ),
    ] = None,
    cloud_origin: Annotated[
        str,
        typer.Option(
            "--cloud-origin",
            help="Trusted HTTPS Cloud origin.",
        ),
    ] = DEFAULT_CLOUD_ORIGIN,
    no_browser: Annotated[
        bool,
        typer.Option(
            "--no-browser",
            help="Display pairing URL without launching a browser.",
        ),
    ] = False,
    new_device: Annotated[
        bool,
        typer.Option(
            "--new-device",
            help="Pair a distinct new device even if a valid local pairing exists.",
        ),
    ] = False,
) -> None:
    """One-command onboarding: pair device, register KiCad project, and enable Connector."""
    origin = _verified_origin(cloud_origin)
    target_dir, stem = _discover_kicad_project(project_dir or Path.cwd())

    device_alias = alias
    if not device_alias:
        try:
            host = socket.gethostname() or ""
        except OSError:
            host = ""
        clean_host = re.sub(r"[^A-Za-z0-9 ._-]", "", host).strip(" ._-")
        device_alias = f"{clean_host} KiCad"[:64] if clean_host else "My computer"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}", device_alias):
            device_alias = "My computer"
    elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}", device_alias):
        raise typer.BadParameter("Device alias must be 1 to 64 alphanumeric characters.")

    from kicad_mcp.cloud_local_registry import default_registry_root
    from kicad_mcp.cloud_registered_pilot import _single_registered_identity

    root = default_registry_root()
    projects_dir = root / "projects"
    keys_dir = root / "keys"

    if projects_dir.exists() and any(projects_dir.iterdir()) and not new_device:
        try:
            existing = _single_registered_identity(root)
        except Exception:
            existing = None

        if existing and existing.get("cloudOrigin") == origin:
            key_file = keys_dir / f"{existing['keySlot']}.pem"
            if key_file.is_file():
                typer.echo("Found valid existing Cloud device and project registration:")
                typer.echo(f"  Device ID:  {existing['deviceId']}")
                typer.echo(f"  Project ID: {existing['projectId']}")
                typer.echo(f"  Directory:  {existing['directory']} ({existing['filenameStem']})")

                from kicad_mcp.cloud_managed_connector import _enable, _status

                current_status = _status()
                if current_status == "Off":
                    typer.echo("Starting Cloud Connector...")
                    try:
                        _enable()
                        for _ in range(5):
                            time.sleep(1)
                            current_status = _status()
                            if current_status in ("Connected", "Connecting"):
                                break
                    except Exception as exc:
                        typer.echo(f"Notice: Connector could not be started automatically: {exc}")
                typer.echo(f"Connector Status: {current_status}")
                typer.echo(f"Cloud web panel:  {origin}/devices")
                return

    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    keys_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    os.chmod(keys_dir, 0o700)

    slot = str(uuid.uuid4())
    keyfile = keys_dir / f"{slot}.pem"

    def _approval_cb(page: str, challenge: str, code: str) -> None:
        review_url = f"{page}#challenge={challenge}&code={code}"
        typer.echo("\n" + "=" * 60)
        typer.echo("KiCad MCP Pro Cloud — Device Authorization")
        typer.echo(f"Pairing verification code: {code}")
        typer.echo("=" * 60)
        if not no_browser:
            opened = False
            try:
                opened = webbrowser.open(review_url, new=2, autoraise=True)
            except (OSError, webbrowser.Error):
                opened = False
            if opened:
                typer.echo("Browser opened for approval. Please confirm the pairing code matches.")
            else:
                typer.echo(f"Open this approval link in your signed-in browser:\n  {review_url}")
        else:
            typer.echo(f"Open this approval link in your signed-in browser:\n  {review_url}")
        typer.echo("Waiting for approval in browser...")

    from kicad_mcp.cloud_pair import CloudPairingError, enroll, register_device_project
    from kicad_mcp.cloud_pair_keys import _read_owner_binding

    try:
        device_id, fingerprint = enroll(origin, device_alias, keyfile, _approval_cb)
    except CloudPairingError as exc:
        raise typer.BadParameter("Device pairing failed or was denied.") from exc

    bound = _read_owner_binding(keyfile)
    owner_sub = bound.get("ownerSub")
    if not owner_sub:
        raise typer.BadParameter("Owner identity missing from device binding.")

    typer.echo(f"\nDevice paired: {device_id} (Fingerprint: {fingerprint[:16]}...)")
    typer.echo(f"Registering KiCad project '{stem}' on Cloud...")

    try:
        project_res = register_device_project(origin, keyfile, alias=stem)
    except CloudPairingError as exc:
        raise typer.BadParameter("Project registration failed on Cloud.") from exc

    project_id = str(project_res["projectId"])
    typer.echo(f"Project registered on Cloud: {project_id}")

    new_record = {
        "ownerSub": owner_sub,
        "cloudOrigin": origin,
        "deviceId": device_id,
        "projectId": project_id,
        "keySlot": slot,
        "directory": str(target_dir),
        "filenameStem": stem,
    }
    _write_project_record(root, new_record)

    connector_state = "Off"
    try:
        from kicad_mcp.cloud_managed_connector import _enable, _status

        _enable()
        for _ in range(5):
            time.sleep(1)
            connector_state = _status()
            if connector_state in ("Connected", "Connecting"):
                break
    except Exception as exc:
        typer.echo(f"Background service start notice: {exc}")
        try:
            from kicad_mcp.cloud_managed_connector import (
                _ENABLED_FILE,
                _identity_state,
                _write_private_json,
            )

            _write_private_json(root, _ENABLED_FILE, _identity_state(new_record))
            connector_state = "Enabled (Foreground ready)"
        except Exception as write_err:
            typer.echo(f"Notice: Could not write enabled state: {write_err}")

    typer.echo("\n" + "=" * 60)
    typer.echo("KiCad MCP Pro Cloud Setup Complete!")
    typer.echo("=" * 60)
    typer.echo(f"Cloud Origin:    {origin}")
    typer.echo(f"Device:          {device_alias} ({device_id}) [Enabled]")
    typer.echo(f"Project:         {stem} ({project_id})")
    typer.echo(f"Local Directory: {target_dir}")
    typer.echo(f"Connector:       {connector_state}")
    typer.echo(f"Web Dashboard:   {origin}/devices")
    typer.echo("AI Client Access: Ready (Configure in Cloud Dashboard)")
    typer.echo("=" * 60 + "\n")


@cloud_app.command("register-project")
def register_project(
    owner_sub: str = typer.Option(
        ..., "--owner-sub", help="Account ID from signed-in Cloud Devices."
    ),
    device_id: str = typer.Option(
        ..., "--device-id", help="Device ID from signed-in Cloud Devices."
    ),
    project_id: str = typer.Option(
        ..., "--project-id", help="Project ID from signed-in Cloud Devices."
    ),
) -> None:
    """Explicitly associate a paired Cloud project with your existing local folder."""
    if not _owner_terminal():
        raise typer.BadParameter("Run this from your own interactive terminal.")
    from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
    from kicad_mcp.cloud_registration_handoff import (
        activate_handoff,
        default_registry_root,
        prepare_handoff,
    )

    try:
        plan = prepare_handoff(
            default_registry_root(),
            owner_sub=owner_sub,
            device_id=device_id,
            project_id=project_id,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter("Local project binding could not be verified.") from exc
    old = plan.old()
    typer.echo("The existing local project folder will be reused:")
    typer.echo(f"  {old['directory']} ({old['filenameStem']})")
    typer.echo("The prior device registration will be archived privately, not deleted.")
    typer.echo("The Cloud device, project and client access switches remain separate.")
    if not typer.confirm("Link this local project to the newly approved device?", default=False):
        typer.echo("No changes made.")
        raise typer.Exit(1)
    try:
        activate_handoff(plan)
    except (OSError, LocalApprovalDeniedError) as exc:
        raise typer.BadParameter(
            "Local registration update failed; inspect private registry."
        ) from exc
    typer.echo("Local project registration updated. Connector remains Off.")
    typer.echo("Check cloud status, then use cloud enable only when ready.")


@cloud_app.command()
def projects() -> None:
    """List registered KiCad Cloud projects and bound device."""
    from kicad_mcp.cloud_local_registry import default_registry_root
    from kicad_mcp.cloud_registered_pilot import _single_registered_identity

    root = default_registry_root()
    projects_dir = root / "projects"
    if not projects_dir.exists() or not any(projects_dir.iterdir()):
        typer.echo("No local KiCad projects currently registered.")
        typer.echo("To connect a project, run: kicad-mcp-pro cloud setup")
        return

    try:
        current = _single_registered_identity(root)
        typer.echo("Active Registered Project:")
        typer.echo(f"  Project Name: {current.get('filenameStem')}")
        typer.echo(f"  Project ID:   {current.get('projectId')}")
        typer.echo(f"  Directory:    {current.get('directory')}")
        typer.echo(f"  Device ID:    {current.get('deviceId')}")
        typer.echo(f"  Cloud Origin: {current.get('cloudOrigin')}")
    except Exception as exc:
        typer.echo(f"Active registration error: {exc}")

    archive_dir = root / "archived-project-registrations"
    if archive_dir.exists():
        archived_files = sorted(f for f in archive_dir.iterdir() if f.suffix == ".json")
        if archived_files:
            typer.echo(f"\nArchived Projects ({len(archived_files)}):")
            for arc in archived_files:
                try:
                    data = json.loads(arc.read_text(encoding="utf-8"))
                    stem = data.get("filenameStem")
                    pid = data.get("projectId")
                    directory = data.get("directory")
                    typer.echo(f"  - {stem} ({pid}) -> {directory}")
                except Exception as arc_err:
                    _ = arc_err
                    typer.echo(f"  - {arc.name}")


@cloud_app.command()
def status() -> None:
    """Show local Connector and Cloud registration status."""
    from kicad_mcp.cloud_local_registry import default_registry_root
    from kicad_mcp.cloud_managed_connector import main as connector
    from kicad_mcp.cloud_registered_pilot import _single_registered_identity

    result = connector(["status"])
    if result:
        raise typer.Exit(result)

    root = default_registry_root()
    try:
        reg = _single_registered_identity(root)
        typer.echo(f"Cloud Origin:    {reg.get('cloudOrigin')}")
        typer.echo(f"Device ID:       {reg.get('deviceId')}")
        typer.echo(f"Project ID:      {reg.get('projectId')}")
        typer.echo(f"Local Directory: {reg.get('directory')} ({reg.get('filenameStem')})")
    except Exception as exc:
        _ = exc


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


@cloud_app.command()
def disconnect() -> None:
    """Disable local Connector authority and stop its user service."""
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["disable"])
    if result:
        raise typer.Exit(result)


@cloud_app.command()
def reconnect() -> None:
    """Explicitly enable the Connector for one already-registered local project."""
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["enable"])
    if result:
        raise typer.Exit(result)


@cloud_app.command("run", hidden=True)
def run() -> None:
    """Run the Cloud Connector in the foreground."""
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["run"])
    if result:
        raise typer.Exit(result)
