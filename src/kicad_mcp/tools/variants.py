"""Design-variant helpers backed by KiCad 10 project metadata when available."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..export.inventory import discover_drill_output_files, discover_gerber_output_files
from ..export.manufacturing_package import ManufacturingApprovalService
from ..path_safety import resolve_under
from ..utils.metadata_write import atomic_metadata_write, serialized_metadata_write
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
    return resolve_under(cfg.project_dir, Path(_VARIANTS_DIRNAME) / _VARIANTS_FILENAME)


def _project_variants_path() -> Path | None:
    cfg = get_config()
    if cfg.project_file is None or not cfg.project_file.exists():
        return None
    return cfg.project_file


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


def _write_variant_state(path: Path, state: dict[str, Any]) -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError("No active project directory is configured.")
    safe_path = resolve_under(cfg.project_dir, path)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_metadata_write(safe_path, json.dumps(state, indent=2))
    return safe_path


def _load_sidecar_state() -> dict[str, Any]:
    path = _variants_path()
    if not path.exists():
        return _default_state()
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
        payload = _load_project_payload(project_path)
        default_variant = str(state.get("default_variant", "default"))
        active_variant = str(state.get("active_variant", default_variant))
        payload[_PROJECT_VARIANTS_KEY] = {
            "default_variant": default_variant,
            "active_variant": active_variant,
            "variants": cast(dict[str, Any], state.get("variants", {})),
        }
        return _write_variant_state(project_path, payload)
    path = _variants_path()
    return _write_variant_state(path, state)


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


def _validate_variant_export_names(variant: str, filename: str) -> None:
    for value in (variant, filename):
        if (
            not value
            or value in {".", ".."}
            or any(char in value for char in ("/", "\\", ":", "\x00"))
        ):
            raise ValueError("Variant export names must be single filename components.")


def _safe_variant_export_path(output_dir: Path, variant: str, filename: str) -> Path:
    """Keep variant-generated artifacts within their designated output directory."""
    _validate_variant_export_names(variant, filename)
    return resolve_under(output_dir, filename, allow_absolute=False)


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


@headless_compatible
@serialized_metadata_write
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


@headless_compatible
@serialized_metadata_write
def variant_set_active(name: str) -> str:
    """Set the active design variant for the current project."""
    state = _load_state()
    _ensure_variant(state, name)
    state["active_variant"] = name
    path = _save_state(state)
    return f"Active variant set to '{name}' in {path}."


@headless_compatible
@serialized_metadata_write
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
    out_file = _safe_variant_export_path(out_dir, variant, f"{variant}_bom.{fmt}")
    rows = _bom_rows(state, variant)
    _write_bom(out_file, rows, fmt)
    return f"Variant BOM exported to {out_file} ({len(rows)} populated component(s))."


# ── FAZ 10.2 — Variant Extended ─────────────────────────────────────


@headless_compatible
@serialized_metadata_write
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


@headless_compatible
@serialized_metadata_write
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
    out_file = _safe_variant_export_path(
        out_dir, variant, output_name or f"{variant}_schematic.pdf"
    )

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
        f"Variant schematic '{variant}' exported to {out_file} ({out_file.stat().st_size} bytes)."
    )


def _variant_fabrication_files(directory: Path, kind: str) -> list[Path]:
    candidates = (
        discover_gerber_output_files(directory)
        if kind == "gerber"
        else discover_drill_output_files(directory)
    )
    return [
        path
        for path in candidates
        if path.suffix.lower() != ".gbrjob"
        and not path.is_symlink()
        and path.is_file()
        and path.stat().st_size > 0
    ]


def _export_variant_fabrication(
    stage: Path,
    kind: str,
    pcb_file: Path,
    variant_args: list[str],
    run_cli: Callable[[list[list[str]]], tuple[int, str, str]],
) -> str | None:
    commands = ("gerbers", "gerber") if kind == "gerber" else ("drill",)
    last_error = "No manufacturing files produced."
    for command in commands:
        for explicit_input in (False, True):
            with TemporaryDirectory(prefix=f"{kind}-attempt-", dir=stage.parent) as attempt:
                output = Path(attempt)
                source = ["--input", str(pcb_file)] if explicit_input else []
                trailing = [] if explicit_input else [str(pcb_file)]
                code, _, stderr = run_cli(
                    [
                        [
                            "pcb",
                            "export",
                            command,
                            *variant_args,
                            *source,
                            "--output",
                            str(output),
                            *trailing,
                        ]
                    ]
                )
                if code == 0 and _variant_fabrication_files(output, kind):
                    output.rename(stage)
                    return None
                last_error = stderr or "No nonempty manufacturing files produced."
    return f"{kind.capitalize()} export failed: {last_error}"


@headless_compatible
@serialized_metadata_write
def variant_export_manufacturing_package(
    variant: str,
    output_name: str | None = None,
    approval_evidence_path: str = "",
) -> str:
    """Export a manufacturing package for a specific variant.

    Requires a passing project quality gate and human approval bound to
    the project files before exporting Gerber, drill and variant BOM data.

    Parameters
    ----------
    variant : str
        Variant name.
    output_name : str | None
        Output filename for the package manifest (defaults to
        ``<variant>_manufacturing.json``).
    approval_evidence_path : str
        Project-relative human approval JSON, bound to current project files.
    """
    from .export_support import (
        _ensure_output_dir,
        _get_pcb_file,
        _get_sch_file,
        _run_cli_variants,
    )
    from .validation import _evaluate_project_gate, _render_project_gate_report

    manifest_name = output_name or f"{variant}_manufacturing.json"
    _validate_variant_export_names(variant, manifest_name)
    state = _load_state()
    _ensure_variant(state, variant)
    cfg = get_config()
    approval_service = ManufacturingApprovalService(
        resolve_project_path=lambda path: cfg.resolve_within_project(path, allow_absolute=False)
    )
    outcomes = _evaluate_project_gate()

    def authorize() -> tuple[Path, dict[str, Any]] | str:
        return approval_service.authorize(
            outcomes=outcomes,
            render_gate_report=lambda items, summary: _render_project_gate_report(
                items, summary=summary
            ),
            approval_evidence_path=approval_evidence_path,
        )

    approval = authorize()
    if isinstance(approval, str):
        return approval
    evidence_path, evidence_payload = approval
    state = _load_state()
    _ensure_variant(state, variant)
    out_dir = _ensure_output_dir("variants")
    manifest_path = _safe_variant_export_path(out_dir, variant, manifest_name)

    is_default = variant == state.get("default_variant", "default")
    variant_args = [f"--variant={variant}"] if not is_default else []
    pcb_file = _get_pcb_file()
    _get_sch_file()

    gerber_dir = _safe_variant_export_path(out_dir, variant, f"{variant}_gerber")
    drill_dir = _safe_variant_export_path(out_dir, variant, f"{variant}_drill")
    bom_path = _safe_variant_export_path(out_dir, variant, f"{variant}_bom.csv")
    destinations = (gerber_dir, drill_dir, bom_path, manifest_path)
    if len(set(destinations)) != len(destinations) or any(path.exists() for path in destinations):
        return (
            "Manufacturing package export blocked: existing or conflicting output paths. "
            "Archive the previous package before retrying; no existing artifacts were changed."
        )

    artifacts = {"gerber": str(gerber_dir), "drill": str(drill_dir), "bom": str(bom_path)}
    with TemporaryDirectory(prefix=".variant-package-", dir=out_dir) as temporary:
        stage = Path(temporary)
        for kind, target in (("gerber", gerber_dir), ("drill", drill_dir)):
            error = _export_variant_fabrication(
                stage / target.name, kind, pcb_file, variant_args, _run_cli_variants
            )
            if error is not None:
                return f"Manufacturing package export failed: {error} No manifest published."

        rows = _bom_rows(state, variant)
        _write_bom(stage / bom_path.name, rows, "csv")
        fresh = authorize()
        if isinstance(fresh, str):
            return f"Manufacturing package export failed: {fresh}"
        if fresh != (evidence_path, evidence_payload):
            return "Manufacturing package export failed: approval changed during export."
        if any(path.exists() for path in destinations):
            return "Manufacturing package export blocked: existing output appeared during export."

        manifest = {
            "variant": variant,
            "approval_evidence_path": str(evidence_path),
            "approval_evidence": evidence_payload,
            "artifacts": artifacts,
            "errors": [],
            "component_count": len(rows),
        }
        # Publish the manifest last, only after all required files exist.
        (stage / manifest_path.name).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for path in destinations:
            (stage / path.name).rename(path)

    lines = [f"Manufacturing package for variant '{variant}':"]
    lines.extend(f"  {key}: {val}" for key, val in artifacts.items())
    lines.append(f"Manifest: {manifest_path}")
    return "\n".join(lines)


def register(mcp: FastMCP) -> None:
    """Register design-variant tools."""
    mcp.tool()(variant_list)
    mcp.tool()(variant_create)
    mcp.tool()(variant_set_active)
    mcp.tool()(variant_set_component_override)
    mcp.tool()(variant_diff_bom)
    mcp.tool()(variant_export_bom)
    mcp.tool()(variant_clone)
    mcp.tool()(variant_delete)
    mcp.tool()(variant_get_component_status)
    mcp.tool()(variant_export_schematic)
    mcp.tool()(variant_export_manufacturing_package)
