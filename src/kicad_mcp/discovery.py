"""KiCad installation and project discovery helpers."""

import inspect
import json
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CliCapabilities:
    """Cached CLI capability summary."""

    version: str | None
    gerber_command: str = "gerber"
    drill_command: str = "drill"
    position_command: str = "pos"
    supports_ipc2581: bool = False
    supports_svg: bool = False
    supports_dxf: bool = False
    supports_step: bool = False
    supports_render: bool = False
    supports_spice_netlist: bool = False


def _candidate_cli_paths() -> list[Path]:
    system = platform.system()
    if system == "Windows":
        return [
            Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"),
            Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli"),
            Path(r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"),
            Path(r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe"),
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


def _discover_via_kipy() -> Path | None:
    try:
        from kipy.kicad import KiCad
    except Exception:
        return None

    kicad = None
    try:
        if "headless" in inspect.signature(KiCad.__init__).parameters:
            kicad = cast(Any, KiCad)(headless=True, timeout_ms=1000)
        else:
            kicad = KiCad(timeout_ms=1000)
        cli = Path(kicad.get_kicad_binary_path("kicad-cli"))
        return cli if cli.exists() else None
    except Exception:
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

    return _candidate_cli_paths()[0]


def find_kicad_version(cli_path: Path) -> str | None:
    """Return the KiCad CLI version string."""
    try:
        result = subprocess.run(
            [str(cli_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError, PermissionError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr).strip()
    return text or None


@lru_cache(maxsize=16)
def get_cli_capabilities(cli_path: Path) -> CliCapabilities:
    """Inspect the local CLI and cache supported commands."""
    version = find_kicad_version(cli_path)
    if not cli_path.exists():
        return CliCapabilities(version=version)

    help_outputs: list[str] = []
    commands = (
        [str(cli_path), "pcb", "export", "--help"],
        [str(cli_path), "sch", "export", "--help"],
        [str(cli_path), "pcb", "--help"],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, OSError, PermissionError, subprocess.TimeoutExpired):
            continue
        help_outputs.append(f"{result.stdout}\n{result.stderr}")

    blob = "\n".join(help_outputs).lower()
    tokens = set(re.findall(r"[a-z0-9_-]+", blob))
    gerber_command = "gerbers" if "gerbers" in tokens and "gerber" not in tokens else "gerber"
    position_command = "positions" if "positions" in tokens else "pos"

    return CliCapabilities(
        version=version,
        gerber_command=gerber_command,
        position_command=position_command,
        supports_ipc2581="ipc2581" in blob,
        supports_svg=" export svg" in blob or " svg " in blob,
        supports_dxf=" export dxf" in blob or " dxf " in blob,
        supports_step=" export step" in blob or " step " in blob,
        supports_render=" render " in blob,
        supports_spice_netlist="spice" in blob,
    )


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

    system = platform.system()
    if system == "Windows":
        candidates.extend(
            [
                Path(r"C:\Program Files\KiCad\10.0\share\kicad"),
                Path(r"C:\Program Files\KiCad\9.0\share\kicad"),
                Path(r"C:\Program Files\KiCad\8.0\share\kicad"),
            ]
        )
    elif system == "Darwin":
        candidates.extend(
            [
                Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport"),
                Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/share/kicad"),
            ]
        )
    else:
        candidates.extend([Path("/usr/share/kicad"), Path("/usr/local/share/kicad")])

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
            Path.home() / "AppData" / "Roaming" / "kicad" / "10.0",
            Path.home() / "AppData" / "Roaming" / "kicad" / "9.0",
        ]
    elif system == "Darwin":
        config_dirs = [Path.home() / "Library" / "Preferences" / "kicad" / "10.0"]
    else:
        config_dirs = [
            Path.home() / ".config" / "kicad" / "10.0",
            Path.home() / ".config" / "kicad" / "9.0",
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
        matches = sorted(directory.glob(f"*{extension}"))
        if matches:
            result[key] = matches[0]
    return result
