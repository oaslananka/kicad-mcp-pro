"""Persistent DRC exclusion and ERC severity policy state."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

Report = dict[str, object]
ProjectDir = Callable[[], Path | None]
RunDrcReport = Callable[[str], tuple[Path | None, Report | None, str | None]]
ReportEntries = Callable[[Report, str], list[dict[str, object]]]
Now = Callable[[], datetime]

ERC_RULE_NAMES: tuple[str, ...] = (
    "power_pin_not_driven",
    "pin_not_connected",
    "pin_to_pin_warning",
    "unresolved_variable",
    "missing_input_pin_connection",
    "missing_power_pin_connection",
    "missing_power_symbol",
    "bus_conflict",
    "label_conflict",
    "global_label_conflict",
    "hierarchical_label_conflict",
    "duplicate_reference",
    "invalid_reference",
    "extra_units",
    "no_connect_connected",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ValidationPolicyStateService:
    """Manage project-local DRC exclusions and ERC severity overrides."""

    project_dir: ProjectDir
    run_drc_report: RunDrcReport
    report_entries: ReportEntries
    now: Now = _utc_now

    def _state_path(self, filename: str) -> Path:
        project_dir = self.project_dir()
        if project_dir is None:
            raise ValueError("No active project is configured.")
        target = project_dir / ".kicad-mcp"
        target.mkdir(parents=True, exist_ok=True)
        return target / filename

    def _load_drc_exclusions(self) -> dict[str, object]:
        path = self._state_path("drc_exclusions.json")
        if not path.exists():
            payload: dict[str, object] = {"exclusions": []}
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload
        return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))

    def _save_drc_exclusions(self, payload: dict[str, object]) -> Path:
        path = self._state_path("drc_exclusions.json")
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def list_drc_exclusions(self) -> str:
        state = self._load_drc_exclusions()
        exclusions = cast(list[dict[str, object]], state.get("exclusions", []))
        return json.dumps(
            {"exclusions": exclusions, "count": len(exclusions)},
            indent=2,
        )

    def add_drc_exclusions(self, reason: str = "Reviewed — not actionable.") -> str:
        _, report, error = self.run_drc_report("drc_add_exclusion.json")
        if report is None:
            return f"Could not run DRC: {error or 'unknown error'}"
        violations = self.report_entries(report, "violations")
        if not violations:
            return "No DRC violations found — nothing to exclude."

        state = self._load_drc_exclusions()
        existing_uuids = {
            str(exclusion.get("uuid", ""))
            for exclusion in cast(list[dict[str, object]], state.get("exclusions", []))
        }
        exclusions = cast(list[dict[str, object]], state.setdefault("exclusions", []))
        created = self.now().isoformat()
        added = 0
        for violation in violations:
            uuid = str(violation.get("uuid", ""))
            if not uuid or uuid in existing_uuids:
                continue
            exclusions.append(
                {
                    "uuid": uuid,
                    "reason": reason,
                    "created": created,
                    "description": str(violation.get("description", "")),
                }
            )
            existing_uuids.add(uuid)
            added += 1

        self._save_drc_exclusions(state)
        return f"Added {added} DRC exclusion(s). Total exclusions stored: {len(exclusions)}."

    def remove_drc_exclusion(self, uuid: str) -> str:
        state = self._load_drc_exclusions()
        exclusions = cast(list[dict[str, object]], state.get("exclusions", []))
        before = len(exclusions)
        remaining = [
            exclusion for exclusion in exclusions if str(exclusion.get("uuid", "")) != uuid
        ]
        state["exclusions"] = remaining
        removed = before - len(remaining)
        if removed == 0:
            return f"No exclusion found with UUID '{uuid}'."
        self._save_drc_exclusions(state)
        return f"Removed 1 DRC exclusion (UUID: {uuid})."

    def validate_drc_exclusions(self) -> str:
        state = self._load_drc_exclusions()
        exclusions = cast(list[dict[str, object]], state.get("exclusions", []))
        if not exclusions:
            return "No DRC exclusions stored for the active project."

        _, report, error = self.run_drc_report("drc_validate_exclusions.json")
        if report is None:
            return f"Could not run DRC: {error or 'unknown error'}"
        active_uuids = {
            str(violation.get("uuid", ""))
            for violation in self.report_entries(report, "violations")
        }
        valid = [item for item in exclusions if str(item.get("uuid", "")) in active_uuids]
        stale = [item for item in exclusions if str(item.get("uuid", "")) not in active_uuids]
        return json.dumps(
            {
                "total_exclusions": len(exclusions),
                "valid_exclusions": len(valid),
                "stale_exclusions": len(stale),
                "active_violations": len(active_uuids),
                "valid": valid[:20],
                "stale": stale[:20],
            },
            indent=2,
        )

    def _load_erc_severity(self) -> dict[str, str]:
        path = self._state_path("erc_severity.json")
        if not path.exists():
            payload = dict.fromkeys(ERC_RULE_NAMES, "error")
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload
        return cast(dict[str, str], json.loads(path.read_text(encoding="utf-8")))

    def _save_erc_severity(self, payload: dict[str, str]) -> Path:
        path = self._state_path("erc_severity.json")
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def list_erc_rules(self) -> str:
        severity_map = self._load_erc_severity()
        payload = {
            "rules": [
                {"name": name, "severity": severity_map.get(name, "error")}
                for name in ERC_RULE_NAMES
            ]
        }
        return json.dumps(payload, indent=2)

    def set_erc_rule_severity(self, rule_name: str, severity: str) -> str:
        severity_lower = severity.casefold().strip()
        if severity_lower not in {"error", "warning", "ignore"}:
            raise ValueError("Severity must be one of: error, warning, ignore.")
        if rule_name not in ERC_RULE_NAMES:
            raise ValueError(
                f"Unknown ERC rule '{rule_name}'. Available rules: {', '.join(ERC_RULE_NAMES)}"
            )
        state = self._load_erc_severity()
        state[rule_name] = severity_lower
        self._save_erc_severity(state)
        return f"ERC rule '{rule_name}' severity set to '{severity_lower}'."

    def reset_erc_rules(self, rule_name: str | None = None) -> str:
        state = self._load_erc_severity()
        if rule_name:
            if rule_name not in ERC_RULE_NAMES:
                raise ValueError(
                    f"Unknown ERC rule '{rule_name}'. Available rules: {', '.join(ERC_RULE_NAMES)}"
                )
            state[rule_name] = "error"
            self._save_erc_severity(state)
            return f"ERC rule '{rule_name}' reset to default severity (error)."
        for name in ERC_RULE_NAMES:
            state[name] = "error"
        self._save_erc_severity(state)
        return f"All {len(ERC_RULE_NAMES)} ERC rules reset to default severity (error)."
