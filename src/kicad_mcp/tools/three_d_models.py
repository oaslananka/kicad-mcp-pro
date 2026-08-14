"""3D model management for footprints.

FAZ 7 — lib_set_3d_model_path, lib_remove_3d_model,
         lib_bulk_assign_3d_models, lib_search_3d_models.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .metadata import headless_compatible


def _footprint_3d_dir() -> Path:
    """Return the KiCad 3D model search path (footprint-level)."""
    cfg = get_config()
    if cfg.footprint_library_dir is None or not cfg.footprint_library_dir.exists():
        raise FileNotFoundError("No KiCad footprint library directory is configured.")
    return cfg.footprint_library_dir


def _find_footprint_file(library: str, footprint: str) -> Path | None:
    """Locate a ``.kicad_mod`` or ``.pretty`` footprint file."""
    lib_dir = _footprint_3d_dir()
    # Try library as subdirectory of footprint_library_dir
    candidates = [
        lib_dir / library / f"{footprint}.kicad_mod",
        lib_dir / library / f"{footprint}.pretty",
        lib_dir / f"{library}.pretty" / f"{footprint}.kicad_mod",
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def _read_footprint_text(path: Path) -> str:
    return path.resolve().read_text(encoding="utf-8", errors="ignore")


def _write_footprint_text(path: Path, text: str) -> None:
    resolved = path.resolve()
    resolved.write_text(text, encoding="utf-8")


def _find_3d_model_refs(text: str) -> list[dict[str, object]]:
    """Return list of ``{path, offset_xyz, scale_xyz, rotate_xyz}`` entries."""
    refs: list[dict[str, object]] = []
    for match in re.finditer(
        r'\(model\s+"([^"]+)"\s*(.*?)\)\s*',
        text,
        re.DOTALL,
    ):
        model_path = match.group(1)
        inner = match.group(2)
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
            parts = offset_xyz.strip().split()
            if len(parts) != 3:
                raise ValueError("offset_xyz must be three space-separated numbers.")
            attrs += f"\n    (offset (xyz {parts[0]} {parts[1]} {parts[2]}))"
        if scale_xyz:
            parts = scale_xyz.strip().split()
            if len(parts) != 3:
                raise ValueError("scale_xyz must be three space-separated numbers.")
            attrs += f"\n    (scale (xyz {parts[0]} {parts[1]} {parts[2]}))"
        if rotate_xyz:
            parts = rotate_xyz.strip().split()
            if len(parts) != 3:
                raise ValueError("rotate_xyz must be three space-separated numbers.")
            attrs += f"\n    (rotate (xyz {parts[0]} {parts[1]} {parts[2]}))"

        new_model = f'(model "{model_path}"{attrs}\n  )'

        # Remove any existing model reference, then insert new one before closing )
        text = re.sub(r'\(model\s+"[^"]*".*?\)\s*', "", text, flags=re.DOTALL)
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

        if model_path:
            escaped = re.escape(model_path)
            text = re.sub(
                rf'\(model\s+"{escaped}".*?\)\s*',
                "",
                text,
                flags=re.DOTALL,
            )
        else:
            text = re.sub(r'\(model\s+"[^"]*".*?\)\s*', "", text, flags=re.DOTALL)

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
        # Find the library directory
        lib_candidates = [
            lib_dir / library,
            lib_dir / f"{library}.pretty",
        ]
        lib_path: Path | None = None
        for cand in lib_candidates:
            if cand.is_dir():
                lib_path = cand
                break
        if lib_path is None:
            raise ValueError(f"Library '{library}' directory not found.")

        compiled = re.compile(footprint_pattern)
        matched = [p for p in lib_path.iterdir() if p.suffix in (".kicad_mod", ".pretty")]
        updated = 0
        for fp_file in matched:
            if not compiled.search(fp_file.stem):
                continue
            text = _read_footprint_text(fp_file)
            # Remove existing models and add new one
            text = re.sub(r'\(model\s+"[^"]*".*?\)\s*', "", text, flags=re.DOTALL)
            new_model = f'(model "{model_path}"\n  )'
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
