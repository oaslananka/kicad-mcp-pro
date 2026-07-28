"""FastMCP-independent tests for validation policy state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from kicad_mcp.validation.policy_state import ValidationPolicyStateService


def _report_entries(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    value = payload.get(key, [])
    assert isinstance(value, list)
    return cast(list[dict[str, object]], value)


def _service(
    tmp_path: Path, report: dict[str, object] | None = None, error: str | None = None
) -> ValidationPolicyStateService:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    return ValidationPolicyStateService(
        project_dir=lambda: project,
        run_drc_report=lambda _name: (project / "report.json", report, error),
        report_entries=_report_entries,
        now=lambda: datetime(2026, 7, 28, 0, 0, tzinfo=UTC),
    )


def test_drc_exclusion_lifecycle_and_validation(tmp_path: Path) -> None:
    report: dict[str, object] = {
        "violations": [
            {"uuid": "v1", "description": "first"},
            {"uuid": "v2", "description": "second"},
        ]
    }
    service = _service(tmp_path, report)
    assert json.loads(service.list_drc_exclusions()) == {"exclusions": [], "count": 0}
    assert service.add_drc_exclusions("reviewed") == (
        "Added 2 DRC exclusion(s). Total exclusions stored: 2."
    )
    assert service.add_drc_exclusions("reviewed") == (
        "Added 0 DRC exclusion(s). Total exclusions stored: 2."
    )
    listing = json.loads(service.list_drc_exclusions())
    assert listing["count"] == 2
    assert listing["exclusions"][0] == {
        "uuid": "v1",
        "reason": "reviewed",
        "created": "2026-07-28T00:00:00+00:00",
        "description": "first",
    }
    assert service.remove_drc_exclusion("missing") == "No exclusion found with UUID 'missing'."
    assert service.remove_drc_exclusion("v2") == "Removed 1 DRC exclusion (UUID: v2)."
    validation = json.loads(service.validate_drc_exclusions())
    assert validation["total_exclusions"] == 1
    assert validation["valid_exclusions"] == 1
    assert validation["stale_exclusions"] == 0


def test_drc_exclusion_error_and_empty_paths(tmp_path: Path) -> None:
    assert _service(tmp_path, None, "offline").add_drc_exclusions() == "Could not run DRC: offline"
    assert _service(tmp_path, {"violations": []}).add_drc_exclusions() == (
        "No DRC violations found — nothing to exclude."
    )
    service = _service(tmp_path, {"violations": []})
    assert service.validate_drc_exclusions() == "No DRC exclusions stored for the active project."

    report: dict[str, object] = {"violations": [{"uuid": "v1", "description": "first"}]}
    service = _service(tmp_path, report)
    assert service.add_drc_exclusions() == "Added 1 DRC exclusion(s). Total exclusions stored: 1."

    def fail_validation(_name: str) -> tuple[Path | None, dict[str, object] | None, str | None]:
        return None, None, "offline"

    object.__setattr__(service, "run_drc_report", fail_validation)
    assert service.validate_drc_exclusions() == "Could not run DRC: offline"


def test_erc_severity_lifecycle(tmp_path: Path) -> None:
    service = _service(tmp_path)
    listing = json.loads(service.list_erc_rules())
    assert len(listing["rules"]) == 15
    assert all(rule["severity"] == "error" for rule in listing["rules"])
    assert service.set_erc_rule_severity("pin_not_connected", " WARNING ") == (
        "ERC rule 'pin_not_connected' severity set to 'warning'."
    )
    assert service.reset_erc_rules("pin_not_connected") == (
        "ERC rule 'pin_not_connected' reset to default severity (error)."
    )
    assert service.reset_erc_rules() == ("All 15 ERC rules reset to default severity (error).")


def test_erc_validation_errors(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="Severity must be one of"):
        service.set_erc_rule_severity("pin_not_connected", "fatal")
    with pytest.raises(ValueError, match="Unknown ERC rule 'missing'"):
        service.set_erc_rule_severity("missing", "error")
    with pytest.raises(ValueError, match="Unknown ERC rule 'missing'"):
        service.reset_erc_rules("missing")


def test_project_directory_is_required(tmp_path: Path) -> None:
    service = ValidationPolicyStateService(
        project_dir=lambda: None,
        run_drc_report=lambda _name: (None, None, None),
        report_entries=lambda _payload, _key: [],
        now=lambda: datetime.now(UTC),
    )
    with pytest.raises(ValueError, match="No active project is configured"):
        service.list_drc_exclusions()
    with pytest.raises(ValueError, match="No active project is configured"):
        service.list_erc_rules()
