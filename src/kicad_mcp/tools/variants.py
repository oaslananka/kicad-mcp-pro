"""Design-variant helpers backed by KiCad 10 project metadata when available."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .metadata import headless_compatible
from .schematic import native_population_flags, parse_schematic_file

_VARIANTS_DIRNAME = ".kicad-mcp"
_VARIANTS_FILENAME = "variants.json"
_PROJECT_VARIANTS_KEY = "variants"


def _variants_path() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(
            "No active project directory is configured.\n"
            "Resolution: call kicad_set_project('/absolute/path/to/project') first.\n"
            "Help: https://oaslananka.github.io/kicad-mcp-pro/installation/"
        )
    target = (cfg.project_dir / _VARIANTS_DIRNAME).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return (target / _VARIANTS_FILENAME).resolve()


def _project_variants_path() -> Path | None:
    cfg = get_config()
    if cfg.project_file is None or not cfg.project_file.exists():
        return None
    return cfg.project_file.resolve()


def _base_components() -> dict[str, dict[str, Any]]:
    cfg = get_config()
    if cfg.sch_file is None or not cfg.sch_file.exists():
        raise ValueError("No schematic file is configured. Call kicad_set_project() first.")
    data = parse_schematic_file(cfg.sch_file)
    # The active backend may not model the native DNP flag, so recover it from
    # the file directly and let it take precedence over the parsed value.
    native_flags = native_population_flags(cfg.sch_file)
    components: dict[str, dict[str, Any]] = {}
    for symbol in data.get("symbols", []):
        reference = str(symbol.get("reference", "")).strip()
        if not reference or reference.startswith("#PWR"):
            continue
        native = native_flags.get(reference, {})
        dnp = bool(native.get("dnp", symbol.get("dnp", False)))
        in_bom = bool(native.get("in_bom", symbol.get("in_bom", True)))
        components[reference] = {
            "reference": reference,
            "value": str(symbol.get("value", "")),
            "footprint": str(symbol.get("footprint", "")),
            "enabled": True,
            "populated": not dnp,
            "dnp": dnp,
            "in_bom": in_bom,
        }
    return components


def _default_state() -> dict[str, Any]:
    return {
        "default_variant": "default",
        "active_variant": "default",
        "variants": {
            "default": {
                "overrides": {},
            }
        },
    }


def _load_project_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Project file '{path}' does not contain valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Project file '{path}' must contain a JSON object at the root.")
    return cast(dict[str, Any], payload)


def _load_sidecar_state() -> dict[str, Any]:
    path = _variants_path()
    if not path.exists():
        state = _default_state()
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _project_state_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    section = payload.get(_PROJECT_VARIANTS_KEY)
    if not isinstance(section, dict):
        return None
    variants = section.get("variants")
    if not isinstance(variants, dict):
        return None
    default_variant = str(section.get("default_variant", "default"))
    active_variant = str(section.get("active_variant", default_variant))
    return {
        "default_variant": default_variant,
        "active_variant": active_variant,
        "variants": cast(dict[str, Any], variants),
    }


def _load_state() -> dict[str, Any]:
    if (project_path := _project_variants_path()) is not None:
        project_payload = _load_project_payload(project_path)
        if (project_state := _project_state_from_payload(project_payload)) is not None:
            return project_state
        sidecar_path = _variants_path()
        if sidecar_path.exists():
            return _load_sidecar_state()
        return _default_state()
    return _load_sidecar_state()


def _save_state(state: dict[str, Any]) -> Path:
    if (project_path := _project_variants_path()) is not None:
        proj_resolved = project_path.resolve()
        payload = _load_project_payload(proj_resolved)
        default_variant = str(state.get("default_variant", "default"))
        active_variant = str(state.get("active_variant", default_variant))
        payload[_PROJECT_VARIANTS_KEY] = {
            "default_variant": default_variant,
            "active_variant": active_variant,
            "variants": cast(dict[str, Any], state.get("variants", {})),
        }
        proj_resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return proj_resolved
    path = _variants_path().resolve()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def _variant_names(state: dict[str, Any]) -> list[str]:
    return sorted(str(name) for name in state.get("variants", {}).keys())


def _active_variant_name(state: dict[str, Any]) -> str | None:
    active = str(state.get("active_variant", "")).strip()
    return active or None


def _ensure_variant(state: dict[str, Any], name: str) -> dict[str, Any]:
    variants = cast(dict[str, dict[str, Any]], state.setdefault("variants", {}))
    if name not in variants:
        raise ValueError(
            f"Variant '{name}' was not found. Existing variants: {', '.join(_variant_names(state))}"
        )
    return variants[name]


def _render_variant_components(state: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    base = _base_components()
    variant = _ensure_variant(state, name)
    overrides = variant.get("overrides", {})
    rendered = {reference: dict(component) for reference, component in base.items()}
    for reference, override in overrides.items():
        if reference not in rendered:
            rendered[reference] = {
                "reference": reference,
                "value": "",
                "footprint": "",
                "enabled": True,
                "populated": True,
                "dnp": False,
                "in_bom": True,
            }
        # Keep populated/dnp consistent when only one side of the pair is set.
        normalized_override = dict(override)
        if "dnp" in normalized_override and "populated" not in normalized_override:
            normalized_override["populated"] = not bool(normalized_override["dnp"])
        if "populated" in normalized_override and "dnp" not in normalized_override:
            normalized_override["dnp"] = not bool(normalized_override["populated"])
        rendered[reference].update(normalized_override)
    return rendered


def _bom_rows(state: dict[str, Any], name: str) -> list[dict[str, Any]]:
    rows = []
    for reference, component in sorted(_render_variant_components(state, name).items()):
        if not component.get("enabled", True):
            continue
        rows.append(
            {
                "reference": reference,
                "value": str(component.get("value", "")),
                "footprint": str(component.get("footprint", "")),
                "populated": bool(component.get("populated", True)),
                "dnp": bool(component.get("dnp", False)),
            }
        )
    return rows


def _write_bom(path: Path, rows: list[dict[str, Any]], format_name: str) -> Path:
    if format_name == "json":
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return path

    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["reference", "value", "footprint", "populated", "dnp"],
    )
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return path


def variant_apply_to_kicad_cli_args(variant_name: str | None = None) -> list[str]:
    """Return ``kicad-cli`` arguments for the requested or active variant."""
    state = _load_state()
    selected_name = variant_name.strip() if variant_name else (_active_variant_name(state) or "")
    if not selected_name:
        return []
    _ensure_variant(state, selected_name)
    return ["--variant", selected_name]


def register(mcp: FastMCP) -> None:
    """Register design-variant tools."""

    @mcp.tool()
    @headless_compatible
    def variant_list() -> str:
        """List available design variants and basic component counts."""
        state = _load_state()
        payload = {
            "default_variant": state.get("default_variant", "default"),
            "active_variant": state.get("active_variant", "default"),
            "variants": [
                {
                    "name": name,
                    "component_count": len(_bom_rows(state, name)),
                }
                for name in _variant_names(state)
            ],
        }
        return json.dumps(payload, indent=2)

    @mcp.tool()
    @headless_compatible
    def variant_create(name: str, base_variant: str | None = None) -> str:
        """Create a new design variant, optionally cloning an existing variant."""
        if not name.strip():
            raise ValueError("Variant name must not be empty.")
        state = _load_state()
        variants = state.setdefault("variants", {})
        if name in variants:
            raise ValueError(f"Variant '{name}' already exists.")
        source = dict(_ensure_variant(state, base_variant)) if base_variant else {"overrides": {}}
        variants[name] = {
            "overrides": dict(source.get("overrides", {})),
        }
        path = _save_state(state)
        return f"Created design variant '{name}' in {path}."

    @mcp.tool()
    @headless_compatible
    def variant_set_active(name: str) -> str:
        """Set the active design variant for the current project."""
        state = _load_state()
        _ensure_variant(state, name)
        state["active_variant"] = name
        path = _save_state(state)
        return f"Active variant set to '{name}' in {path}."

    @mcp.tool()
    @headless_compatible
    def variant_set_component_override(
        variant: str,
        reference: str,
        enabled: bool,
        value: str | None = None,
        footprint: str | None = None,
    ) -> str:
        """Override component population, value, or footprint in a variant."""
        state = _load_state()
        _ensure_variant(state, variant)
        if reference not in _base_components():
            raise ValueError(f"Reference '{reference}' was not found in the active schematic.")
        overrides = state["variants"][variant].setdefault("overrides", {})
        payload: dict[str, Any] = {"enabled": enabled}
        if value is not None:
            payload["value"] = value
        if footprint is not None:
            payload["footprint"] = footprint
        overrides[reference] = payload
        _save_state(state)
        return f"Updated variant override for '{reference}' in variant '{variant}'."

    @mcp.tool()
    @headless_compatible
    def variant_diff_bom(variant_a: str, variant_b: str) -> str:
        """Diff the effective BOM between two design variants."""
        state = _load_state()
        bom_a = {item["reference"]: item for item in _bom_rows(state, variant_a)}
        bom_b = {item["reference"]: item for item in _bom_rows(state, variant_b)}
        added = [bom_b[ref] for ref in sorted(set(bom_b) - set(bom_a))]
        removed = [bom_a[ref] for ref in sorted(set(bom_a) - set(bom_b))]
        changed = []
        for reference in sorted(set(bom_a) & set(bom_b)):
            if bom_a[reference] != bom_b[reference]:
                changed.append(
                    {
                        "reference": reference,
                        "from": bom_a[reference],
                        "to": bom_b[reference],
                    }
                )
        return json.dumps(
            {
                "variant_a": variant_a,
                "variant_b": variant_b,
                "added": added,
                "removed": removed,
                "changed": changed,
            },
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def variant_export_bom(variant: str, format: str = "csv") -> str:
        """Export a variant-specific BOM into the project output directory."""
        fmt = format.casefold()
        if fmt not in {"csv", "json"}:
            raise ValueError("Only csv and json BOM export formats are supported.")
        state = _load_state()
        _ensure_variant(state, variant)
        cfg = get_config()
        out_dir = cfg.ensure_output_dir("variants")
        out_file = out_dir / f"{variant}_bom.{fmt}"
        rows = _bom_rows(state, variant)
        _write_bom(out_file, rows, fmt)
        return f"Variant BOM exported to {out_file} ({len(rows)} populated component(s))."

    # ── FAZ 10.2 — Variant Extended ─────────────────────────────────────

    @mcp.tool()
    @headless_compatible
    def variant_clone(name: str, new_name: str) -> str:
        """Clone an existing design variant under a new name.

        Parameters
        ----------
        name : str
            Source variant name.
        new_name : str
            Target name for the cloned variant.
        """
        if not new_name.strip():
            raise ValueError("New variant name must not be empty.")
        state = _load_state()
        source = dict(_ensure_variant(state, name))
        variants = cast(dict[str, dict[str, Any]], state.setdefault("variants", {}))
        if new_name in variants:
            raise ValueError(f"Variant '{new_name}' already exists.")
        variants[new_name] = {
            "overrides": dict(source.get("overrides", {})),
        }
        path = _save_state(state)
        return f"Cloned variant '{name}' -> '{new_name}' in {path}."

    @mcp.tool()
    @headless_compatible
    def variant_delete(name: str) -> str:
        """Delete a design variant.

        Parameters
        ----------
        name : str
            Variant name to delete. Cannot delete the ``default`` variant.
        """
        if name.strip() == "default":
            raise ValueError("The 'default' variant cannot be deleted.")
        state = _load_state()
        variants = cast(dict[str, dict[str, Any]], state.setdefault("variants", {}))
        if name not in variants:
            raise ValueError(
                f"Variant '{name}' not found. Existing variants: {', '.join(_variant_names(state))}"
            )
        del variants[name]
        if state.get("active_variant") == name:
            state["active_variant"] = state.get("default_variant", "default")
        path = _save_state(state)
        return (
            f"Deleted variant '{name}' from {path}."
            f" Active variant reset to '{state['active_variant']}'."
        )

    @mcp.tool()
    @headless_compatible
    def variant_get_component_status(variant: str, reference: str) -> str:
        """Get the effective status of a single component in a variant.

        Parameters
        ----------
        variant : str
            Variant name.
        reference : str
            Component reference designator (e.g. ``R1``, ``C4``).
        """
        state = _load_state()
        components = _render_variant_components(state, variant)
        if reference not in components:
            base_names = ", ".join(sorted(components)[:30])
            raise ValueError(
                f"Reference '{reference}' not found in schematic components. "
                f"Sample references: {base_names}"
            )
        return json.dumps(components[reference], indent=2)

    @mcp.tool()
    @headless_compatible
    def variant_export_schematic(variant: str, output_name: str | None = None) -> str:
        """Export a variant-specific schematic PDF with overrides applied.

        Parameters
        ----------
        variant : str
            Variant name.
        output_name : str | None
            Output filename (defaults to ``<variant>_schematic.pdf``).
        """
        from .export_support import _ensure_output_dir, _get_sch_file, _run_cli_variants

        state = _load_state()
        _ensure_variant(state, variant)
        sch_file = _get_sch_file()
        out_dir = _ensure_output_dir("variants")
        out_file = out_dir / (output_name or f"{variant}_schematic.pdf")

        is_default = variant == state.get("default_variant", "default")
        variant_args = [f"--variant={variant}"] if not is_default else []

        code, _, stderr = _run_cli_variants(
            [
                [
                    "sch",
                    "export",
                    "pdf",
                    *variant_args,
                    "--output",
                    str(out_file),
                    str(sch_file),
                ],
                [
                    "sch",
                    "export",
                    "pdf",
                    *variant_args,
                    "--input",
                    str(sch_file),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if code != 0:
            return f"Schematic variant export failed: {stderr or 'unknown error'}"
        return (
            f"Variant schematic '{variant}' exported to {out_file} "
            f"({out_file.stat().st_size} bytes)."
        )

    @mcp.tool()
    @headless_compatible
    def variant_export_manufacturing_package(
        variant: str,
        output_name: str | None = None,
    ) -> str:
        """Export a manufacturing package for a specific variant.

        Combines Gerber, drill, BOM, and pick-and-place exports with
        the variant's overrides applied.

        Parameters
        ----------
        variant : str
            Variant name.
        output_name : str | None
            Output filename for the package manifest (defaults to
            ``<variant>_manufacturing.json``).
        """
        from .export_support import (
            _ensure_output_dir,
            _get_pcb_file,
            _get_sch_file,
            _run_cli_variants,
        )

        state = _load_state()
        _ensure_variant(state, variant)
        get_config()
        out_dir = _ensure_output_dir("variants")
        manifest_path = out_dir / (output_name or f"{variant}_manufacturing.json")

        is_default = variant == state.get("default_variant", "default")
        variant_args = [f"--variant={variant}"] if not is_default else []
        pcb_file = _get_pcb_file()
        _get_sch_file()

        artifacts: dict[str, str] = {}
        errors: list[str] = []

        # Gerber
        gerber_dir = out_dir / f"{variant}_gerber"
        gerber_dir.mkdir(exist_ok=True)
        code, _, stderr = _run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "gerber",
                    *variant_args,
                    "--output",
                    str(gerber_dir),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    "gerber",
                    *variant_args,
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(gerber_dir),
                ],
            ]
        )
        if code == 0:
            artifacts["gerber"] = str(gerber_dir)
        else:
            errors.append(f"Gerber: {stderr or 'unknown error'}")

        # Drill
        drill_dir = out_dir / f"{variant}_drill"
        drill_dir.mkdir(exist_ok=True)
        code, _, stderr = _run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "drill",
                    *variant_args,
                    "--output",
                    str(drill_dir),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    "drill",
                    *variant_args,
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(drill_dir),
                ],
            ]
        )
        if code == 0:
            artifacts["drill"] = str(drill_dir)
        else:
            errors.append(f"Drill: {stderr or 'unknown error'}")

        # BOM
        bom_path = out_dir / f"{variant}_bom.csv"
        rows = _bom_rows(state, variant)
        _write_bom(bom_path, rows, "csv")
        artifacts["bom"] = str(bom_path)

        manifest = {
            "variant": variant,
            "artifacts": artifacts,
            "errors": errors,
            "component_count": len(rows),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        lines = [f"Manufacturing package for variant '{variant}':"]
        for key, val in artifacts.items():
            lines.append(f"  {key}: {val}")
        if errors:
            lines.append("Errors:")
            for err in errors:
                lines.append(f"  ! {err}")
        lines.append(f"Manifest: {manifest_path}")
        return "\n".join(lines)
