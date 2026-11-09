"""Human-first Cloud setup shortcuts on top of existing signed device enrollment.

Account sign-in takes place in the user's normal browser; there is deliberately
no fabricated CLI bearer token or automatic project grant.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

DEFAULT_CLOUD_ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"
_DEFAULT_DEVICE_ALIAS = "My computer"
cloud_app = typer.Typer(help="Sign in, pair a device and manage the optional Cloud Connector.")


def _verified_origin(value: str) -> str:
    from kicad_mcp.cloud_pair import CloudPairingError, _origin

    try:
        return _origin(value)[2]
    except CloudPairingError as exc:
        raise typer.BadParameter("Cloud origin must be an HTTPS site origin.") from exc


def _owner_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _is_windows() -> bool:
    """Explicit routing seam; Windows enrollment is not a POSIX filesystem flow."""
    return os.name == "nt"


def _local_pairing_storage_supported() -> bool:
    """Fail early until a complete native owner-private enrollment is available."""
    # Windows vault inspection primitives are not an enrollment/connector
    # implementation. Never create a Cloud challenge using POSIX-only keys.
    if os.name == "nt":
        return False
    return (
        os.name == "posix"
        and callable(getattr(os, "getuid", None))
        and isinstance(getattr(os, "O_NOFOLLOW", None), int)
        and isinstance(getattr(os, "O_DIRECTORY", None), int)
        and os.open in os.supports_dir_fd
    )


def _require_local_pairing_storage() -> None:
    if not _local_pairing_storage_supported():
        if os.name == "nt":
            typer.echo("No device or project was registered.", err=True)
            typer.echo("Windows Cloud pairing is not yet supported. Local MCP works.", err=True)
            raise typer.BadParameter("owner-private key storage is unavailable on Windows.")
        raise typer.BadParameter(
            "Cloud device pairing is not available on this operating system yet: "
            "owner-private key storage requires supported native filesystem protection. "
            "No device or project was registered. Local KiCad and the local AI tools "
            "work without a Cloud account."
        )


def _has_kicad_project_files(folder: Path) -> bool:
    """Avoid onboarding an arbitrary terminal working directory as a KiCad project."""
    patterns = ("*.kicad_pro", "*.kicad_sch", "*.kicad_pcb", "*/*.kicad_pro")
    return folder.is_dir() and any(
        path.is_file() for pattern in patterns for path in folder.glob(pattern)
    )


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


def _browse_windows_project_folder() -> Path:
    """Use the built-in Windows folder dialog even without Python/Tk installed."""
    # This program is a fixed literal: never interpolate project paths or other
    # user input into an executable shell command.
    script = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
$picker = [System.Windows.Forms.FolderBrowserDialog]::new()
$picker.Description = 'Choose your local KiCad project folder'
$picker.ShowNewFolderButton = $false
# The browser-facing backend runs without foreground focus. An invisible
# topmost owner keeps the genuine Windows folder chooser above the app.
$owner = [System.Windows.Forms.Form]::new()
$owner.ShowInTaskbar = $false
$owner.TopMost = $true
$owner.Opacity = 0
$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
try {
    $owner.Show()
    $owner.Activate()
    if ($picker.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::WriteLine($picker.SelectedPath)
    }
} finally {
    $picker.Dispose()
    $owner.Close()
    $owner.Dispose()
}
"""
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    try:
        selected = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-STA",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise typer.BadParameter("Windows folder picker unavailable. Try again.") from exc
    if selected.returncode != 0:
        raise typer.BadParameter("Windows folder picker unavailable. Try again.")
    if not selected.stdout.strip():
        raise typer.BadParameter("No project folder selected. Setup was not changed.")
    return Path(selected.stdout.strip())


def _browse_local_project_folder() -> Path:
    """Open a native *local* directory picker. Never send the path to Cloud."""
    if sys.platform == "win32":
        return _browse_windows_project_folder()
    zenity = shutil.which("zenity") if sys.platform.startswith("linux") else None
    if zenity:
        try:
            selected = subprocess.run(
                [
                    zenity,
                    "--file-selection",
                    "--directory",
                    "--title=Choose your local KiCad project folder",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise typer.BadParameter(
                "Folder picker unavailable; use --project-dir /path/to/project."
            ) from exc
        if selected.returncode != 0 or not selected.stdout.strip():
            raise typer.BadParameter("No project folder selected. Setup was not changed.")
        return Path(selected.stdout.strip())
    try:
        import tkinter as tk
        from tkinter import filedialog

        dialog = tk.Tk()
        dialog.withdraw()
        try:
            selection = filedialog.askdirectory(
                parent=dialog,
                title="Choose your local KiCad project folder",
                mustexist=True,
            )
        finally:
            dialog.destroy()
    except (ImportError, RuntimeError, OSError) as exc:
        raise typer.BadParameter(
            "No graphical folder picker available; use --project-dir /path/to/project."
        ) from exc
    if not selection:
        raise typer.BadParameter("No project folder selected. Setup was not changed.")
    return Path(selection)


def _select_setup_project_directory(browse: bool, project_dir: Path | None) -> Path:
    """Select an actual local KiCad project before any network or registry writes."""
    if browse:
        selected = _browse_local_project_folder()
    elif project_dir is not None:
        selected = project_dir
    else:
        current = Path.cwd()
        if _has_kicad_project_files(current):
            selected = current
        elif _owner_terminal():
            selected = _browse_local_project_folder()
        else:
            raise typer.BadParameter(
                "No KiCad project found in the current directory. "
                "Choose a local project in the desktop UI, or supply a project directory. "
                "No Cloud registration was started."
            )
    if not _has_kicad_project_files(selected):
        raise typer.BadParameter(
            "No KiCad project found in the selected directory. "
            "Choose a folder containing a .kicad_pro, .kicad_sch or .kicad_pcb file. "
            "No device or project registration was started."
        )
    return selected


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
    alias: str = typer.Option(
        _DEFAULT_DEVICE_ALIAS, "--alias", help="Display name for this new device."
    ),
    cloud_origin: str = typer.Option(
        DEFAULT_CLOUD_ORIGIN, "--cloud-origin", help="Trusted HTTPS Cloud origin."
    ),
    new_device: bool = typer.Option(
        False,
        "--new-device",
        help="Pair a distinct new device after browser approval, preserving existing local keys.",
    ),
    project_dir: Annotated[
        Path | None,
        typer.Option("--project-dir", "-p", help="Select a local KiCad project on Windows."),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option(
            "--no-browser", help="Print Cloud owner pairing URL without opening a browser."
        ),
    ] = False,
) -> None:
    """Start browser-approved device pairing without granting project access."""
    if not alias or len(alias) > 80 or any(ord(char) < 32 for char in alias):
        raise typer.BadParameter("Device name must be 1 to 80 printable characters.")
    origin = _verified_origin(cloud_origin)
    if _is_windows():
        from kicad_mcp.cloud_windows_user_cli import setup_windows

        setup_windows(
            origin=origin,
            alias=_resolve_device_alias(alias),
            project_dir=project_dir,
            browse=False,
            new_device=new_device,
            approval=lambda page, challenge, code: _perform_approval(
                page, challenge, code, no_browser
            ),
            picker=_browse_local_project_folder,
            owner_terminal=_owner_terminal,
        )
        return
    _require_local_pairing_storage()
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


def _resolve_device_alias(alias: str | None) -> str:
    if not alias:
        try:
            host = socket.gethostname() or ""
        except OSError:
            host = ""
        clean_host = re.sub(r"[^A-Za-z0-9 ._-]", "", host).strip(" ._-")
        candidate = f"{clean_host} KiCad"[:64] if clean_host else _DEFAULT_DEVICE_ALIAS
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}", candidate):
            return _DEFAULT_DEVICE_ALIAS
        return candidate
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}", alias):
        raise typer.BadParameter("Device alias must be 1 to 64 alphanumeric characters.")
    return alias


def _try_reconnect_existing(root: Path, origin: str) -> bool:
    projects_dir = root / "projects"
    keys_dir = root / "keys"
    if not (projects_dir.exists() and any(projects_dir.iterdir())):
        return False
    from kicad_mcp.cloud_registered_pilot import _single_registered_identity

    try:
        existing = _single_registered_identity(root)
    except Exception:
        return False
    if not (existing and existing.get("cloudOrigin") == origin):
        return False
    key_file = keys_dir / f"{existing['keySlot']}.pem"
    if not key_file.is_file():
        return False

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
    return True


def _perform_approval(page: str, challenge: str, code: str, no_browser: bool) -> None:
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


def _start_connector() -> str:
    try:
        from kicad_mcp.cloud_managed_connector import _enable, _status

        _enable()
        for _ in range(5):
            time.sleep(1)
            connector_state = _status()
            if connector_state in ("Connected", "Connecting"):
                return connector_state
        return _status()
    except Exception as exc:
        # An enabled marker is not an executable Connector. Never tell users
        # that Cloud access is ready when the service failed to start.
        typer.echo(f"Cloud Connector could not start: {type(exc).__name__}.", err=True)
        typer.echo(
            "Device registration was not rolled back; check cloud status "
            "before retrying cloud enable.",
            err=True,
        )
        return "Unavailable"


@cloud_app.command()
def setup(
    project_dir: Annotated[
        Path | None,
        typer.Option(
            "--project-dir",
            "-p",
            help="KiCad project directory; otherwise use current project or choose a folder.",
        ),
    ] = None,
    browse: Annotated[
        bool,
        typer.Option(
            "--browse",
            help="Choose a local KiCad project folder using a native desktop dialog.",
        ),
    ] = False,
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
    if browse and project_dir is not None:
        raise typer.BadParameter("Choose either --browse or --project-dir, not both.")
    device_alias = _resolve_device_alias(alias)
    if _is_windows():
        from kicad_mcp.cloud_windows_user_cli import setup_windows

        setup_windows(
            origin=origin,
            alias=device_alias,
            project_dir=project_dir,
            browse=browse,
            new_device=new_device,
            approval=lambda page, challenge, code: _perform_approval(
                page, challenge, code, no_browser
            ),
            picker=_browse_local_project_folder,
            owner_terminal=_owner_terminal,
        )
        return
    _require_local_pairing_storage()
    selected = _select_setup_project_directory(browse, project_dir)
    target_dir, stem = _discover_kicad_project(selected)

    from kicad_mcp.cloud_local_registry import default_registry_root

    root = default_registry_root()
    keys_dir = root / "keys"

    if not new_device and _try_reconnect_existing(root, origin):
        return

    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    keys_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    os.chmod(keys_dir, 0o700)

    slot = str(uuid.uuid4())
    keyfile = keys_dir / f"{slot}.pem"

    from kicad_mcp.cloud_pair import CloudPairingError, enroll, register_device_project
    from kicad_mcp.cloud_pair_keys import _read_owner_binding

    try:
        device_id, fingerprint = enroll(
            origin,
            device_alias,
            keyfile,
            lambda page, chal, code: _perform_approval(page, chal, code, no_browser),
        )
    except CloudPairingError as exc:
        raise typer.BadParameter("Device pairing failed or was denied.") from exc

    bound = _read_owner_binding(keyfile)
    owner_sub = bound.get("ownerSub")
    if not owner_sub:
        raise typer.BadParameter("Owner identity missing from device binding.")

    typer.echo(f"\nDevice paired: {device_id} (Fingerprint: {fingerprint[:16]}...)")
    typer.echo(f"Registering KiCad project {stem} on Cloud...")

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
    connector_state = _start_connector()

    typer.echo("\n" + "=" * 60)
    typer.echo(
        "KiCad MCP Pro Cloud Setup Complete!"
        if connector_state in ("Connected", "Connecting")
        else "KiCad MCP Pro Cloud device registered; Connector needs attention"
    )
    typer.echo("=" * 60)
    typer.echo(f"Cloud Origin:    {origin}")
    typer.echo(f"Device:          {device_alias} ({device_id}) [Review access in Cloud]")
    typer.echo(f"Project:         {stem} ({project_id})")
    typer.echo(f"Local Directory: {target_dir}")
    typer.echo(f"Connector:       {connector_state}")
    typer.echo(f"Web Dashboard:   {origin}/devices")
    typer.echo("AI Client Access: Requires separate Cloud owner approval")
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
    if _is_windows():
        from kicad_mcp.cloud_windows_user_cli import show_status

        show_status()
        return
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
    if _is_windows():
        from kicad_mcp.cloud_windows_user_cli import show_status

        show_status()
        return
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

    from kicad_mcp.services.client_config import get_owned_client_configs

    owned = get_owned_client_configs(root)
    if owned:
        typer.echo(f"Configured Clients: {', '.join(sorted(owned.keys()))}")
    else:
        typer.echo("Configured Clients: None (run 'kicad-mcp-pro init' to configure)")


@cloud_app.command()
def enable() -> None:
    """Explicitly enable the Connector for one already-registered local project."""
    if _is_windows():
        from kicad_mcp.cloud_windows_user_cli import enable_existing

        enable_existing(owner_terminal=_owner_terminal)
        return
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["enable"])
    if result:
        raise typer.Exit(result)


@cloud_app.command()
def disable() -> None:
    """Disable local Connector authority and stop its user service."""
    if _is_windows():
        from kicad_mcp.cloud_windows_user_cli import disable_local

        disable_local()
        return
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["disable"])
    if result:
        raise typer.Exit(result)


@cloud_app.command()
def disconnect() -> None:
    """Disable local Connector authority and stop its user service."""
    if _is_windows():
        from kicad_mcp.cloud_windows_user_cli import disable_local

        disable_local()
        return
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["disable"])
    if result:
        raise typer.Exit(result)


@cloud_app.command()
def reconnect() -> None:
    """Explicitly enable the Connector for one already-registered local project."""
    if _is_windows():
        from kicad_mcp.cloud_windows_user_cli import enable_existing

        enable_existing(owner_terminal=_owner_terminal)
        return
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["enable"])
    if result:
        raise typer.Exit(result)


@cloud_app.command("run", hidden=True)
def run() -> None:
    """Run the Cloud Connector in the foreground."""
    if _is_windows():
        from kicad_mcp.cloud_windows_connector import main as windows_connector

        result = windows_connector(["run"])
        if result:
            raise typer.Exit(result)
        return
    from kicad_mcp.cloud_managed_connector import main as connector

    result = connector(["run"])
    if result:
        raise typer.Exit(result)
