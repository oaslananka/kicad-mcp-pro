"""3D model management for footprints.

FAZ 7 — lib_set_3d_model_path, lib_remove_3d_model,
         lib_bulk_assign_3d_models, lib_search_3d_models.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..errors import UnsafePathError
from ..path_safety import relative_subpath, resolve_under
from ..utils.sexpr import _extract_block, _sexpr_string, _unescape_sexpr_string
from .metadata import headless_compatible


def _footprint_3d_dir() -> Path:
    """Return the KiCad 3D model search path (footprint-level)."""
    cfg = get_config()
    if cfg.footprint_library_dir is None or not cfg.footprint_library_dir.exists():
        raise FileNotFoundError("No KiCad footprint library directory is configured.")
    return cfg.footprint_library_dir


def _safe_library_component(value: str, *, label: str) -> str:
    candidate = relative_subpath(value)
    if (
        not value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or len(candidate.parts) != 1
    ):
        raise UnsafePathError(
            f"{label} must be a single path component inside the footprint library."
        )
    return candidate.name


def _find_footprint_file(library: str, footprint: str) -> Path | None:
    """Locate a ``.kicad_mod`` or ``.pretty`` footprint file."""
    lib_dir = _footprint_3d_dir()
    library_name = _safe_library_component(library, label="library")
    footprint_name = _safe_library_component(footprint, label="footprint")
    candidates = [
        resolve_under(
            lib_dir,
            Path(library_name) / f"{footprint_name}.kicad_mod",
            allow_absolute=False,
        ),
        resolve_under(
            lib_dir,
            Path(library_name) / f"{footprint_name}.pretty",
            allow_absolute=False,
        ),
        resolve_under(
            lib_dir,
            Path(f"{library_name}.pretty") / f"{footprint_name}.kicad_mod",
            allow_absolute=False,
        ),
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def _read_footprint_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _write_footprint_text(path: Path, text: str) -> None:
    safe_path = resolve_under(_footprint_3d_dir(), path)
    with safe_path.open("w", encoding="utf-8") as handle:
        handle.write(text)


def _validated_xyz(value: str, *, label: str) -> str:
    parts = value.strip().split()
    try:
        valid = len(parts) == 3 and all(math.isfinite(float(part)) for part in parts)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be three space-separated numbers.")
    return " ".join(parts)


def _model_blocks(text: str) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(" and text.startswith("(model", index):
            boundary = index + len("(model")
            if boundary < len(text) and text[boundary].isspace():
                block, consumed = _extract_block(text, index)
                if consumed:
                    blocks.append((index, index + consumed, block))
                    index += consumed
                    continue
        index += 1
    return blocks


def _model_path_from_block(block: str) -> str | None:
    match = re.match(r'^\(model\s+"((?:\\.|[^"\\])*)"', block)
    if match is None:
        return None
    return _unescape_sexpr_string(match.group(1))


def _remove_3d_model_blocks(text: str, *, model_path: str | None = None) -> str:
    for start, end, block in reversed(_model_blocks(text)):
        if model_path is not None and _model_path_from_block(block) != model_path:
            continue
        text = text[:start] + text[end:]
    return text


def _find_3d_model_refs(text: str) -> list[dict[str, object]]:
    """Return list of ``{path, offset_xyz, scale_xyz, rotate_xyz}`` entries."""
    refs: list[dict[str, object]] = []
    for _, _, block in _model_blocks(text):
        model_path = _model_path_from_block(block)
        if model_path is None:
            continue
        match = re.match(r'^\(model\s+"((?:\\.|[^"\\])*)"', block)
        if match is None:
            continue
        inner = block[match.end() : -1]
        ox = _sexpr_float(inner, "offset", "xyz", index=0)
        oy = _sexpr_float(inner, "offset", "xyz", index=1)
        oz = _sexpr_float(inner, "offset", "xyz", index=2)
        sx = _sexpr_float(inner, "scale", "xyz", index=0)
        sy = _sexpr_float(inner, "scale", "xyz", index=1)
        sz = _sexpr_float(inner, "scale", "xyz", index=2)
        rx = _sexpr_float(inner, "rotate", "xyz", index=0)
        ry = _sexpr_float(inner, "rotate", "xyz", index=1)
        rz = _sexpr_float(inner, "rotate", "xyz", index=2)
        refs.append(
            {
                "path": model_path,
                "offset_xyz": [ox, oy, oz],
                "scale_xyz": [sx if sx else 1.0, sy if sy else 1.0, sz if sz else 1.0],
                "rotate_xyz": [rx, ry, rz],
            }
        )
    return refs


def _sexpr_float(sexpr: str, *tags: str, index: int = 0) -> float:
    """Extract a numeric value from a nested S-expression."""
    pattern = (
        r"\(" + r"\s+".join(re.escape(t) for t in tags) + r"\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)"
    )
    m = re.search(pattern, sexpr)
    if m:
        try:
            return float(m.group(index + 1))
        except (ValueError, IndexError):
            pass
    return 0.0


def _search_3d_model_files(query: str) -> list[dict[str, str]]:
    """Walk footprint library dir and find 3D model files matching ``query``."""
    lib_dir = _footprint_3d_dir()
    results: list[dict[str, str]] = []
    query_lower = query.casefold()
    for ext in (
        "*.step",
        "*.stp",
        "*.wrl",
        "*.vrml",
        "*.x3d",
        "*.x3dv",
        "*.3ds",
        "*.iges",
        "*.igs",
    ):
        for model_file in lib_dir.rglob(ext):
            rel = model_file.relative_to(lib_dir)
            if query_lower in str(rel).casefold():
                results.append(
                    {
                        "path": str(rel.as_posix()),
                        "absolute_path": str(model_file),
                        "size_bytes": str(model_file.stat().st_size),
                    }
                )
    return sorted(results, key=lambda r: r["path"])[:100]


def register(mcp: FastMCP) -> None:
    """Register 3D model management tools."""

    @mcp.tool()
    @headless_compatible
    def lib_set_3d_model_path(
        library: str,
        footprint: str,
        model_path: str,
        offset_xyz: str | None = None,
        scale_xyz: str | None = None,
        rotate_xyz: str | None = None,
    ) -> str:
        """Set or replace the 3D model path on a footprint.

        Parameters
        ----------
        library : str
            Library name (e.g. ``Package_SO``).
        footprint : str
            Footprint name (e.g. ``SOIC-8_3.9x4.9mm_P1.27mm``).
        model_path : str
            Absolute or relative 3D model file path (Step, VRML, etc.).
        offset_xyz : str | None
            Optional offset as ``"x y z"`` in mm (e.g. ``"0 5 0"``).
        scale_xyz : str | None
            Optional scale as ``"x y z"`` (e.g. ``"1 1 1"``).
        rotate_xyz : str | None
            Optional rotation as ``"x y z"`` in degrees.
        """
        fp_file = _find_footprint_file(library, footprint)
        if fp_file is None:
            raise ValueError(
                f"Footprint '{library}:{footprint}' not found. "
                "Check the library and footprint name."
            )

        text = _read_footprint_text(fp_file)
        # Build the model S-expression
        attrs = ""
        if offset_xyz:
            attrs += f"\n    (offset (xyz {_validated_xyz(offset_xyz, label='offset_xyz')}))"
        if scale_xyz:
            attrs += f"\n    (scale (xyz {_validated_xyz(scale_xyz, label='scale_xyz')}))"
        if rotate_xyz:
            attrs += f"\n    (rotate (xyz {_validated_xyz(rotate_xyz, label='rotate_xyz')}))"

        new_model = f"(model {_sexpr_string(model_path)}{attrs}\n  )"

        # Remove any existing model reference, then insert new one before closing )
        text = _remove_3d_model_blocks(text)
        # Insert the new model before the final closing parenthesis
        text = text.rstrip()
        if text.endswith(")"):
            text = text[:-1].rstrip() + f"\n  {new_model}\n)"

        _write_footprint_text(fp_file, text)
        return f"3D model set on '{library}:{footprint}' -> {model_path}"

    @mcp.tool()
    @headless_compatible
    def lib_remove_3d_model(
        library: str,
        footprint: str,
        model_path: str | None = None,
    ) -> str:
        """Remove 3D model reference(s) from a footprint.

        Parameters
        ----------
        library : str
            Library name.
        footprint : str
            Footprint name.
        model_path : str | None
            If provided, only remove the model with this exact path.
            If omitted, all 3D model references are removed.
        """
        fp_file = _find_footprint_file(library, footprint)
        if fp_file is None:
            raise ValueError(f"Footprint '{library}:{footprint}' not found.")

        text = _read_footprint_text(fp_file)
        before_count = len(_find_3d_model_refs(text))

        text = _remove_3d_model_blocks(text, model_path=model_path if model_path else None)

        _write_footprint_text(fp_file, text)
        after_count = len(_find_3d_model_refs(text))
        removed = before_count - after_count
        return (
            f"Removed {removed} 3D model(s) from '{library}:{footprint}'. Remaining: {after_count}."
        )

    @mcp.tool()
    @headless_compatible
    def lib_bulk_assign_3d_models(
        library: str,
        footprint_pattern: str,
        model_path: str,
    ) -> str:
        """Bulk-assign a 3D model to multiple footprints matching a pattern.

        Parameters
        ----------
        library : str
            Library name.
        footprint_pattern : str
            Regex pattern to match footprint names (e.g. ``SOIC.*``, ``QFP.*``).
        model_path : str
            3D model file path to assign to all matched footprints.
        """
        lib_dir = _footprint_3d_dir()
        library_name = _safe_library_component(library, label="library")
        lib_candidates = [
            resolve_under(lib_dir, library_name, allow_absolute=False),
            resolve_under(lib_dir, f"{library_name}.pretty", allow_absolute=False),
        ]
        lib_path: Path | None = None
        for cand in lib_candidates:
            if cand.is_dir():
                lib_path = cand
                break
        if lib_path is None:
            raise ValueError(f"Library '{library}' directory not found.")

        compiled = re.compile(footprint_pattern)
        matched = [path for path in lib_path.iterdir() if path.suffix in (".kicad_mod", ".pretty")]
        updated = 0
        for candidate in matched:
            if not compiled.search(candidate.stem):
                continue
            fp_file = resolve_under(lib_dir, candidate)
            text = _read_footprint_text(fp_file)
            # Remove existing models and add new one
            text = _remove_3d_model_blocks(text)
            new_model = f"(model {_sexpr_string(model_path)}\n  )"
            text = text.rstrip()
            if text.endswith(")"):
                text = text[:-1].rstrip() + f"\n  {new_model}\n)"
            _write_footprint_text(fp_file, text)
            updated += 1

        return f"Updated {updated} footprint(s) in library '{library}' with model '{model_path}'."

    @mcp.tool()
    @headless_compatible
    def lib_search_3d_models(query: str) -> str:
        """Search for available 3D model files in the footprint library directory.

        Parameters
        ----------
        query : str
            Search term (case-insensitive, matched against path).
        """
        results = _search_3d_model_files(query)
        if not results:
            return json.dumps({"query": query, "count": 0, "results": []}, indent=2)
        return json.dumps({"query": query, "count": len(results), "results": results}, indent=2)
