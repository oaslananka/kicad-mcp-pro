"""Operating mode policy for KiCad MCP Pro tool exposure and execution."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .capabilities import AccessTier, all_records, get
from .config import get_config
from .tools.router import EXPERIMENTAL_TOOL_NAMES, TOOL_CATEGORIES


class OperatingMode(StrEnum):
    """Risk-oriented MCP operating modes."""

    READONLY = "readonly"
    WRITE = "write"
    MANUFACTURING = "manufacturing"
    EXPERIMENTAL = "experimental"


DEFAULT_OPERATING_MODE = OperatingMode.READONLY
OPERATING_MODE_VALUES = tuple(mode.value for mode in OperatingMode)

_ALLOWED_REQUIREMENTS: dict[OperatingMode, frozenset[OperatingMode]] = {
    OperatingMode.READONLY: frozenset({OperatingMode.READONLY}),
    OperatingMode.WRITE: frozenset({OperatingMode.READONLY, OperatingMode.WRITE}),
    OperatingMode.MANUFACTURING: frozenset({OperatingMode.READONLY, OperatingMode.MANUFACTURING}),
    OperatingMode.EXPERIMENTAL: frozenset(OperatingMode),
}

_MANUFACTURING_TOOL_NAMES = frozenset(
    {
        "export_manufacturing_package",
        "manufacturing_quality_gate",
        "check_design_for_manufacture",
    }
)
_WRITE_TOOL_NAMES = frozenset(
    {
        "project_set_design_intent",
        "project_auto_fix_loop",
        "project_full_validation_loop",
        "kicad_create_new_project",
        "dfm_load_manufacturer_profile",
        "sch_live_preview",
    }
)
_WRITE_PREFIXES = (
    "pcb_add",
    "pcb_align",
    "pcb_auto",
    "pcb_bga",
    "pcb_block_create",
    "pcb_block_place",
    "pcb_delete",
    "pcb_group",
    "pcb_highlight",
    "pcb_move",
    "pcb_place_",
    "pcb_refill",
    "pcb_route",
    "pcb_save",
    "pcb_set",
    "pcb_sync",
    "sch_add",
    "sch_auto",
    "sch_build",
    "sch_create",
    "sch_delete",
    "sch_instantiate",
    "sch_modify",
    "sch_move",
    "sch_reload",
    "sch_route",
    "sch_set",
    "sch_update",
    "variant_create",
    "variant_set",
    "lib_assign",
    "lib_bind",
    "lib_create",
    "lib_generate",
    "sim_add",
    "drc_rule_create",
    "drc_rule_delete",
    "drc_rule_enable",
    "vcs_",
)


@dataclass(frozen=True)
class ToolOperatingModeAvailability:
    """Mode-gating status for a single tool."""

    available: bool
    required_mode: OperatingMode
    reason: str | None

    def as_contract(self) -> dict[str, object]:
        """Return the protocol-schema shape used by server-info."""
        return {
            "available": self.available,
            "requiredMode": self.required_mode.value,
            "reason": self.reason,
        }


def parse_operating_mode(value: object) -> OperatingMode:
    """Normalize a CLI/config value into an operating mode."""
    if isinstance(value, OperatingMode):
        return value
    raw = str(value or DEFAULT_OPERATING_MODE.value).strip().casefold()
    normalized = raw.replace("_", "-")
    aliases = {
        "read-only": OperatingMode.READONLY.value,
        "read_only": OperatingMode.READONLY.value,
        "ro": OperatingMode.READONLY.value,
        "mfg": OperatingMode.MANUFACTURING.value,
    }
    candidate = aliases.get(normalized, normalized)
    if candidate == "read-only":
        candidate = OperatingMode.READONLY.value
    return OperatingMode(candidate)


def active_operating_mode(config: object | None = None) -> OperatingMode:
    """Return the effective operating mode from configuration."""
    cfg = config or get_config()
    if bool(getattr(cfg, "enable_experimental_tools", False)):
        return OperatingMode.EXPERIMENTAL
    return parse_operating_mode(getattr(cfg, "operating_mode", DEFAULT_OPERATING_MODE.value))


def tool_required_mode(tool_name: str) -> OperatingMode:
    """Return the minimum operating mode required by a tool."""
    if _is_experimental_tool(tool_name):
        return OperatingMode.EXPERIMENTAL
    if _is_manufacturing_tool(tool_name):
        return OperatingMode.MANUFACTURING

    record = get(tool_name)
    if record is not None:
        if record.tier is AccessTier.WRITE or record.tier is AccessTier.PUBLISH:
            return OperatingMode.WRITE
        if record.tier is AccessTier.HUMAN_ONLY:
            return OperatingMode.MANUFACTURING
        return OperatingMode.READONLY

    if _is_write_tool(tool_name):
        return OperatingMode.WRITE
    return OperatingMode.READONLY


def is_tool_allowed_in_mode(tool_name: str, mode: OperatingMode | str | None = None) -> bool:
    """Return whether a tool may be discovered or executed in the active mode."""
    active = parse_operating_mode(mode) if mode is not None else active_operating_mode()
    required = tool_required_mode(tool_name)
    return required in _ALLOWED_REQUIREMENTS[active]


def tool_availability(
    tool_name: str,
    mode: OperatingMode | str | None = None,
) -> ToolOperatingModeAvailability:
    """Return structured mode availability for a tool."""
    active = parse_operating_mode(mode) if mode is not None else active_operating_mode()
    required = tool_required_mode(tool_name)
    available = required in _ALLOWED_REQUIREMENTS[active]
    return ToolOperatingModeAvailability(
        available=available,
        required_mode=required,
        reason=None if available else required_mode_reason(required),
    )


def known_tool_names() -> tuple[str, ...]:
    """Return tool names known to profile routing or capability metadata."""
    names = set(all_records())
    for category in TOOL_CATEGORIES.values():
        names.update(category["tools"])
    return tuple(sorted(names))


def operating_mode_contract(config: object | None = None) -> dict[str, object]:
    """Return server-info metadata for the effective operating mode."""
    cfg = config or get_config()
    active = active_operating_mode(cfg)
    return {
        "active": active.value,
        "default": DEFAULT_OPERATING_MODE.value,
        "available": list(OPERATING_MODE_VALUES),
        "experimentalEnabled": active is OperatingMode.EXPERIMENTAL,
        "toolAvailability": {
            name: tool_availability(name, active).as_contract() for name in known_tool_names()
        },
    }


def filter_tools_for_mode[T](
    tools: Iterable[T],
    mode: OperatingMode | str | None = None,
) -> list[T]:
    """Filter MCP tool objects according to operating mode policy."""
    active = parse_operating_mode(mode) if mode is not None else active_operating_mode()
    return [
        tool for tool in tools if is_tool_allowed_in_mode(str(getattr(tool, "name", "")), active)
    ]


def denial_message(tool_name: str, mode: OperatingMode | str | None = None) -> str:
    """Return the execution denial text for a mode-blocked tool."""
    active = parse_operating_mode(mode) if mode is not None else active_operating_mode()
    required = tool_required_mode(tool_name)
    return (
        f"Tool '{tool_name}' requires {required.value} operating mode; "
        f"active mode is {active.value}."
    )


def required_mode_reason(required: OperatingMode) -> str:
    """Return the structured server-info reason for an unavailable tool."""
    return f"Requires {required.value} operating mode."


def _category_names_for_tool(tool_name: str) -> set[str]:
    return {
        category_name
        for category_name, category in TOOL_CATEGORIES.items()
        if tool_name in category["tools"]
    }


def _is_experimental_tool(tool_name: str) -> bool:
    categories = _category_names_for_tool(tool_name)
    return (
        tool_name in EXPERIMENTAL_TOOL_NAMES
        or "routing" in categories
        or tool_name.startswith(("route_", "tune_"))
    )


def _is_manufacturing_tool(tool_name: str) -> bool:
    categories = _category_names_for_tool(tool_name)
    return (
        tool_name in _MANUFACTURING_TOOL_NAMES
        or "manufacturing" in categories
        or "release_export" in categories
        or tool_name.startswith("mfg_")
    )


def _is_write_tool(tool_name: str) -> bool:
    categories = _category_names_for_tool(tool_name)
    return (
        tool_name in _WRITE_TOOL_NAMES
        or "pcb_write" in categories
        or tool_name.startswith(_WRITE_PREFIXES)
    )
