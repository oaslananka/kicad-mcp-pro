"""KiCad library-table discovery shared by library and PCB workflows."""

from __future__ import annotations

import os
import re
from pathlib import Path


def resolve_kicad_env(uri: str, project_dir: Path | None) -> str:
    """Substitute KiCad table variables without erasing unknown values."""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "KIPRJMOD" and project_dir is not None:
            return str(project_dir)
        return os.environ.get(name, match.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _sub, uri)


def parse_lib_table(path: Path, project_dir: Path | None) -> dict[str, Path]:
    """Parse KiCad table entries into existing, resolved library paths."""
    libraries: dict[str, Path] = {}
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return libraries

    for chunk in re.split(r"\(lib\b", content)[1:]:
        name = re.search(r'\(name\s+"?([^")\s]+)"?\)', chunk)
        type_ = re.search(r'\(type\s+"?([^")\s]+)"?\)', chunk)
        uri = re.search(r'\(uri\s+"([^"]+)"\)', chunk)
        if not (name and uri):
            continue
        if type_ and type_.group(1).lower() != "kicad":
            continue
        resolved = Path(resolve_kicad_env(uri.group(1), project_dir))
        if resolved.exists():
            libraries[name.group(1)] = resolved
    return libraries


def lib_table_paths(table_name: str, project_dir: Path | None) -> list[Path]:
    """Locate project-level and then global KiCad library tables."""
    paths: list[Path] = []
    if project_dir is not None:
        candidate = project_dir / table_name
        if candidate.exists():
            paths.append(candidate)

    config_roots = [
        os.environ.get("APPDATA"),
        os.path.expanduser("~/.config"),
        os.path.expanduser("~/Library/Preferences"),
    ]
    for root in config_roots:
        if not root:
            continue
        kicad_root = Path(root) / "kicad"
        if not kicad_root.is_dir():
            continue
        for version_dir in sorted(kicad_root.glob("*")):
            candidate = version_dir / table_name
            if candidate.exists():
                paths.append(candidate)
    return paths


def footprint_library_dirs(
    *,
    configured_root: Path | None,
    project_dir: Path | None,
) -> dict[str, Path]:
    """Map discoverable footprint nicknames to their ``.pretty`` directories."""
    directories: dict[str, Path] = {}
    if configured_root is not None and configured_root.exists():
        for pretty in sorted(configured_root.glob("*.pretty")):
            directories.setdefault(pretty.stem, pretty)

    for table in lib_table_paths("fp-lib-table", project_dir):
        for nickname, pretty_path in parse_lib_table(table, project_dir).items():
            directories.setdefault(nickname, pretty_path)
    return directories


def resolve_footprint_file(
    library: str,
    footprint: str,
    *,
    configured_root: Path | None,
    project_dir: Path | None,
) -> Path:
    """Resolve one footprint through configured and table-based libraries."""
    pretty_dir = footprint_library_dirs(
        configured_root=configured_root,
        project_dir=project_dir,
    ).get(library)
    if pretty_dir is not None:
        return pretty_dir / f"{footprint}.kicad_mod"

    if configured_root is not None and configured_root.exists():
        return configured_root / f"{library}.pretty" / f"{footprint}.kicad_mod"

    raise FileNotFoundError(
        f"Footprint library '{library}' was not found in configured directories "
        "or KiCad fp-lib-table entries."
    )


__all__ = [
    "footprint_library_dirs",
    "lib_table_paths",
    "parse_lib_table",
    "resolve_footprint_file",
    "resolve_kicad_env",
]
