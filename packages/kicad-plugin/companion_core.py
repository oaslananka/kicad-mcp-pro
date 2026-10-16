"""Small read-only IPC and localhost dashboard adapter for the KiCad companion.

No writes to the board, automatic shell commands or remote network calls.
"""

from __future__ import annotations

import os

# Safe, argv-only pip invocation (no shell), guarded by a KiCad-venv check
# and an explicit confirmation in the wx Companion UI.
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:3334"


@dataclass(frozen=True)
class BoardSummary:
    name: str
    project: str
    footprints: int
    nets: int
    selected: int
    project_path: str = ""
    selected_reference: str = ""


def board_summary(kicad_factory: Callable[[], Any] | None = None) -> BoardSummary:
    """Read the open board through KiCad's official IPC API."""
    if kicad_factory is None:
        from kipy import KiCad

        kicad_factory = KiCad
    client = kicad_factory()
    board = client.get_board()
    project = board.get_project()
    selection = board.get_selection()
    selected_reference = ""
    for item in selection:
        reference = getattr(item, "reference", None)
        if isinstance(reference, str):
            selected_reference = reference
            break
    return BoardSummary(
        name=str(board.name),
        project=str(project.name),
        footprints=len(board.get_footprints()),
        nets=len(board.get_nets()),
        selected=len(selection),
        project_path=str(getattr(project, "path", "")),
        selected_reference=selected_reference,
    )


def _client_and_compatibility(
    *,
    client_factory: Callable[..., Any] | None = None,
    compatibility_loader: Callable[[], dict[str, object]] | None = None,
) -> tuple[Any, dict[str, object]]:
    from context import StudioContextClient, load_compatibility_contract

    base_url = os.environ.get("KICAD_MCP_URL", DEFAULT_BASE_URL)
    token = os.environ.get("KICAD_MCP_AUTH_TOKEN", "")
    factory = client_factory or StudioContextClient
    loader = compatibility_loader or load_compatibility_contract
    return factory(base_url, auth_token=token), loader()


def backend_status(
    *,
    client_factory: Callable[..., Any] | None = None,
    compatibility_loader: Callable[[], dict[str, object]] | None = None,
) -> tuple[bool, str]:
    """Check backend readiness with the existing versioned and loopback-only contract."""
    try:
        client, compatibility = _client_and_compatibility(
            client_factory=client_factory,
            compatibility_loader=compatibility_loader,
        )
        health = client.health(compatibility)
    except (OSError, RuntimeError, ValueError) as exc:
        return False, f"Backend unavailable: {exc}"
    return health.state == "ready", health.message


def dashboard_url(fragment: str = "") -> str:
    """Only open a loopback web UI; never allow an arbitrary external dashboard URL."""
    from urllib.parse import urlsplit, urlunsplit

    from context import _validate_loopback_base_url

    base = os.environ.get("KICAD_MCP_URL", DEFAULT_BASE_URL).rstrip("/")
    _validate_loopback_base_url(base)
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, "/ui", "", fragment.lstrip("#")))


def sync_board_context(
    summary: BoardSummary,
    *,
    client_factory: Callable[..., Any] | None = None,
    compatibility_loader: Callable[[], dict[str, object]] | None = None,
) -> None:
    """Publish a read-only board snapshot through the existing MCP context contract."""
    from context import BoardInfo, build_studio_context

    client, compatibility = _client_and_compatibility(
        client_factory=client_factory, compatibility_loader=compatibility_loader
    )
    health = client.health(compatibility)
    if health.state != "ready":
        raise RuntimeError(health.message)

    file_name = summary.name
    project_root = summary.project_path
    if project_root and project_root.endswith(".kicad_pro"):
        project_root = str(Path(project_root).parent)
    if project_root and file_name and not Path(file_name).is_absolute():
        candidate = Path(project_root) / file_name
        if candidate.is_file():
            file_name = str(candidate)

    client.push(
        build_studio_context(
            BoardInfo(
                file_name=file_name,
                file_type="pcb",
                project_root=project_root,
                project_file=file_name,
                selected_reference=summary.selected_reference,
            )
        )
    )


def repair_ipc_dependencies(
    *,
    python_executable: str | None = None,
    requirements_path: Path | None = None,
    in_virtualenv: bool | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Repair only KiCad's active plugin venv after explicit user confirmation.

    KiCad's Python manager sometimes sees packages in user-site during pip
    resolution but hides that site when running an IPC action. Disabling the
    user site for this install prevents falsely satisfied dependencies.
    """
    is_venv = sys.prefix != sys.base_prefix if in_virtualenv is None else in_virtualenv
    if not is_venv:
        raise RuntimeError("IPC dependency repair requires a KiCad-managed virtual environment")
    requirements = requirements_path or Path(__file__).with_name("requirements.txt")
    if not requirements.is_file():
        raise RuntimeError("Plugin requirements are missing; reinstall the KiCad plugin")

    command = [
        python_executable or sys.executable,
        "-m",
        "pip",
        "install",
        "--no-input",
        "--isolated",
        "--only-binary",
        ":all:",
        "--require-virtualenv",
        "-r",
        str(requirements),
    ]
    environment = os.environ.copy()
    environment["PYTHONNOUSERSITE"] = "1"
    environment.pop("PIP_USER", None)
    try:
        result = runner(
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("KiCad's private Python dependency repair could not finish") from exc
    if result.returncode != 0:
        raise RuntimeError(
            "KiCad's private Python dependency repair failed. "
            "Check network access and the plugin log."
        )
