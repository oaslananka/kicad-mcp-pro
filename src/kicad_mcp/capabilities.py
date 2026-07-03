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
    NETWORK = "network"


class ToolMaturity(StrEnum):
    """Operational maturity for an advertised tool."""

    STABLE = "stable"
    BETA = "beta"
    EXPERIMENTAL = "experimental"
    ADVISORY = "advisory"
    DEPRECATED = "deprecated"


class AdvisoryLevel(StrEnum):
    """How much human/evidence review a tool result requires."""

    NONE = "none"
    ADVISORY = "advisory"
    REQUIRES_EVIDENCE = "requires_evidence"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class CapabilityRecord:
    """Metadata for a single registered tool capability."""

    name: str
    profiles: frozenset[str]
    tier: AccessTier
    category: str = "system"
    runtime: RuntimeRequirement = RuntimeRequirement.NONE
    writes_files: bool = False
    writes_kicad_gui_state: bool = False
    supports_dry_run: bool = False
    supports_rollback: bool = False
    human_gate_required: bool = False
    requires_human_confirmation: bool = False
    description: str = ""
    verification_level: str = "experimental"
    maturity: ToolMaturity = ToolMaturity.EXPERIMENTAL
    advisory_level: AdvisoryLevel = AdvisoryLevel.ADVISORY
    tested_kicad_versions: tuple[str, ...] = ("10.0.x",)


PROTOCOL_TOOL_CAPABILITY_SCHEMA_VERSION = "1.0.0"
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


def to_protocol_metadata(record: CapabilityRecord) -> dict[str, object]:
    """Return schema-versioned metadata for an advertised capability."""
    return {
        "schemaVersion": PROTOCOL_TOOL_CAPABILITY_SCHEMA_VERSION,
        "name": record.name,
        "profiles": sorted(record.profiles),
        "category": record.category,
        "tier": record.tier.value,
        "runtime": record.runtime.value,
        "writes_files": record.writes_files,
        "writes_kicad_gui_state": record.writes_kicad_gui_state,
        "supports_dry_run": record.supports_dry_run,
        "supports_rollback": record.supports_rollback,
        "human_gate_required": record.human_gate_required,
        "requires_human_confirmation": record.requires_human_confirmation,
        "description": record.description,
        "verification_level": record.verification_level,
        "maturity": record.maturity.value,
        "advisory_level": record.advisory_level.value,
        "tested_kicad_versions": list(record.tested_kicad_versions),
    }


def all_protocol_metadata() -> list[dict[str, object]]:
    """Return all capability records as protocol-schema payloads."""
    return [
        to_protocol_metadata(record)
        for record in sorted(_REGISTRY.values(), key=lambda item: item.name)
    ]


def tools_for_profile(profile: str) -> list[CapabilityRecord]:
    """Return all capability records available to a profile."""
    return [record for record in _REGISTRY.values() if profile in record.profiles]


def is_allowed(tool_name: str, profile: str) -> bool:
    """Return whether a tool is allowed for a profile."""
    record = get(tool_name)
    if record is None:
        return False
    return profile in record.profiles


def metadata_coverage() -> dict[str, object]:
    """Return capability metadata coverage for tools declared in the router."""
    from .tools.router import TOOL_CATEGORIES

    routed_tools = {
        tool_name for category in TOOL_CATEGORIES.values() for tool_name in category["tools"]
    }
    registered = set(_REGISTRY)
    missing = sorted(routed_tools - registered)
    return {
        "routed_tools": len(routed_tools),
        "registered_tools": len(routed_tools & registered),
        "missing_tools": missing,
        "coverage_pct": 100.0
        if not routed_tools
        else (len(routed_tools & registered) / len(routed_tools)) * 100,
    }


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
    writes_files: bool = False,
    writes_kicad_gui_state: bool = False,
    verification_level: str = "experimental",
) -> None:
    for name in names:
        register(
            CapabilityRecord(
                name=name,
                profiles=profiles,
                tier=tier,
                runtime=runtime,
                writes_files=writes_files,
                writes_kicad_gui_state=writes_kicad_gui_state,
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

# File-backed schematic reads that parse the ``.kicad_sch`` directly and stay
# discoverable when KiCad is not running.
_register_many(
    [
        "sch_get_population_status",
    ],
    profiles=_SCH_PROFILES,
    tier=AccessTier.READ,
    verification_level="verified",
)

_register_many(
    [
        "sch_add_component",
        "sch_add_symbol",
        "sch_add_wire",
        "sch_add_label",
        "sch_modify_property",
        "sch_update_properties",
        "sch_build_circuit",
        "sch_annotate",
    ],
    profiles=_SCH_PROFILES,
    tier=AccessTier.WRITE,
    runtime=RuntimeRequirement.NONE,
    supports_dry_run=True,
    writes_files=True,
)

# File-based schematic authoring tools that write the ``.kicad_sch`` directly and
# only reload KiCad opportunistically. They do not require a live IPC session, so
# they must stay discoverable when KiCad is not running (issue #198 follow-up).
# Kept separate from the block above because they do not expose a dry-run path.
_register_many(
    [
        "sch_add_no_connect",
        "sch_instantiate_template",
        "sch_auto_place_functional",
    ],
    profiles=_SCH_PROFILES,
    tier=AccessTier.WRITE,
    runtime=RuntimeRequirement.NONE,
    writes_files=True,
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
        "pcb_place_component",
        "pcb_route_trace",
        "pcb_add_footprint",
        "pcb_move_footprint",
        "pcb_move_component",
        "pcb_sync_from_schematic",
        "pcb_add_track",
        "pcb_add_zone",
        "pcb_add_via",
        "pcb_set_design_rules",
        "pcb_delete_object",
        "pcb_delete_items",
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
        "export_stepz",
        "export_xao",
        "export_pdf",
        "export_svg",
        "export_dxf",
        "export_ipc2581",
        "export_odb",
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
        category="release_export",
        runtime=RuntimeRequirement.KICAD_CLI,
        writes_files=True,
        supports_dry_run=True,
        supports_rollback=False,
        human_gate_required=True,
        requires_human_confirmation=True,
        description="Final manufacturing package. Requires explicit human approval.",
        verification_level="verified",
        maturity=ToolMaturity.STABLE,
        advisory_level=AdvisoryLevel.HUMAN_REVIEW,
    )
)


def _profiles_for_category(category: str) -> frozenset[str]:
    from .tools.router import PROFILE_CATEGORIES

    return frozenset(
        profile for profile, categories in PROFILE_CATEGORIES.items() if category in categories
    )


def _is_read_tool(name: str, category: str) -> bool:
    if category in {"pcb_read", "dfm"}:
        return True
    if name in {
        "kicad_set_project",
        "project_design_workflow",
        "pcb_placement_quality_gate",
        "pcb_placement_quality_report",
        "pcb_transfer_quality_gate",
        "pcb_transfer_quality_report",
        "lib_certify_footprint",
    }:
        return True
    return name.startswith(
        (
            "get_",
            "list_",
            "check_",
            "validate_",
            "run_",
            "kicad_get_",
            "kicad_list_",
            "kicad_help",
            "project_get_",
            "project_assess_",
            "project_validate_",
            "project_gate_",
            "si_get_",
            "sch_get_",
            "sch_list_",
            "sch_find_",
            "sch_analyze_",
            "sch_check_",
            "sch_trace_",
            "pcb_get_",
            "pcb_check_",
            "pcb_placement_quality_",
            "pcb_transfer_quality_",
            "lib_get_",
            "lib_list_",
            "lib_search_",
            "lib_check_",
            "lib_find_",
            "lib_recommend_",
            "mfg_check_",
            "route_list_",
            "variant_list",
            "variant_get_",
            "vcs_list_",
            "vcs_diff_",
        )
    )


def _tier_for_tool(name: str, category: str) -> AccessTier:
    if name == "export_manufacturing_package":
        return AccessTier.HUMAN_ONLY
    if _is_read_tool(name, category):
        return AccessTier.READ
    if category in {"export", "release_export"} or "_export" in name or name.startswith("export_"):
        return AccessTier.EXPORT
    if category == "version_control" and name in {"vcs_commit_checkpoint", "vcs_tag_release"}:
        return AccessTier.PUBLISH
    if category == "manufacturing" and (
        name.startswith(("mfg_import_", "jobset_export", "fp_export", "sym_export"))
    ):
        return AccessTier.EXPORT
    return AccessTier.WRITE


def _runtime_for_tool(name: str, category: str, tier: AccessTier) -> RuntimeRequirement:
    if name in {"sch_render_png", "sch_render_visual_diff", "sch_set_title_block_info"}:
        return RuntimeRequirement.NONE
    if category == "simulation" or name.startswith("sim_"):
        return RuntimeRequirement.NGSPICE
    if "freerouting" in name:
        return RuntimeRequirement.FREEROUTING
    if name.startswith("lib_search_components") or name in {
        "lib_get_component_details",
        "lib_check_stock_availability",
        "lib_find_alternative_parts",
        "lib_get_bom_with_pricing",
    }:
        return RuntimeRequirement.NETWORK
    if category in {"export", "release_export", "manufacturing"}:
        return RuntimeRequirement.KICAD_CLI
    if category == "validation" and name in {"run_drc", "run_erc", "validate_design"}:
        return RuntimeRequirement.KICAD_CLI
    if category in {"pcb_read", "pcb_write", "schematic"} and tier is not AccessTier.READ:
        return RuntimeRequirement.KICAD_IPC
    return RuntimeRequirement.NONE


def _maturity_for_tool(name: str, category: str, tier: AccessTier) -> ToolMaturity:
    if name in {"sch_swap_pins", "sch_swap_gates", "sch_add_jumper", "sch_reload"}:
        return ToolMaturity.EXPERIMENTAL
    if category in {"signal_integrity", "power_integrity", "emc", "simulation"}:
        return ToolMaturity.ADVISORY
    if tier in {AccessTier.WRITE, AccessTier.PUBLISH}:
        return ToolMaturity.BETA
    return ToolMaturity.STABLE


def _advisory_level_for_tool(category: str, tier: AccessTier) -> AdvisoryLevel:
    if tier is AccessTier.HUMAN_ONLY:
        return AdvisoryLevel.HUMAN_REVIEW
    if category in {"signal_integrity", "power_integrity", "emc", "simulation"}:
        return AdvisoryLevel.ADVISORY
    if category in {"validation", "release_export", "manufacturing"}:
        return AdvisoryLevel.REQUIRES_EVIDENCE
    return AdvisoryLevel.NONE if tier is AccessTier.READ else AdvisoryLevel.ADVISORY


def _register_router_tools() -> None:
    from .tools.router import TOOL_CATEGORIES

    for category, info in TOOL_CATEGORIES.items():
        profiles = _profiles_for_category(category)
        for name in info["tools"]:
            existing = _REGISTRY.get(name)
            if existing is not None:
                continue
            tier = _tier_for_tool(name, category)
            runtime = _runtime_for_tool(name, category, tier)
            writes_files = tier in {
                AccessTier.WRITE,
                AccessTier.EXPORT,
                AccessTier.PUBLISH,
                AccessTier.HUMAN_ONLY,
            }
            writes_gui = runtime is RuntimeRequirement.KICAD_IPC and tier in {
                AccessTier.WRITE,
                AccessTier.PUBLISH,
            }
            register(
                CapabilityRecord(
                    name=name,
                    profiles=profiles,
                    tier=tier,
                    category=category,
                    runtime=runtime,
                    writes_files=writes_files,
                    writes_kicad_gui_state=writes_gui,
                    supports_dry_run=False,
                    supports_rollback=category == "version_control"
                    or name.startswith(("pcb_begin_", "pcb_push_", "pcb_drop_", "pcb_revert")),
                    human_gate_required=tier is AccessTier.HUMAN_ONLY,
                    requires_human_confirmation=tier is AccessTier.HUMAN_ONLY,
                    description=f"{category} tool exposed by KiCad MCP Pro.",
                    verification_level="verified" if tier is AccessTier.READ else "experimental",
                    maturity=_maturity_for_tool(name, category, tier),
                    advisory_level=_advisory_level_for_tool(category, tier),
                )
            )


_register_router_tools()
