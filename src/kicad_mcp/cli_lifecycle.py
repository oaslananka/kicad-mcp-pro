"""Explicit, read-only package lifecycle guidance; no implicit updates.

MCP stdio startup must never perform an update check or print status.
The package manager owns package mutation, not the running MCP process.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import typer
import urllib3
from packaging.version import InvalidVersion, Version

from kicad_mcp import __version__

_PACKAGE = "kicad-mcp-pro"
_PYPI_HOST = "pypi.org"
_MAX_PYPI_RESPONSE = 4 * 1024 * 1024

update_app = typer.Typer(
    help="Check for stable package releases and show the right upgrade command.",
    invoke_without_command=True,
)


class ReleaseLookupError(ValueError):
    """The public release index could not be verified."""


def _install_manager(executable: str | Path | None = None) -> str:
    """Infer only recognizable tool-managed virtual environments."""
    path = str(executable if executable is not None else sys.executable)
    normalized = path.replace(chr(92), "/").casefold()
    if "/uv/tools/kicad-mcp-pro/" in normalized:
        return "uv"
    if "/pipx/venvs/kicad-mcp-pro/" in normalized:
        return "pipx"
    return "unknown"


def _path_launchers(
    directories: Sequence[str] | None = None,
    *,
    windows: bool | None = None,
) -> list[str]:
    """List all matching PATH executables without running any of them."""
    roots = directories if directories is not None else os.environ.get("PATH", "").split(os.pathsep)
    is_windows = (os.name == "nt") if windows is None else windows
    extensions = (".exe", ".cmd", ".bat") if is_windows else ("",)
    results: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not root:
            continue
        for suffix in extensions:
            candidate = Path(root) / f"kicad-mcp-pro{suffix}"
            if not candidate.is_file():
                continue
            path = str(candidate.resolve())
            key = path.casefold() if is_windows else path
            if key not in seen:
                seen.add(key)
                results.append(path)
    return results


def _manager_command(manager: str, action: str) -> str | None:
    if manager == "uv":
        return f"uv tool {action} {_PACKAGE}"
    if manager == "pipx":
        return f"pipx {'upgrade' if action == 'upgrade' else 'uninstall'} {_PACKAGE}"
    return None


def _fetch_latest_stable() -> str:
    """Only on an explicit update invocation. Never run during MCP startup."""
    pool = urllib3.HTTPSConnectionPool(
        _PYPI_HOST,
        443,
        timeout=urllib3.Timeout(connect=5, read=5),
        retries=False,
        cert_reqs="CERT_REQUIRED",
    )
    try:
        response = pool.request(
            "GET",
            f"/pypi/{_PACKAGE}/json",
            headers={"Accept": "application/json"},
            retries=False,
            redirect=False,
            preload_content=False,
        )
        try:
            if response.status != 200:
                raise ReleaseLookupError("PyPI did not return a successful release response.")
            payload_bytes = response.read(_MAX_PYPI_RESPONSE + 1)
            if len(payload_bytes) > _MAX_PYPI_RESPONSE:
                raise ReleaseLookupError("PyPI release metadata exceeded the size limit.")
        finally:
            response.release_conn()
        payload = json.loads(payload_bytes)
        info = payload["info"]
        if (
            not isinstance(info, dict)
            or str(info.get("name", "")).casefold().replace("_", "-") != _PACKAGE
        ):
            raise ReleaseLookupError("PyPI release metadata does not match this package.")
        latest = Version(info["version"])
        if latest.is_prerelease or latest.is_devrelease:
            raise ReleaseLookupError("The release index did not provide a stable version.")
        return str(latest)
    except (
        KeyError,
        TypeError,
        json.JSONDecodeError,
        InvalidVersion,
        urllib3.exceptions.HTTPError,
        OSError,
    ) as exc:
        raise ReleaseLookupError("Could not verify the latest stable PyPI release.") from exc
    finally:
        pool.close()


def _update_report() -> dict[str, str | None]:
    installed = Version(__version__)
    latest = Version(_fetch_latest_stable())
    manager = _install_manager()
    return {
        "installed": str(installed),
        "latest_stable": str(latest),
        "status": "update_available" if latest > installed else "up_to_date",
        "manager": manager,
        "upgrade_command": _manager_command(manager, "upgrade"),
    }


def _show_update(json_output: bool) -> None:
    try:
        result = _update_report()
    except ReleaseLookupError as exc:
        if json_output:
            typer.echo(json.dumps({"status": "lookup_failed", "error": str(exc)}))
        else:
            typer.echo(f"Update check unavailable: {exc}", err=True)
            typer.echo("The installed version has not been changed.", err=True)
        raise typer.Exit(code=3) from exc

    if json_output:
        typer.echo(json.dumps(result, sort_keys=True))
        return
    typer.echo(f"Installed: {result['installed']}; latest stable: {result['latest_stable']}")
    if result["status"] == "up_to_date":
        typer.echo("Already up to date. No installation changes were made.")
        return
    typer.echo("A newer stable version is available.")
    if result["upgrade_command"]:
        typer.echo(f"Upgrade using your package manager: {result['upgrade_command']}")
    else:
        typer.echo(
            "Installation manager not confirmed. Identify whether this CLI came "
            "from uv, pipx or pip before changing it."
        )
    typer.echo("No update was installed automatically.")


@update_app.callback(invoke_without_command=True)
def update_root(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Show machine-readable status."),
) -> None:
    """Show the current and latest stable versions; never silently replace this CLI."""
    if ctx.invoked_subcommand is None:
        _show_update(json_output)


@update_app.command("check")
def check(
    json_output: bool = typer.Option(False, "--json", help="Show machine-readable status."),
) -> None:
    """Check PyPI for a newer stable version on demand."""
    _show_update(json_output)


def uninstall() -> None:
    """Show a safe removal command for the actual package manager."""
    manager = _install_manager()
    typer.echo(f"Detected package manager: {manager}")
    command = _manager_command(manager, "uninstall")
    if command is None:
        typer.echo(
            "Installer unknown. Check which kicad-mcp-pro executable runs, then "
            "uninstall it using that installation's manager."
        )
    else:
        typer.echo(f"Run this command outside the application: {command}")
    typer.echo(
        "Removing this package does not revoke Cloud access or delete saved "
        "AI client entries. KiCad projects and unrelated settings must be preserved."
    )
    typer.echo("No package, project or configuration was removed.")
