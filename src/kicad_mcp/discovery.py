"""KiCad installation and project discovery helpers."""

from __future__ import annotations

import atexit
import inspect
import json
import platform
import random
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class _StudioWatcherState:
    thread: threading.Thread | None = None
    root: Path | None = None


_WATCHER_LOCK = threading.Lock()
_WATCHER_STATE = _StudioWatcherState()
_WATCHER_STOP = threading.Event()
_CLI_CAPABILITIES_CACHE: dict[tuple[Path, int | None], CliCapabilities] = {}
_NUMBERED_DUPLICATE_RE = re.compile(r"^.+\s+\d+\.kicad_(?:pro|sch|pcb)$", re.IGNORECASE)


@dataclass(frozen=True)
class CliCapabilities:
    """Cached CLI capability summary."""

    version: str | None
    gerber_command: str = "gerber"
    drill_command: str = "drill"
    position_command: str = "pos"
    supports_ipc2581: bool = False
    supports_odb_export: bool = False
    supports_svg: bool = False
    supports_dxf: bool = False
    supports_step: bool = False
    supports_stepz: bool = False
    supports_xao: bool = False
    supports_render: bool = False
    supports_3d_pdf: bool = False
    supports_spice_netlist: bool = False
    supports_specctra_export: bool = False
    supports_specctra_import: bool = False
    supports_allegro_import: bool = False
    supports_pads_import: bool = False
    supports_geda_import: bool = False
    supports_cli_variant: bool = False
    supports_drc_severity_all: bool = False
    supports_drc_exit_code_violations: bool = False
    supports_brep: bool = False
    supports_glb: bool = False
    supports_gencad: bool = False
    supports_ipc_d356: bool = False
    supports_ply: bool = False
    supports_stl: bool = False
    supports_u3d: bool = False
    supports_vrml: bool = False
    supports_ps: bool = False


def _candidate_cli_paths() -> list[Path]:
    system = platform.system()
    if system == "Windows":
        # Prefer the released stable KiCad 10 installation. The KiCad 11
        # candidate is a future-compatible probe, not an assertion that 11
        # is installed (or released).
        return [
            Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"),
            Path(r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"),
            Path(r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe"),
            Path(r"C:\Program Files\KiCad\11.0\bin\kicad-cli.exe"),
        ]
    if system == "Darwin":
        return [
            Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"),
            Path("/usr/local/bin/kicad-cli"),
            Path("/opt/homebrew/bin/kicad-cli"),
        ]
    return [
        Path("/usr/bin/kicad-cli"),
        Path("/usr/local/bin/kicad-cli"),
        Path("/snap/bin/kicad-cli"),
        Path("/var/lib/flatpak/exports/bin/kicad-cli"),
        Path("/flatpak/exports/bin/kicad-cli"),
    ]


def _is_ephemeral_cli_path(cli: Path) -> bool:
    """Report whether ``cli`` lives under a transient AppImage FUSE mount."""
    # AppImage mount roots are named ``.mount_<random>``. Match that semantic
    # component rather than trusting a particular temporary-directory prefix:
    # the mount may live under /tmp, XDG_RUNTIME_DIR, or another runtime root.
    return any(part.startswith(".mount_") for part in cli.parts)


def _discover_via_kipy() -> Path | None:
    try:
        from kipy.kicad import KiCad
    except ImportError:
        return None

    kicad = None
    try:
        if "headless" in inspect.signature(KiCad.__init__).parameters:
            headless_ctor = cast(Callable[..., KiCad], KiCad)
            kicad = headless_ctor(headless=True, timeout_ms=1000)
        else:
            kicad = KiCad(timeout_ms=1000)
        cli = Path(kicad.get_kicad_binary_path("kicad-cli"))
        if not cli.exists():
            return None
        if _is_ephemeral_cli_path(cli):
            # Fall through to PATH/candidate discovery rather than caching a path
            # that stops resolving as soon as the running KiCad exits.
            logger.debug("kipy_cli_discovery_ephemeral", path=str(cli))
            return None
        return cli
    except Exception as exc:
        logger.debug("kipy_cli_discovery_failed", error=str(exc))
        return None
    finally:
        if kicad is not None:
            try:
                close_fn = getattr(kicad, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception as exc:
                logger.debug("kipy_headless_close_failed", error=str(exc))


def discover_kicad_cli() -> Path:
    """Find the best available kicad-cli executable."""
    from_kipy = _discover_via_kipy()
    if from_kipy is not None:
        return from_kipy

    on_path = shutil.which("kicad-cli")
    if on_path:
        return Path(on_path)

    for candidate in _candidate_cli_paths():
        if candidate.exists():
            return candidate

    # Never expose an imaginary versioned Windows installation as a
    # discovered executable; the diagnostics UI should report an unavailable
    # CLI rather than claiming a nonexistent KiCad 11 location.
    if platform.system() == "Windows":
        return Path("kicad-cli")
    return _candidate_cli_paths()[0]


def find_kicad_version(cli_path: Path) -> str | None:
    """Return the KiCad CLI version string."""
    try:
        result = subprocess.run(
            [str(cli_path), "--version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError, PermissionError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr).strip()
    return text or None


def get_cli_capabilities(cli_path: Path) -> CliCapabilities:
    """Inspect the local CLI and cache supported commands."""
    cache_key = _cli_capabilities_cache_key(cli_path)
    cached = _CLI_CAPABILITIES_CACHE.get(cache_key)
    if cached is not None:
        return cached

    version = find_kicad_version(cli_path)
    if not cli_path.exists():
        capabilities = CliCapabilities(version=version)
        _CLI_CAPABILITIES_CACHE[cache_key] = capabilities
        return capabilities

    help_outputs: list[str] = []
    commands = (
        [str(cli_path), "pcb", "export", "--help"],
        [str(cli_path), "pcb", "import", "--help"],
        [str(cli_path), "sch", "export", "--help"],
        [str(cli_path), "pcb", "--help"],
        [str(cli_path), "pcb", "drc", "--help"],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, OSError, PermissionError, subprocess.TimeoutExpired):
            continue
        help_outputs.append(f"{result.stdout}\n{result.stderr}")

    blob = "\n".join(help_outputs).lower()
    tokens = set(re.findall(r"[a-z0-9_-]+", blob))
    gerber_command = "gerbers" if "gerbers" in tokens else "gerber"
    position_command = "positions" if "positions" in tokens else "pos"

    capabilities = CliCapabilities(
        version=version,
        gerber_command=gerber_command,
        position_command=position_command,
        supports_ipc2581="ipc2581" in blob,
        supports_odb_export="odb++" in blob or "odb" in tokens,
        supports_svg=" export svg" in blob or " svg " in blob,
        supports_dxf=" export dxf" in blob or " dxf " in blob,
        supports_step=" export step" in blob or " step " in blob,
        supports_stepz="stpz" in tokens or "stepz" in tokens,
        supports_xao="xao" in tokens,
        supports_render=" render " in blob,
        supports_3d_pdf="3dpdf" in blob or "3d pdf" in blob,
        supports_spice_netlist="spice" in blob,
        supports_specctra_export="specctra" in blob or " dsn " in blob,
        supports_specctra_import="specctra" in blob or " ses " in blob,
        supports_allegro_import="allegro" in blob,
        supports_pads_import="pads" in blob,
        supports_geda_import="geda" in blob,
        supports_cli_variant="--variant" in blob,
        supports_brep=" brep " in blob or "brep" in tokens,
        supports_glb=" glb " in blob or "glb" in tokens,
        supports_gencad="gencad" in tokens,
        supports_ipc_d356="d356" in tokens or "ipc-d356" in blob,
        supports_ply=" ply " in blob or "ply" in tokens,
        supports_stl=" stl " in blob or "stl" in tokens,
        supports_u3d="u3d" in tokens,
        supports_vrml="vrml" in tokens,
        supports_ps=" ps " in blob or "postscript" in blob,
        supports_drc_severity_all="--severity-all" in blob or "severity-all" in blob,
        supports_drc_exit_code_violations="--exit-code-violations" in blob
        or "exit-code-violations" in blob,
    )
    _CLI_CAPABILITIES_CACHE[cache_key] = capabilities
    return capabilities


def _cli_capabilities_cache_key(cli_path: Path) -> tuple[Path, int | None]:
    resolved = cli_path.expanduser().resolve(strict=False)
    try:
        mtime_ns = resolved.stat().st_mtime_ns
    except OSError:
        mtime_ns = None
    return resolved, mtime_ns


def _clear_cli_capabilities_cache() -> None:
    _CLI_CAPABILITIES_CACHE.clear()


cast(Any, get_cli_capabilities).cache_clear = _clear_cli_capabilities_cache


def _platform_library_roots(system: str) -> list[Path]:
    """Return the conventional KiCad shared-support roots for a platform.

    Kept separate from :func:`discover_library_paths` so callers and tests can
    substitute the platform's install locations instead of depending on what
    happens to be installed on the host.
    """
    if system == "Windows":
        return [
            Path(r"C:\Program Files\KiCad\11.0\share\kicad"),
            Path(r"C:\Program Files\KiCad\10.0\share\kicad"),
            Path(r"C:\Program Files\KiCad\9.0\share\kicad"),
            Path(r"C:\Program Files\KiCad\8.0\share\kicad"),
        ]
    if system == "Darwin":
        return [
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport"),
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/share/kicad"),
        ]
    return [Path("/usr/share/kicad"), Path("/usr/local/share/kicad")]


def discover_library_paths(cli_path: Path) -> dict[str, Path | None]:
    """Discover symbol and footprint library directories."""
    candidates: list[Path] = []
    resolved_cli = cli_path.expanduser()
    if resolved_cli.exists():
        parents = [
            resolved_cli.parent,
            resolved_cli.parent.parent,
            resolved_cli.parent.parent.parent,
        ]
        candidates.extend(parents)
        candidates.extend(parent / "share" / "kicad" for parent in parents)

    candidates.extend(_platform_library_roots(platform.system()))

    for base in candidates:
        share_root = base / "share" / "kicad" if not (base / "symbols").exists() else base
        symbols = share_root / "symbols"
        footprints = share_root / "footprints"
        if symbols.exists() or footprints.exists():
            return {
                "root": share_root,
                "symbols": symbols if symbols.exists() else None,
                "footprints": footprints if footprints.exists() else None,
            }

    return {"root": None, "symbols": None, "footprints": None}


def find_recent_projects(limit: int = 10) -> list[Path]:
    """Find recently opened KiCad projects on this system."""
    system = platform.system()
    if system == "Windows":
        config_dirs = [
            Path.home() / "AppData" / "Roaming" / "kicad" / "11.0",
            Path.home() / "AppData" / "Roaming" / "kicad" / "10.0",
        ]
    elif system == "Darwin":
        config_dirs = [
            Path.home() / "Library" / "Preferences" / "kicad" / "11.0",
            Path.home() / "Library" / "Preferences" / "kicad" / "10.0",
        ]
    else:
        config_dirs = [
            Path.home() / ".config" / "kicad" / "11.0",
            Path.home() / ".config" / "kicad" / "10.0",
        ]

    project_files: list[Path] = []
    for config_dir in config_dirs:
        common = config_dir / "kicad_common.json"
        if not common.exists():
            continue
        try:
            data = json.loads(common.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        recent = data.get("recentlyUsedFiles", {}).get("projects", [])
        for raw in recent:
            candidate = Path(raw).expanduser()
            if candidate.exists() and candidate.suffix == ".kicad_pro":
                project_files.append(candidate)
        if project_files:
            break
    return project_files[:limit]


def _is_confined_discovery_candidate(directory: Path, candidate: Path) -> bool:
    """Return whether a discovered file resolves inside the scanned project directory."""
    root = directory.expanduser().resolve()
    resolved = candidate.expanduser().resolve()
    return resolved.is_relative_to(root)


def scan_project_dir(directory: Path) -> dict[str, Path | None]:
    """Scan a directory for KiCad project files."""
    result: dict[str, Path | None] = {
        "project": None,
        "pcb": None,
        "schematic": None,
    }
    if not directory.exists() or not directory.is_dir():
        return result

    for extension, key in (
        (".kicad_pro", "project"),
        (".kicad_pcb", "pcb"),
        (".kicad_sch", "schematic"),
    ):
        matches = [
            candidate
            for candidate in sorted(directory.glob(f"*{extension}"))
            if _is_confined_discovery_candidate(directory, candidate)
        ]
        if not matches:
            continue
        # Board and root schematic share the project's stem; the directory name need not.
        project = result["project"]
        project_match = directory / f"{project.stem}{extension}" if project else None
        if project_match in matches:
            result[key] = project_match
        else:
            result[key] = select_canonical_kicad_file(directory, matches, extension)
    return result


def is_numbered_duplicate_kicad_file(path: Path) -> bool:
    """Return true for Finder/iCloud-style numbered duplicate KiCad files."""
    return bool(_NUMBERED_DUPLICATE_RE.match(path.name))


def select_canonical_kicad_file(
    directory: Path,
    matches: list[Path],
    extension: str,
) -> Path | None:
    """Select the safest default KiCad file from same-extension candidates.

    Directory scans should prefer ``<directory-name>.<extension>`` over stale
    numbered sync-conflict duplicates such as ``project 2.kicad_pro``.  If no
    canonical match exists, numbered duplicates are ignored while a normal
    candidate exists.  When the only candidate is numbered, it is still returned
    for backward compatibility with intentionally numbered project names.
    """
    confined_matches = [
        candidate for candidate in matches if _is_confined_discovery_candidate(directory, candidate)
    ]
    if not confined_matches:
        return None
    matches = confined_matches

    canonical = directory / f"{directory.name}{extension}"
    for candidate in matches:
        if candidate.resolve() == canonical.resolve():
            return candidate

    non_duplicates = [
        candidate for candidate in matches if not is_numbered_duplicate_kicad_file(candidate)
    ]
    if non_duplicates:
        return non_duplicates[0]
    return matches[0]


def _discover_project_root(candidate: Path) -> tuple[Path, dict[str, Path | None]] | None:
    current = candidate if candidate.is_dir() else candidate.parent
    for directory in [current, *current.parents]:
        scan = scan_project_dir(directory)
        if any(scan.values()):
            return directory, scan
    return None


def auto_set_project_from_file(active_file: str | Path) -> Path | None:
    """Detect a KiCad project from an opened file and make it active."""
    candidate = Path(active_file).expanduser()
    discovered = _discover_project_root(candidate)
    if discovered is None:
        return None

    project_dir, scan = discovered

    from .config import get_config
    from .connection import reset_connection

    cfg = get_config()
    cfg.apply_project(
        project_dir.resolve(),
        project_file=scan.get("project"),
        pcb_file=scan.get("pcb"),
        sch_file=scan.get("schematic"),
        output_dir=project_dir.resolve() / "output",
        explicit=False,
    )
    reset_connection()
    logger.info("studio_project_auto_detected", project_dir=str(project_dir))
    return project_dir.resolve()


def poll_studio_watch_dir(
    watch_dir: Path,
    previous: dict[Path, float] | None = None,
) -> dict[Path, float]:
    """Poll a watch directory for changed ``.kicad_pro`` files and auto-select the project."""
    baseline = previous or {}
    current: dict[Path, float] = {}
    latest_changed: Path | None = None
    latest_mtime = -1.0

    if not watch_dir.exists():
        return current

    for project_file in watch_dir.rglob("*.kicad_pro"):
        try:
            mtime = project_file.stat().st_mtime
        except OSError:
            continue
        current[project_file.resolve()] = mtime
        if baseline.get(project_file.resolve()) != mtime and mtime >= latest_mtime:
            latest_changed = project_file.resolve()
            latest_mtime = mtime

    if latest_changed is not None:
        try:
            from .config import get_config

            cfg = get_config()
            if cfg.project_dir_is_explicit:
                logger.info(
                    "studio_watch_project_detected_without_override",
                    path=str(latest_changed),
                    active_project_dir=str(cfg.project_dir),
                )
            else:
                auto_set_project_from_file(latest_changed)
        except Exception as exc:
            logger.warning(
                "studio_watch_auto_detect_failed",
                path=str(latest_changed),
                error=str(exc),
            )

    return current


def ensure_studio_project_watcher(watch_dir: Path, poll_interval_seconds: float = 2.0) -> None:
    """Start a lightweight polling watcher for KiCad Studio bridge workflows."""
    resolved_root = watch_dir.expanduser().resolve()
    with _WATCHER_LOCK:
        if (
            _WATCHER_STATE.thread is not None
            and _WATCHER_STATE.thread.is_alive()
            and _WATCHER_STATE.root == resolved_root
        ):
            return

        _WATCHER_STOP.set()
        if _WATCHER_STATE.thread is not None and _WATCHER_STATE.thread.is_alive():
            _WATCHER_STATE.thread.join(timeout=0.5)
        _WATCHER_STATE.thread = None
        _WATCHER_STATE.root = None

        _WATCHER_STOP.clear()
        _WATCHER_STATE.root = resolved_root

        def _worker() -> None:
            previous: dict[Path, float] = {}
            interval = poll_interval_seconds
            while not _WATCHER_STOP.is_set():
                if resolved_root.exists():
                    previous = poll_studio_watch_dir(resolved_root, previous)
                    interval = poll_interval_seconds
                else:
                    previous = {}
                    interval = min(max(poll_interval_seconds, interval) * 2.0, 30.0)
                    logger.warning(
                        "studio_watch_dir_missing",
                        watch_dir=str(resolved_root),
                        retry_in_seconds=round(interval, 2),
                    )
                sleep_for = max(
                    0.1,
                    interval * random.uniform(0.9, 1.1),  # noqa: S311 - scheduler jitter only
                )
                _WATCHER_STOP.wait(sleep_for)

        _WATCHER_STATE.thread = threading.Thread(
            target=_worker,
            name="kicad-mcp-studio-watch",
            daemon=True,
        )
        _WATCHER_STATE.thread.start()
        logger.info("studio_watch_started", watch_dir=str(resolved_root))


def stop_studio_project_watcher() -> None:
    """Stop the background studio watch thread if it is running."""
    with _WATCHER_LOCK:
        _WATCHER_STOP.set()
        if _WATCHER_STATE.thread is not None and _WATCHER_STATE.thread.is_alive():
            _WATCHER_STATE.thread.join(timeout=0.5)
        _WATCHER_STATE.thread = None
        _WATCHER_STATE.root = None


atexit.register(stop_studio_project_watcher)
