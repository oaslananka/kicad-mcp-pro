"""Capability registry for KiCad MCP Pro."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AccessTier(StrEnum):
    """Access tier for a registered capability."""

    READ = "read"
    WRITE = "write"
    EXPORT = "export"
    PUBLISH = "publish"
    HUMAN_ONLY = "human_only"


class RuntimeRequirement(StrEnum):
    """External runtime required by a capability."""

    NONE = "none"
    KICAD_CLI = "kicad_cli"
    KICAD_IPC = "kicad_ipc"
    NGSPICE = "ngspice"
    FREEROUTING = "freerouting"
    DOCKER = "docker"


@dataclass(frozen=True)
class CapabilityRecord:
    """Metadata for a single registered tool capability."""

    name: str
    profiles: frozenset[str]
    tier: AccessTier
    runtime: RuntimeRequirement = RuntimeRequirement.NONE
    supports_dry_run: bool = False
    human_gate_required: bool = False
    description: str = ""
    verification_level: str = "experimental"


_REGISTRY: dict[str, CapabilityRecord] = {}


def register(record: CapabilityRecord) -> None:
    """Register or replace a capability record."""
    _REGISTRY[record.name] = record


def get(name: str) -> CapabilityRecord | None:
    """Return a capability record by tool name."""
    return _REGISTRY.get(name)


def all_records() -> dict[str, CapabilityRecord]:
    """Return a copy of all capability records."""
    return dict(_REGISTRY)


def tools_for_profile(profile: str) -> list[CapabilityRecord]:
    """Return all capability records available to a profile."""
    return [record for record in _REGISTRY.values() if profile in record.profiles]


def is_allowed(tool_name: str, profile: str) -> bool:
    """Return whether a tool is allowed for a profile."""
    record = get(tool_name)
    if record is None:
        return False
    return profile in record.profiles


_ALL_PROFILES = frozenset(
    ["minimal", "pcb_only", "schematic_only", "manufacturing", "analysis", "agent_full"]
)
_PCB_PROFILES = frozenset(["pcb_only", "manufacturing", "analysis", "agent_full"])
_SCH_PROFILES = frozenset(["schematic_only", "manufacturing", "analysis", "agent_full"])
_MFG_PROFILES = frozenset(["manufacturing", "agent_full"])


def _register_many(
    names: list[str],
    *,
    profiles: frozenset[str],
    tier: AccessTier,
    runtime: RuntimeRequirement = RuntimeRequirement.NONE,
    supports_dry_run: bool = False,
    verification_level: str = "experimental",
) -> None:
    for name in names:
        register(
            CapabilityRecord(
                name=name,
                profiles=profiles,
                tier=tier,
                runtime=runtime,
                supports_dry_run=supports_dry_run,
                verification_level=verification_level,
            )
        )


_register_many(
    [
        "kicad_set_project",
        "project_get_design_spec",
        "project_quality_gate_report",
        "kicad_health",
        "kicad_doctor",
    ],
    profiles=_ALL_PROFILES,
    tier=AccessTier.READ,
    verification_level="verified",
)

_register_many(
    [
        "sch_list_symbols",
        "sch_get_netlist",
        "sch_get_bom",
        "sch_validate_connectivity",
        "sch_get_sheet_list",
    ],
    profiles=_SCH_PROFILES,
    tier=AccessTier.READ,
    runtime=RuntimeRequirement.KICAD_IPC,
    verification_level="verified",
)

_register_many(
    [
        "sch_add_symbol",
        "sch_add_wire",
        "sch_add_label",
        "sch_update_properties",
        "sch_build_circuit",
        "sch_annotate",
    ],
    profiles=_SCH_PROFILES,
    tier=AccessTier.WRITE,
    runtime=RuntimeRequirement.KICAD_IPC,
    supports_dry_run=True,
)

_register_many(
    [
        "pcb_get_board_state",
        "pcb_list_footprints",
        "pcb_get_tracks",
        "pcb_get_zones",
        "pcb_run_drc",
    ],
    profiles=_PCB_PROFILES,
    tier=AccessTier.READ,
    runtime=RuntimeRequirement.KICAD_IPC,
    verification_level="verified",
)

_register_many(
    [
        "pcb_add_footprint",
        "pcb_move_footprint",
        "pcb_sync_from_schematic",
        "pcb_add_track",
        "pcb_add_via",
        "pcb_run_autorouter",
    ],
    profiles=_PCB_PROFILES,
    tier=AccessTier.WRITE,
    runtime=RuntimeRequirement.KICAD_IPC,
    supports_dry_run=True,
)

_register_many(
    [
        "export_gerbers",
        "export_drill",
        "export_bom",
        "export_netlist",
        "export_step",
        "export_pdf",
        "export_svg",
        "export_dxf",
        "export_ipc2581",
        "export_pick_and_place",
    ],
    profiles=_PCB_PROFILES | _MFG_PROFILES,
    tier=AccessTier.EXPORT,
    runtime=RuntimeRequirement.KICAD_CLI,
    supports_dry_run=True,
    verification_level="verified",
)

register(
    CapabilityRecord(
        name="export_manufacturing_package",
        profiles=_MFG_PROFILES,
        tier=AccessTier.HUMAN_ONLY,
        runtime=RuntimeRequirement.KICAD_CLI,
        supports_dry_run=True,
        human_gate_required=True,
        description="Final manufacturing package. Requires explicit human approval.",
        verification_level="verified",
    )
)
