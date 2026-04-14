"""Project setup and discovery tools."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import __version__
from ..config import get_config
from ..connection import KiCadConnectionError, get_kicad, reset_connection
from ..discovery import find_kicad_version, find_recent_projects, scan_project_dir
from .metadata import headless_compatible
from .router import TOOL_CATEGORIES, available_profiles

logger = structlog.get_logger(__name__)


class ScanDirectoryInput(BaseModel):
    """Directory scan parameters."""

    path: str = Field(min_length=1, max_length=1000)


class CreateProjectInput(BaseModel):
    """New project creation parameters."""

    path: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=120)


class DecouplingPairIntent(BaseModel):
    """Intent describing which capacitors should stay close to an IC."""

    ic_ref: str = Field(min_length=1, max_length=50)
    cap_refs: list[str] = Field(min_length=1, max_length=20)
    max_distance_mm: float = Field(default=3.0, gt=0.0, le=50.0)


class RFKeepoutIntent(BaseModel):
    """Intent describing an RF-sensitive keepout area."""

    name: str = Field(default="RF Keepout", min_length=1, max_length=100)
    x_mm: float
    y_mm: float
    w_mm: float = Field(gt=0.0, le=5000.0)
    h_mm: float = Field(gt=0.0, le=5000.0)


class ProjectDesignIntent(BaseModel):
    """Persisted high-level design intent used by validation and workflow tools."""

    connector_refs: list[str] = Field(default_factory=list)
    decoupling_pairs: list[DecouplingPairIntent] = Field(default_factory=list)
    critical_nets: list[str] = Field(default_factory=list)
    power_tree_refs: list[str] = Field(default_factory=list)
    analog_refs: list[str] = Field(default_factory=list)
    digital_refs: list[str] = Field(default_factory=list)
    sensor_cluster_refs: list[str] = Field(default_factory=list)
    rf_keepout_regions: list[RFKeepoutIntent] = Field(default_factory=list)
    manufacturer: str = Field(default="")
    manufacturer_tier: str = Field(default="")


def _render_project_info() -> str:
    cfg = get_config()
    cli_status = "found" if cfg.kicad_cli.exists() else "missing"
    return "\n".join(
        [
            "Current project configuration:",
            f"- Project directory: {cfg.project_dir or '(not set)'}",
            f"- Project file: {cfg.project_file or '(not set)'}",
            f"- PCB file: {cfg.pcb_file or '(not set)'}",
            f"- Schematic file: {cfg.sch_file or '(not set)'}",
            f"- Output directory: {cfg.output_dir or '(not set)'}",
            f"- KiCad CLI: {cfg.kicad_cli} ({cli_status})",
            f"- Server profile: {cfg.profile}",
            f"- Experimental tools: {cfg.enable_experimental_tools}",
        ]
    )


def _new_project_files(project_dir: Path, name: str) -> tuple[Path, Path, Path]:
    project_file = project_dir / f"{name}.kicad_pro"
    pcb_file = project_dir / f"{name}.kicad_pcb"
    sch_file = project_dir / f"{name}.kicad_sch"
    return project_file, pcb_file, sch_file


def _design_intent_path() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(
            "No project is configured. "
            "Call kicad_set_project() or kicad_create_new_project() first."
        )
    return cfg.ensure_output_dir() / "design_intent.json"


def _normalized_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def _normalize_design_intent(intent: ProjectDesignIntent) -> ProjectDesignIntent:
    return ProjectDesignIntent.model_validate(
        {
            "connector_refs": _normalized_unique(intent.connector_refs),
            "decoupling_pairs": [
                {
                    "ic_ref": pair.ic_ref.strip(),
                    "cap_refs": _normalized_unique(pair.cap_refs),
                    "max_distance_mm": pair.max_distance_mm,
                }
                for pair in intent.decoupling_pairs
            ],
            "critical_nets": _normalized_unique(intent.critical_nets),
            "power_tree_refs": _normalized_unique(intent.power_tree_refs),
            "analog_refs": _normalized_unique(intent.analog_refs),
            "digital_refs": _normalized_unique(intent.digital_refs),
            "sensor_cluster_refs": _normalized_unique(intent.sensor_cluster_refs),
            "rf_keepout_regions": [region.model_dump() for region in intent.rf_keepout_regions],
            "manufacturer": intent.manufacturer.strip(),
            "manufacturer_tier": intent.manufacturer_tier.strip(),
        }
    )


def load_design_intent() -> ProjectDesignIntent:
    """Load the persisted project design intent, or return defaults if none exists."""
    path = _design_intent_path()
    if not path.exists():
        return ProjectDesignIntent()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("design_intent_load_failed", path=str(path), error=str(exc))
        return ProjectDesignIntent()
    return _normalize_design_intent(ProjectDesignIntent.model_validate(payload))


def save_design_intent(intent: ProjectDesignIntent) -> Path:
    """Persist the normalized project design intent to the output directory."""
    path = _design_intent_path()
    normalized = _normalize_design_intent(intent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized.model_dump(), indent=2), encoding="utf-8")
    return path


def _render_design_intent(intent: ProjectDesignIntent) -> str:
    lines = ["Project design intent:"]
    lines.append(
        "- Connector refs: "
        + (", ".join(intent.connector_refs) if intent.connector_refs else "(none)")
    )
    lines.append(
        "- Critical nets: "
        + (", ".join(intent.critical_nets) if intent.critical_nets else "(none)")
    )
    lines.append(
        "- Power-tree refs: "
        + (", ".join(intent.power_tree_refs) if intent.power_tree_refs else "(none)")
    )
    lines.append(
        "- Analog refs: " + (", ".join(intent.analog_refs) if intent.analog_refs else "(none)")
    )
    lines.append(
        "- Digital refs: "
        + (", ".join(intent.digital_refs) if intent.digital_refs else "(none)")
    )
    lines.append(
        "- Sensor cluster refs: "
        + (
            ", ".join(intent.sensor_cluster_refs)
            if intent.sensor_cluster_refs
            else "(none)"
        )
    )
    lines.append(
        "- Manufacturer: "
        + (
            f"{intent.manufacturer} / {intent.manufacturer_tier}"
            if intent.manufacturer or intent.manufacturer_tier
            else "(none)"
        )
    )
    lines.append(f"- Decoupling pairs: {len(intent.decoupling_pairs)}")
    for pair in intent.decoupling_pairs[:10]:
        lines.append(
            f"  {pair.ic_ref} <- {', '.join(pair.cap_refs)} "
            f"(max {pair.max_distance_mm:.2f} mm)"
        )
    lines.append(f"- RF keepout regions: {len(intent.rf_keepout_regions)}")
    for region in intent.rf_keepout_regions[:10]:
        lines.append(
            f"  {region.name}: center=({region.x_mm:.2f}, {region.y_mm:.2f}) "
            f"size=({region.w_mm:.2f} x {region.h_mm:.2f}) mm"
        )
    return "\n".join(lines)


def register(mcp: FastMCP) -> None:
    """Register project management tools."""

    @mcp.tool()
    @headless_compatible
    def kicad_set_project(
        project_dir: str,
        pcb_file: str = "",
        sch_file: str = "",
        output_dir: str = "",
    ) -> str:
        """Set the active KiCad project directory and file paths."""
        cfg = get_config()
        project_path = Path(project_dir).expanduser().resolve()
        if not project_path.exists() or not project_path.is_dir():
            return "Project directory does not exist or is not a directory."

        scan = scan_project_dir(project_path)
        selected_pcb = Path(pcb_file).expanduser().resolve() if pcb_file else scan.get("pcb")
        selected_sch = Path(sch_file).expanduser().resolve() if sch_file else scan.get("schematic")
        selected_project = scan.get("project")
        selected_output = (
            Path(output_dir).expanduser().resolve() if output_dir else project_path / "output"
        )

        cfg.apply_project(
            project_path,
            project_file=selected_project,
            pcb_file=selected_pcb,
            sch_file=selected_sch,
            output_dir=selected_output,
        )
        reset_connection()
        return _render_project_info()

    @mcp.tool()
    @headless_compatible
    def kicad_get_project_info() -> str:
        """Show the currently configured KiCad project paths."""
        return _render_project_info()

    @mcp.tool()
    @headless_compatible
    def project_set_design_intent(
        connector_refs: list[str] | None = None,
        decoupling_pairs: list[dict[str, Any]] | None = None,
        critical_nets: list[str] | None = None,
        power_tree_refs: list[str] | None = None,
        analog_refs: list[str] | None = None,
        digital_refs: list[str] | None = None,
        sensor_cluster_refs: list[str] | None = None,
        rf_keepout_regions: list[dict[str, Any]] | None = None,
        manufacturer: str = "",
        manufacturer_tier: str = "",
    ) -> str:
        """Store minimal design intent used by placement and release-quality gates."""
        existing = load_design_intent()
        updated = ProjectDesignIntent(
            connector_refs=existing.connector_refs if connector_refs is None else connector_refs,
            decoupling_pairs=(
                existing.decoupling_pairs if decoupling_pairs is None else decoupling_pairs
            ),
            critical_nets=existing.critical_nets if critical_nets is None else critical_nets,
            power_tree_refs=(
                existing.power_tree_refs if power_tree_refs is None else power_tree_refs
            ),
            analog_refs=existing.analog_refs if analog_refs is None else analog_refs,
            digital_refs=existing.digital_refs if digital_refs is None else digital_refs,
            sensor_cluster_refs=(
                existing.sensor_cluster_refs
                if sensor_cluster_refs is None
                else sensor_cluster_refs
            ),
            rf_keepout_regions=(
                existing.rf_keepout_regions
                if rf_keepout_regions is None
                else rf_keepout_regions
            ),
            manufacturer=existing.manufacturer if not manufacturer else manufacturer,
            manufacturer_tier=(
                existing.manufacturer_tier if not manufacturer_tier else manufacturer_tier
            ),
        )
        path = save_design_intent(updated)
        return (
            f"Stored project design intent at {path}.\n"
            f"{_render_design_intent(_normalize_design_intent(updated))}"
        )

    @mcp.tool()
    @headless_compatible
    def project_get_design_intent() -> str:
        """Show the persisted project design intent used by placement and release gates."""
        intent = load_design_intent()
        if intent == ProjectDesignIntent():
            return (
                "No explicit project design intent is stored yet.\n"
                f"{_render_design_intent(intent)}"
            )
        return _render_design_intent(intent)

    @mcp.tool()
    @headless_compatible
    def kicad_list_recent_projects() -> str:
        """List recently opened KiCad projects from KiCad's config files."""
        projects = find_recent_projects()
        if not projects:
            return "No recent KiCad projects were found on this machine."

        lines = [f"Found {len(projects)} recent project(s):"]
        for index, project in enumerate(projects, start=1):
            lines.append(f"{index}. {project}")
        lines.append("")
        lines.append("Call `kicad_set_project()` with one of these paths to activate it.")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def kicad_scan_directory(path: str) -> str:
        """Scan a directory and report any KiCad project files it contains."""
        payload = ScanDirectoryInput(path=path)
        directory = Path(payload.path).expanduser().resolve()
        if not directory.exists() or not directory.is_dir():
            return "The supplied path is not a directory."

        scan = scan_project_dir(directory)
        lines = [f"Scan results for {directory}:"]
        lines.append(f"- Project file: {scan['project'] or '(none)'}")
        lines.append(f"- PCB file: {scan['pcb'] or '(none)'}")
        lines.append(f"- Schematic file: {scan['schematic'] or '(none)'}")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def kicad_create_new_project(path: str, name: str) -> str:
        """Create a new minimal KiCad project structure and activate it."""
        payload = CreateProjectInput(path=path, name=name)
        project_dir = Path(payload.path).expanduser().resolve() / payload.name
        project_dir.mkdir(parents=True, exist_ok=True)

        project_file, pcb_file, sch_file = _new_project_files(project_dir, payload.name)
        project_file.write_text(
            json.dumps(
                {
                    "board": {"design_settings": {}},
                    "meta": {"filename": project_file.name, "version": 1},
                    "schematic": {"legacy_lib_dir": "", "page_layout_descr_file": ""},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        pcb_file.write_text(
            '(kicad_pcb (version 20250316) (generator "kicad-mcp-pro"))\n',
            encoding="utf-8",
        )
        sch_file.write_text(
            (
                "(kicad_sch\n"
                "\t(version 20250316)\n"
                '\t(generator "kicad-mcp-pro")\n'
                f'\t(uuid "{uuid.uuid4()}")\n'
                '\t(paper "A4")\n'
                "\t(lib_symbols)\n"
                '\t(sheet_instances (path "/" (page "1")))\n'
                "\t(embedded_fonts no)\n"
                ")\n"
            ),
            encoding="utf-8",
        )

        cfg = get_config()
        cfg.apply_project(
            project_dir,
            project_file=project_file,
            pcb_file=pcb_file,
            sch_file=sch_file,
            output_dir=project_dir / "output",
        )
        reset_connection()
        return "\n".join(
            [
                f"Created project '{payload.name}' at {project_dir}.",
                f"- Project file: {project_file}",
                f"- PCB file: {pcb_file}",
                f"- Schematic file: {sch_file}",
            ]
        )

    @mcp.tool()
    @headless_compatible
    def kicad_get_version() -> str:
        """Get KiCad version information and current connection status."""
        cfg = get_config()
        lines = [f"# KiCad MCP Pro Server v{__version__}", f"CLI path: {cfg.kicad_cli}"]

        cli_version = find_kicad_version(cfg.kicad_cli)
        lines.append(f"CLI version: {cli_version or 'unavailable'}")

        try:
            from kipy.proto.common.types.base_types_pb2 import DocumentType

            kicad = get_kicad()
            lines.append(f"IPC version: {kicad.get_version()}")
            pcb_docs = kicad.get_open_documents(DocumentType.DOCTYPE_PCB)
            sch_docs = kicad.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)
            lines.append(f"Open PCB documents: {len(pcb_docs)}")
            lines.append(f"Open schematic documents: {len(sch_docs)}")
        except KiCadConnectionError as exc:
            lines.append(f"IPC connection: unavailable ({exc})")
        except Exception as exc:
            logger.debug("kicad_version_ipc_probe_failed", error=str(exc))
            lines.append("IPC connection: unavailable")

        lines.append("")
        lines.append("Use `kicad_set_project()` to configure an active project.")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def kicad_help() -> str:
        """Show a concise startup guide and all tool categories."""
        lines = [
            "# KiCad MCP Pro Quick Start",
            "",
            "1. Call `kicad_get_version()` to verify the runtime.",
            "2. Call `kicad_set_project()` or `kicad_create_new_project()`.",
            "3. Inspect `kicad://project/info` and `kicad://board/summary`.",
            "4. Call `kicad_list_tool_categories()` to discover the right tool family.",
            "",
            "Available categories:",
        ]
        for category, info in TOOL_CATEGORIES.items():
            lines.append(f"- `{category}`: {info['description']}")
        lines.append("")
        lines.append("Profiles:")
        lines.extend(f"- `{profile}`" for profile in available_profiles())
        return "\n".join(lines)
