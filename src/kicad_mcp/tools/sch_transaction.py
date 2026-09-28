"""Transactional schematic plan/preview/apply/verify/rollback tools (issue #155).

Provides a plan-based transaction model over schematic edits so an agent can:

1. ``sch_plan_from_spec``  — turn a subcircuit spec into a stored, content-addressed plan;
2. ``sch_preview_plan``    — see the object changes a plan would make, without writing;
3. ``sch_apply_plan``      — checkpoint the schematic, then apply the plan's net labels;
4. ``sch_verify_plan``     — verify the applied changes (connectivity) and report ERC status;
5. ``sch_rollback_plan``   — restore the schematic from the checkpoint.

Mutations go through the project's atomic, validating ``transactional_write`` and are
guarded by a file checkpoint, so a failed or unwanted apply is always recoverable.
Net labels are applied directly (no library dependency); symbol placement is recorded
in the plan/preview and is expected to reuse ``sch_add_symbol`` as a follow-up.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..models import sch_transaction as txn
from .metadata import headless_compatible


def _plans_dir() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError("No active project is configured. Call kicad_set_project() first.")
    target = cfg.project_dir / ".kicad-mcp" / "plans"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _plan_path(plan_id: str) -> Path:
    return _plans_dir() / f"{plan_id}.json"


def _load_stored(plan_id: str) -> txn.StoredPlan | None:
    path = _plan_path(plan_id)
    if not path.exists():
        return None
    return txn.StoredPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _save_stored(stored: txn.StoredPlan) -> None:
    _plan_path(stored.plan.plan_id).write_text(
        json.dumps(stored.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _active_schematic() -> Path:
    from .schematic import project_schematic_files

    files = project_schematic_files()
    cfg = get_config()
    if cfg.project_file is not None:
        stem = cfg.project_file.stem
        for candidate in files:
            if candidate.stem == stem:
                return candidate
    return files[0]


def _label_identity(name: str, x: float, y: float) -> tuple[str, float, float]:
    """Normalize one label instance to the same coordinate precision as connectivity groups."""
    return (name, round(float(x), 4), round(float(y), 4))


def register(mcp: FastMCP) -> None:
    """Register transactional schematic plan tools."""

    @mcp.tool()
    @headless_compatible
    def sch_plan_from_spec(spec_json: str) -> str:
        """Create a stored schematic change plan from a JSON spec (no write).

        The spec describes a small subcircuit as ``components`` (reference + lib_id,
        optional value/footprint) and ``labels`` (text + x/y) plus optional ``nets``
        and ``title``. Returns the content-addressed ``plan_id`` to use with the
        preview/apply/verify/rollback tools.
        """
        try:
            spec = json.loads(spec_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"spec_json is not valid JSON: {exc}"})
        try:
            plan = txn.plan_from_spec(spec)
        except txn.PlanValidationError as exc:
            return json.dumps({"error": str(exc)})
        stored = txn.StoredPlan(plan=plan)
        _save_stored(stored)
        return json.dumps(
            {
                "plan_id": plan.plan_id,
                "title": plan.title,
                "status": stored.status,
                "change_count": len(txn.plan_changes(plan)),
            },
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def sch_preview_plan(plan_id: str) -> str:
        """Return the object changes a plan would make, without writing anything."""
        stored = _load_stored(plan_id)
        if stored is None:
            return json.dumps({"error": f"No plan found with id '{plan_id}'."})
        return json.dumps(
            {
                "plan_id": plan_id,
                "status": stored.status,
                "changes": txn.plan_changes(stored.plan),
            },
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def sch_apply_plan(plan_id: str) -> str:
        """Checkpoint the schematic, then apply the plan's net labels.

        Copies every schematic file into a per-plan checkpoint before mutating, so
        ``sch_rollback_plan`` can fully restore the prior state. The label insertion
        runs through the project's atomic, validating writer.
        """
        from .schematic import project_schematic_files, transactional_write

        stored = _load_stored(plan_id)
        if stored is None:
            return json.dumps({"error": f"No plan found with id '{plan_id}'."})
        if stored.status == "applied":
            return json.dumps(
                {"plan_id": plan_id, "status": "applied", "note": "Plan was already applied."}
            )

        checkpoint_dir = _plans_dir() / plan_id / "checkpoint"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        backed_up: list[str] = []
        for sch_file in project_schematic_files():
            shutil.copy2(sch_file, checkpoint_dir / sch_file.name)
            backed_up.append(sch_file.name)

        active = _active_schematic()
        labels = stored.plan.labels

        def _mutator(text: str) -> str:
            return txn.insert_labels(text, labels)

        if labels:
            transactional_write(_mutator, active)

        applied = txn.StoredPlan(
            plan=stored.plan,
            status="applied",
            checkpoint_dir=str(checkpoint_dir),
            applied_files=tuple(backed_up),
        )
        _save_stored(applied)
        return json.dumps(
            {
                "plan_id": plan_id,
                "status": "applied",
                "labels_added": len(labels),
                "checkpoint": str(checkpoint_dir),
                "note": (
                    "Net labels applied; symbol placement (if any) is recorded in the "
                    "plan and should be applied with sch_add_symbol."
                ),
            },
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def sch_verify_plan(plan_id: str) -> str:
        """Verify an applied plan against the schematic; report ERC availability.

        Verification fails closed when planned labels or components are absent,
        planned labels are unattached, or connectivity analysis cannot complete.
        Full ERC is declared explicitly as available or unavailable rather than
        silently skipped — run ``run_erc()`` for the full electrical gate.
        """
        stored = _load_stored(plan_id)
        if stored is None:
            return json.dumps({"error": f"No plan found with id '{plan_id}'."})
        if stored.status != "applied":
            return json.dumps(
                {"plan_id": plan_id, "status": stored.status, "note": "Plan is not applied yet."}
            )

        from .schematic import build_connectivity_groups, parse_schematic_file

        active = _active_schematic()
        parsed = parse_schematic_file(active)
        placed_label_identities = {
            _label_identity(
                str(label.get("name", "")),
                float(label.get("x", 0.0)),
                float(label.get("y", 0.0)),
            )
            for label in parsed.get("labels", [])
        }
        missing_label_identities = {
            _label_identity(label.text, label.x, label.y)
            for label in stored.plan.labels
            if _label_identity(label.text, label.x, label.y) not in placed_label_identities
        }
        missing_labels = [
            label.text
            for label in stored.plan.labels
            if _label_identity(label.text, label.x, label.y) in missing_label_identities
        ]
        placed_references = {
            str(symbol.get("reference", "")) for symbol in parsed.get("symbols", [])
        }
        missing_components = [
            component.reference
            for component in stored.plan.components
            if component.reference not in placed_references
        ]

        unconnected_labels: list[str] = []
        connectivity_error: str | None = None
        if stored.plan.labels:
            try:
                groups = build_connectivity_groups(active)
            except (OSError, RuntimeError, ValueError) as exc:
                connectivity_error = str(exc)
            else:
                for label in stored.plan.labels:
                    label_identity = _label_identity(label.text, label.x, label.y)
                    if label_identity in missing_label_identities:
                        continue
                    planned_point = label_identity[1:]
                    matching_groups = [
                        group
                        for group in groups
                        if label.text in group.get("names", [])
                        and planned_point
                        in {
                            (round(float(point[0]), 4), round(float(point[1]), 4))
                            for point in group.get("points", [])
                        }
                    ]
                    if not matching_groups or all(
                        not group.get("pins") and len(group.get("points", [])) == 1
                        for group in matching_groups
                    ):
                        unconnected_labels.append(label.text)

        connectivity = (
            "pass"
            if not missing_labels
            and not missing_components
            and not unconnected_labels
            and connectivity_error is None
            else "fail"
        )

        erc_available = shutil.which("kicad-cli") is not None
        erc_status = "available" if erc_available else "unavailable"
        erc_note = (
            "Run run_erc() for the full electrical rules check."
            if erc_available
            else "kicad-cli not found on PATH; ERC cannot run headless here."
        )

        return json.dumps(
            {
                "plan_id": plan_id,
                "connectivity": connectivity,
                "missing_labels": missing_labels,
                "missing_components": missing_components,
                "unconnected_labels": unconnected_labels,
                "connectivity_error": connectivity_error,
                "erc": erc_status,
                "erc_note": erc_note,
            },
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def sch_rollback_plan(plan_id: str) -> str:
        """Restore the schematic from a plan's checkpoint, undoing the apply."""
        stored = _load_stored(plan_id)
        if stored is None:
            return json.dumps({"error": f"No plan found with id '{plan_id}'."})
        if stored.status != "applied" or not stored.checkpoint_dir:
            return json.dumps(
                {"plan_id": plan_id, "status": stored.status, "note": "Nothing to roll back."}
            )

        checkpoint_dir = Path(stored.checkpoint_dir)
        cfg = get_config()
        if cfg.project_dir is None:
            return json.dumps({"error": "No active project is configured."})
        restored: list[str] = []
        for name in stored.applied_files:
            source = checkpoint_dir / name
            if source.exists():
                shutil.copy2(source, cfg.project_dir / name)
                restored.append(name)

        rolled_back = txn.StoredPlan(
            plan=stored.plan,
            status="rolled_back",
            checkpoint_dir=stored.checkpoint_dir,
            applied_files=stored.applied_files,
        )
        _save_stored(rolled_back)
        return json.dumps(
            {"plan_id": plan_id, "status": "rolled_back", "restored_files": restored}, indent=2
        )
