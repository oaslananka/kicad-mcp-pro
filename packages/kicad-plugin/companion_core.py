"""Small read-only IPC and localhost dashboard adapter for the KiCad companion.

No writes to the board, automatic shell commands or remote network calls.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil

# Safe, argv-only pip invocation (no shell), guarded by a KiCad-venv check
# and an explicit confirmation in the wx Companion UI.
import subprocess  # nosec B404
import sys
import tempfile
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
    selected_value: str = ""
    selected_footprint: str = ""
    selected_pad_count: int | None = None
    selected_nets: tuple[str, ...] = ()
    selected_unconnected_pads: int = 0
    # Logical pad net assignments, NOT verified copper connectivity.
    selected_net_peers: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class DrcFinding:
    severity: str
    check_type: str
    description: str
    objects: tuple[str, ...] = ()
    location: tuple[float, float] | None = None


@dataclass(frozen=True)
class SavedDrcResult:
    errors: int
    warnings: int
    unconnected: int
    excluded: int
    kicad_version: str
    findings: tuple[DrcFinding, ...] = ()
    coordinate_units: str = "mm"


def _read_drc_finding(entry: dict[str, Any]) -> DrcFinding:
    items = entry.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError("KiCad DRC report has malformed affected items.")
    affected: list[str] = []
    location = None
    for item in items[:8]:
        if not isinstance(item, dict):
            raise RuntimeError("KiCad DRC report has malformed affected items.")
        descriptor = item.get("description")
        if isinstance(descriptor, str) and descriptor:
            affected.append(descriptor[:180].replace("\n", " "))
        pos = item.get("pos")
        if location is None and isinstance(pos, dict):
            x, y = pos.get("x"), pos.get("y")
            if (
                isinstance(x, (int, float))
                and not isinstance(x, bool)
                and isinstance(y, (int, float))
                and not isinstance(y, bool)
                and math.isfinite(x)
                and math.isfinite(y)
            ):
                location = (float(x), float(y))
    check_type = entry.get("type")
    description = entry.get("description")
    if not isinstance(check_type, str):
        check_type = "unknown_check"
    if not isinstance(description, str):
        description = "Description unavailable"
    return DrcFinding(
        severity=entry["severity"],
        check_type=check_type[:80],
        description=description[:300].replace("\n", " "),
        objects=tuple(affected),
        location=location,
    )


def _saved_board_file(summary: BoardSummary) -> Path:
    """Resolve only the saved PCB in the active KiCad project directory."""
    root = Path(summary.project_path).expanduser()
    if root.suffix == ".kicad_pro":
        root = root.parent
    if not root.is_absolute() or not root.is_dir() or not summary.name:
        raise RuntimeError("Save the active PCB in a project before checking DRC.")
    original = Path(summary.name)
    candidate = (original if original.is_absolute() else root / original).resolve()
    if (
        candidate.parent != root.resolve()
        or candidate.suffix != ".kicad_pcb"
        or not candidate.is_file()
    ):
        raise RuntimeError("The active PCB must be saved in its project directory.")
    return candidate


def run_saved_board_drc(
    summary: BoardSummary, *, cli: str = "kicad-cli", timeout: int = 45
) -> SavedDrcResult:
    """User-triggered DRC on a private copy of the SAVED board, not editor state.

    Only generated CLI output and local project-rule copies touch the temporary
    directory. No refill, save-board, remote API request or manufacturing gate.
    """
    saved = _saved_board_file(summary)
    before_hash = hashlib.sha256(saved.read_bytes()).digest()
    with tempfile.TemporaryDirectory(prefix="kicad-companion-drc-") as scratch:
        work = Path(scratch)
        copied_board = work / saved.name
        shutil.copyfile(saved, copied_board)
        for extension in (".kicad_pro", ".kicad_dru"):
            candidate = saved.with_suffix(extension)
            if candidate.is_file() and not candidate.is_symlink():
                shutil.copyfile(candidate, work / candidate.name)
        report = work / "saved-board-drc.json"
        try:
            process = subprocess.run(  # nosec B603
                [cli, "pcb", "drc", "--format", "json", "--output", str(report), str(copied_board)],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("KiCad CLI DRC could not finish.") from exc
        if process.returncode != 0 or not report.is_file() or report.stat().st_size > 3_000_000:
            raise RuntimeError("KiCad CLI did not produce a complete DRC report.")
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("KiCad CLI produced an invalid DRC report.") from exc
    if hashlib.sha256(saved.read_bytes()).digest() != before_hash:
        raise RuntimeError("Saved PCB changed during DRC; discard this report.")
    if not isinstance(payload, dict):
        raise RuntimeError("KiCad DRC report has an unexpected format.")
    violations = payload.get("violations")
    unconnected = payload.get("unconnected_items")
    version = payload.get("kicad_version")
    if (
        not isinstance(violations, list)
        or not isinstance(unconnected, list)
        or not isinstance(version, str)
        or not version
        or payload.get("source") != saved.name
    ):
        raise RuntimeError("KiCad DRC report is incomplete or mismatched.")
    if any(
        not isinstance(v, dict) or v.get("severity") not in ("error", "warning", "exclusion")
        for v in violations + unconnected
    ):
        raise RuntimeError("KiCad DRC report contains unknown severity.")
    units = payload.get("coordinate_units", "mm")
    if units not in ("mm", "in", "mils"):
        raise RuntimeError("KiCad DRC report uses unexpected coordinate units.")
    ordered = (
        [v for v in violations if v["severity"] == "error"]
        + list(unconnected)
        + [v for v in violations if v["severity"] == "warning"]
        + [v for v in violations if v["severity"] == "exclusion"]
    )
    findings = tuple(_read_drc_finding(entry) for entry in ordered)
    return SavedDrcResult(
        errors=sum(v["severity"] == "error" for v in violations),
        warnings=sum(v["severity"] == "warning" for v in violations),
        unconnected=len(unconnected),
        excluded=sum(v["severity"] == "exclusion" for v in violations),
        kicad_version=version,
        findings=findings,
        coordinate_units=units,
    )


def _footprint_ref(item: object) -> str:
    reference = getattr(item, "reference", None)
    if not isinstance(reference, str) or not reference:
        field = getattr(item, "reference_field", None)
        reference = getattr(getattr(field, "text", None), "value", None)
    return reference if isinstance(reference, str) else ""


def _pad_net_names(item: object) -> set[str]:
    definition = getattr(item, "definition", None)
    pads = getattr(definition, "pads", None)
    if not isinstance(pads, (list, tuple)):
        return set()
    names = set()
    for pad in pads:
        net_name = getattr(getattr(pad, "net", None), "name", None)
        if isinstance(net_name, str) and net_name:
            names.add(net_name)
    return names


def board_summary(kicad_factory: Callable[[], Any] | None = None) -> BoardSummary:
    """Read the open board through KiCad's official IPC API."""
    if kicad_factory is None:
        from kipy import KiCad

        kicad_factory = KiCad
    client = kicad_factory()
    board = client.get_board()
    project = board.get_project()
    selection = board.get_selection()
    footprints = board.get_footprints()
    selected_reference = ""
    selected_value = ""
    selected_footprint = ""
    selected_pad_count: int | None = None
    selected_nets: tuple[str, ...] = ()
    selected_unconnected_pads = 0
    selected_net_peers: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # A multi-selection must not falsely attribute the first footprint's
    # value and nets to all selected items, or publish its reference as sole.
    if len(selection) == 1:
        item = selection[0]
        selected_reference = _footprint_ref(item)

        definition = getattr(item, "definition", None)
        if selected_reference and definition is not None:
            value_field = getattr(item, "value_field", None)
            value = getattr(getattr(value_field, "text", None), "value", None)
            if isinstance(value, str):
                selected_value = value
            identifier = getattr(definition, "id", None)
            library = getattr(identifier, "library", None)
            name = getattr(identifier, "name", None)
            if isinstance(library, str) and isinstance(name, str) and name:
                selected_footprint = f"{library}:{name}" if library else name
            pads = getattr(definition, "pads", None)
            if isinstance(pads, (list, tuple)):
                selected_pad_count = len(pads)
                net_names: set[str] = set()
                for pad in pads:
                    net = getattr(pad, "net", None)
                    net_name = getattr(net, "name", None)
                    if isinstance(net_name, str) and net_name:
                        net_names.add(net_name)
                    else:
                        selected_unconnected_pads += 1
                selected_nets = tuple(sorted(net_names))

        # Scan the already-fetched footprint collection once. A shared net
        # label means logical assignment, never routed copper or DRC success.
        if selected_reference and selected_nets:
            selected_names = set(selected_nets)
            net_peers: dict[str, set[str]] = {net: set() for net in selected_nets}
            for other in footprints:
                other_ref = _footprint_ref(other)
                if not other_ref or other_ref == selected_reference:
                    continue
                for name in _pad_net_names(other) & selected_names:
                    net_peers[name].add(other_ref)
            selected_net_peers = tuple(
                (net, tuple(sorted(refs))) for net, refs in sorted(net_peers.items()) if refs
            )
    return BoardSummary(
        name=str(board.name),
        project=str(project.name),
        footprints=len(footprints),
        nets=len(board.get_nets()),
        selected=len(selection),
        project_path=str(getattr(project, "path", "")),
        selected_reference=selected_reference,
        selected_value=selected_value,
        selected_footprint=selected_footprint,
        selected_pad_count=selected_pad_count,
        selected_nets=selected_nets,
        selected_unconnected_pads=selected_unconnected_pads,
        selected_net_peers=selected_net_peers,
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
