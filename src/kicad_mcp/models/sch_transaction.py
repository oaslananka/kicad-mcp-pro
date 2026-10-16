"""Transactional schematic plan model (issue #155).

Models a schematic *plan* (a small subcircuit described as components + nets),
renders a no-write preview of the object changes it would make, and provides the
pure text mutation used to apply a plan's net labels. File checkpoint/rollback and
plan storage are handled by the thin tool layer in ``tools/sch_transaction.py``.

Plan IDs are content-addressed (a hash of the canonical spec) so the same spec
always yields the same id — deterministic and friendly to idempotent retries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PlannedComponent:
    reference: str
    lib_id: str
    value: str = ""
    footprint: str = ""


@dataclass(frozen=True, slots=True)
class PlannedLabel:
    text: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class SchPlan:
    """A validated schematic change plan."""

    plan_id: str
    title: str
    components: tuple[PlannedComponent, ...] = ()
    labels: tuple[PlannedLabel, ...] = ()
    nets: tuple[str, ...] = ()
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "components": [asdict(component) for component in self.components],
            "labels": [asdict(label) for label in self.labels],
            "nets": list(self.nets),
            "notes": self.notes,
        }


class PlanValidationError(ValueError):
    """Raised when a plan spec is structurally invalid."""


def _canonical(spec: dict[str, Any]) -> str:
    return json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_plan_id(spec: dict[str, Any]) -> str:
    """Return a stable, content-addressed id for ``spec``."""
    digest = hashlib.sha1(_canonical(spec).encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"plan_{digest[:12]}"


def plan_from_spec(spec: dict[str, Any]) -> SchPlan:
    """Validate and normalize a plan spec into a :class:`SchPlan`.

    Spec shape::

        {
          "title": "Buck output stage",
          "components": [{"reference": "R1", "lib_id": "Device:R", "value": "10k"}],
          "labels": [{"text": "VOUT", "x": 100, "y": 50}],
          "nets": ["VIN", "GND", "VOUT"]
        }
    """

    if not isinstance(spec, dict):
        raise PlanValidationError("Plan spec must be a JSON object.")

    title = str(spec.get("title", "")).strip() or "Untitled plan"

    components: list[PlannedComponent] = []
    for raw in spec.get("components", []) or []:
        if not isinstance(raw, dict):
            raise PlanValidationError("Each component must be an object.")
        reference = str(raw.get("reference", "")).strip()
        lib_id = str(raw.get("lib_id", "")).strip()
        if not reference or not lib_id:
            raise PlanValidationError("Each component needs a reference and lib_id.")
        components.append(
            PlannedComponent(
                reference=reference,
                lib_id=lib_id,
                value=str(raw.get("value", "")).strip(),
                footprint=str(raw.get("footprint", "")).strip(),
            )
        )

    labels: list[PlannedLabel] = []
    for raw in spec.get("labels", []) or []:
        if not isinstance(raw, dict):
            raise PlanValidationError("Each label must be an object.")
        text = str(raw.get("text", "")).strip()
        if not text:
            raise PlanValidationError("Each label needs text.")
        try:
            x = float(raw.get("x", 0.0))
            y = float(raw.get("y", 0.0))
        except (TypeError, ValueError) as exc:
            raise PlanValidationError("Label x/y must be numbers.") from exc
        labels.append(PlannedLabel(text=text, x=x, y=y))

    nets = tuple(str(net).strip() for net in (spec.get("nets", []) or []) if str(net).strip())

    if not components and not labels:
        raise PlanValidationError("A plan must add at least one component or label.")

    return SchPlan(
        plan_id=compute_plan_id(spec),
        title=title,
        components=tuple(components),
        labels=tuple(labels),
        nets=nets,
        notes=str(spec.get("notes", "")).strip(),
    )


def plan_changes(plan: SchPlan) -> list[dict[str, Any]]:
    """Return a no-write list of the object changes the plan would make."""
    changes: list[dict[str, Any]] = []
    for component in plan.components:
        changes.append(
            {
                "action": "add_component",
                "reference": component.reference,
                "lib_id": component.lib_id,
                "value": component.value,
                "footprint": component.footprint,
            }
        )
    for label in plan.labels:
        changes.append(
            {
                "action": "add_label",
                "text": label.text,
                "position": [label.x, label.y],
            }
        )
    return changes


def render_label_sexpr(label: PlannedLabel) -> str:
    """Render a single ``(label ...)`` s-expression for insertion."""
    text = label.text.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'\t(label "{text}" (at {label.x:g} {label.y:g} 0)\n'
        "\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n"
        "\t)"
    )


def insert_labels(sch_text: str, labels: tuple[PlannedLabel, ...]) -> str:
    """Insert label s-expressions before the schematic's final closing paren.

    This is a pure text transform; the caller wraps it in the project's atomic,
    validating ``transactional_write`` so a malformed result is never persisted.
    """
    if not labels:
        return sch_text
    close = sch_text.rfind(")")
    if close == -1:
        raise PlanValidationError("Schematic text has no closing parenthesis.")
    block = "\n" + "\n".join(render_label_sexpr(label) for label in labels) + "\n"
    return sch_text[:close] + block + sch_text[close:]


@dataclass(frozen=True, slots=True)
class StoredPlan:
    """On-disk plan record (status + checkpoint bookkeeping)."""

    plan: SchPlan
    status: str = "planned"  # planned | applied | rolled_back
    checkpoint_dir: str = ""
    applied_files: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.as_dict(),
            "status": self.status,
            "checkpoint_dir": self.checkpoint_dir,
            "applied_files": list(self.applied_files),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> StoredPlan:
        plan_data = data["plan"]
        plan = SchPlan(
            plan_id=plan_data["plan_id"],
            title=plan_data.get("title", ""),
            components=tuple(
                PlannedComponent(**component) for component in plan_data.get("components", [])
            ),
            labels=tuple(PlannedLabel(**label) for label in plan_data.get("labels", [])),
            nets=tuple(plan_data.get("nets", [])),
            notes=plan_data.get("notes", ""),
        )
        return StoredPlan(
            plan=plan,
            status=data.get("status", "planned"),
            checkpoint_dir=data.get("checkpoint_dir", ""),
            applied_files=tuple(data.get("applied_files", [])),
        )
