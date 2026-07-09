"""Gate-to-fixer registry for the auto-fix loop.

This module describes *which* tool to call and *why*, given a gate name and
optional failure reason text.  For ``auto_applicable`` fixers it also exposes
a ``callable_import`` path so that ``project_auto_fix_loop`` can invoke the
underlying implementation directly — without going through MCP transport.

Callable convention: ``"module_path:function_name"``  where ``module_path`` is
relative to the ``kicad_mcp`` package (e.g. ``tools.schematic:run_auto_annotate``).
The function must take no required arguments and return a ``str`` summary.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class FixerAction:
    """A single recommended fix action for a failing gate.

    ``auto_applicable`` indicates the server can apply the fix without agent
    involvement (e.g., zone refill, annotation).  When ``False``, the action is
    returned as an instruction for the agent.

    ``callable_import`` — optional ``"module:function"`` string used by
    ``project_auto_fix_loop`` to call the fixer directly.
    """

    tool: str
    description: str
    args: dict[str, Any] = field(default_factory=dict)
    auto_applicable: bool = False
    callable_import: str = ""  # e.g. "tools.schematic:run_auto_annotate"


# ---------------------------------------------------------------------------
# Gate-name → ordered list of FixerActions
#
# Each entry in a fixer list is tried in order; the first matching one is used
# by project_auto_fix_loop.  Multiple entries cover different failure reasons.
# ---------------------------------------------------------------------------

GATE_FIXERS: dict[str, list[FixerAction]] = {
    "Schematic": [
        FixerAction(
            tool="sch_annotate",
            description="Annotate un-annotated schematic symbols.",
            auto_applicable=True,
            callable_import="tools.schematic:run_auto_annotate",
        ),
        FixerAction(
            tool="sch_get_bounding_boxes",
            description=(
                "Check for overlapping symbols: get current bounding boxes, "
                "then use sch_find_free_placement + sch_auto_place_symbols to fix."
            ),
        ),
        FixerAction(
            tool="run_erc",
            description="Run ERC to surface remaining schematic rule violations.",
        ),
    ],
    "Schematic connectivity": [
        FixerAction(
            tool="sch_add_missing_junctions",
            description="Insert missing junctions at wire T-intersections.",
            auto_applicable=True,
            callable_import="tools.schematic:run_auto_add_missing_junctions",
        ),
        FixerAction(
            tool="sch_check_power_flags",
            description="Add missing PWR_FLAG symbols to power nets.",
        ),
        FixerAction(
            tool="sch_analyze_net_compilation",
            description="Inspect net compilation errors and fix dangling labels.",
        ),
    ],
    "Pre-sync": [
        FixerAction(
            tool="sch_add_missing_junctions",
            description="Repair missing schematic junctions before PCB sync.",
            auto_applicable=True,
            callable_import="tools.schematic:run_auto_add_missing_junctions",
        ),
        FixerAction(
            tool="sch_annotate",
            description="Annotate un-annotated symbols before PCB sync.",
            auto_applicable=True,
            callable_import="tools.schematic:run_auto_annotate",
        ),
    ],
    "PCB": [
        FixerAction(
            tool="pcb_refill_zones",
            description="Refill copper zones to resolve unconnected-net violations.",
            auto_applicable=True,
            callable_import="tools.pcb:run_auto_refill_zones",
        ),
        FixerAction(
            tool="run_drc",
            description="Run DRC to identify remaining rule violations.",
        ),
    ],
    "Placement": [
        FixerAction(
            tool="pcb_place_decoupling_caps",
            description="Place decoupling capacitors near their IC partners.",
        ),
        FixerAction(
            tool="pcb_auto_place_by_schematic",
            description="Re-run schematic-guided auto-placement.",
        ),
        FixerAction(
            tool="pcb_score_placement",
            description="Score current placement to identify specific constraint failures.",
        ),
    ],
    "PCB transfer": [
        FixerAction(
            tool="pcb_sync_from_schematic",
            description="Synchronise PCB footprints from the schematic netlist.",
        ),
        FixerAction(
            tool="pcb_transfer_quality_gate",
            description="Inspect transfer-gate details to identify missing footprints.",
        ),
    ],
    "Manufacturing": [
        FixerAction(
            tool="dfm_run_manufacturer_check",
            description="Run detailed DFM check to see specific manufacturing violations.",
        ),
        FixerAction(
            tool="pcb_refill_zones",
            description="Refill zones — common cause of DFM copper-coverage failures.",
            auto_applicable=True,
            callable_import="tools.pcb:run_auto_refill_zones",
        ),
    ],
    "Footprint parity": [
        FixerAction(
            tool="pcb_sync_from_schematic",
            description="Sync missing footprints from schematic to PCB.",
        ),
        FixerAction(
            tool="validate_footprints_vs_schematic",
            description="Inspect footprint-parity details to identify mismatched refs.",
        ),
    ],
    # Advisory only — cosmetic fixers mutate the schematic and default to a dry
    # run, so they are surfaced as suggestions (never auto-applied in the loop)
    # to respect the review-before-write workflow.
    "Schematic cosmetics": [
        FixerAction(
            tool="sch_cosmetic_score",
            description="Re-score cosmetics and read worst_category to pick the right fixer.",
        ),
        FixerAction(
            tool="sch_align_to_grid",
            description="Snap off-grid symbols/labels/wires to the grid (dry run, then apply).",
        ),
        FixerAction(
            tool="sch_straighten_wires",
            description="Flatten almost-orthogonal wires (dry run, then apply=true).",
        ),
        FixerAction(
            tool="sch_resolve_label_overlaps",
            description="De-conflict overlapping labels by flipping justify (dry run, then apply).",
        ),
        FixerAction(
            tool="sch_normalize_power_orientation",
            description="Upright sideways power symbols (dry run, then apply=true).",
        ),
        FixerAction(
            tool="sch_normalize_text_sizes",
            description="Normalise outlier fonts to the dominant size (dry run, then apply=true).",
        ),
    ],
}

# Gate names that, when failing, block *all* downstream gates.
BLOCKING_GATES: frozenset[str] = frozenset({"Schematic", "Schematic connectivity", "Pre-sync"})


def fixers_for_gate(gate_name: str) -> list[FixerAction]:
    """Return the ordered fixer list for a gate, or an empty list if unknown."""
    return GATE_FIXERS.get(gate_name, [])


def validate_callable_imports(
    registry: dict[str, list[FixerAction]] | None = None,
) -> list[str]:
    """Validate auto-fixer callable import paths and log warnings for bad entries."""
    missing: list[str] = []
    for gate_name, actions in (registry or GATE_FIXERS).items():
        for action in actions:
            if not action.callable_import:
                continue
            try:
                module_path, func_name = action.callable_import.rsplit(":", 1)
                module = importlib.import_module(f"kicad_mcp.{module_path}")
                candidate = getattr(module, func_name, None)
            except Exception as exc:
                missing.append(f"{gate_name}: {action.callable_import}")
                logger.warning(
                    "fixer_callable_import_invalid",
                    gate=gate_name,
                    tool=action.tool,
                    callable_import=action.callable_import,
                    error=str(exc),
                )
                continue
            if not callable(candidate):
                missing.append(f"{gate_name}: {action.callable_import}")
                logger.warning(
                    "fixer_callable_import_invalid",
                    gate=gate_name,
                    tool=action.tool,
                    callable_import=action.callable_import,
                    error="target is not callable",
                )
    return missing


def auto_fix_description(gate_name: str) -> str | None:
    """Return the description of the first auto-applicable fixer, or None."""
    for action in fixers_for_gate(gate_name):
        if action.auto_applicable:
            return action.description
    return None


def first_agent_action(gate_name: str) -> FixerAction | None:
    """Return the first non-auto fixer action for the agent to take."""
    for action in fixers_for_gate(gate_name):
        if not action.auto_applicable:
            return action
    return None


def sampling_prompt_for_gate(gate_name: str, summary: str, details: list[str] | None = None) -> str:
    """Build a compact prompt for MCP client-side sampling when supported."""
    rendered_details = "\n".join(f"- {detail}" for detail in (details or [])[:8])
    detail_block = f"\nDetails:\n{rendered_details}" if rendered_details else ""
    return (
        "You are a KiCad expert. Give a short, practical fix recommendation for "
        "the following quality-gate failure.\n"
        f"Gate: {gate_name}\n"
        f"Summary: {summary}{detail_block}"
    )
