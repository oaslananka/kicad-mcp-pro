"""Regression guards for the KiCad 10.0.7 ERC JSON unit-scale correction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.kicad_107_erc_units import ProbeError, run_probe, validate_reports

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MM = (15.0, 14.0)
UNITS = {"mm": 1.0, "in": 1 / 25.4, "mils": 1000 / 25.4}


def _report(unit: str, *, scale: float | None = None, x: float = 15.0) -> dict:
    ratio = UNITS[unit] if scale is None else scale
    return {
        "kicad_version": "10.0.7",
        "coordinate_units": unit,
        "sheets": [
            {
                "violations": [
                    {
                        "type": "footprint_link_issues",
                        "items": [
                            {
                                "description": "Symbol J1 [J1]",
                                "pos": {"x": x * ratio, "y": 14.0 * ratio},
                            }
                        ],
                    }
                ]
            }
        ],
    }


def _reports() -> dict[str, dict]:
    return {unit: _report(unit) for unit in UNITS}


def test_exact_coordinate_transforms_and_violation_identity() -> None:
    evidence = validate_reports(_reports())
    assert evidence["schemaVersion"] == "kicad-107-erc-json-units.v1"
    assert evidence["kicadVersion"] == "10.0.7"
    assert evidence["status"] == "pass"
    assert set(evidence["units"]) == set(UNITS)
    assert evidence["units"]["mm"]["x"] == pytest.approx(EXPECTED_MM[0])
    assert evidence["units"]["mm"]["y"] == pytest.approx(EXPECTED_MM[1])
    assert evidence["units"]["in"]["x"] == pytest.approx(15 / 25.4)
    assert evidence["units"]["mils"]["y"] == pytest.approx(14000 / 25.4)
    assert evidence["units"]["mm"]["violationCount"] == 1


@pytest.mark.parametrize("unit", ["in", "mils"])
def test_unit_scale_mismatch_fails_closed(unit: str) -> None:
    reports = _reports()
    reports[unit] = _report(unit, scale=1.0)
    with pytest.raises(ProbeError, match="coordinate"):
        validate_reports(reports)


@pytest.mark.parametrize("unit", ["mm", "in", "mils"])
def test_zero_position_fails_closed(unit: str) -> None:
    reports = _reports()
    reports[unit]["sheets"][0]["violations"][0]["items"][0]["pos"] = {"x": 0, "y": 0}
    with pytest.raises(ProbeError, match="coordinate"):
        validate_reports(reports)


def test_missing_or_ambiguous_j1_violation_fails_closed() -> None:
    reports = _reports()
    reports["in"]["sheets"][0]["violations"] = []
    with pytest.raises(ProbeError, match="J1"):
        validate_reports(reports)
    reports = _reports()
    reports["mm"]["sheets"][0]["violations"].append(reports["mm"]["sheets"][0]["violations"][0])
    with pytest.raises(ProbeError, match="J1"):
        validate_reports(reports)


def test_wrong_cli_version_and_declared_units_fail_closed() -> None:
    reports = _reports()
    reports["in"]["kicad_version"] = "10.0.6"
    with pytest.raises(ProbeError, match="version"):
        validate_reports(reports)
    reports = _reports()
    reports["mils"]["coordinate_units"] = "mm"
    with pytest.raises(ProbeError, match="units"):
        validate_reports(reports)


def test_native_cli_uses_audited_runner_and_an_isolated_fixture(monkeypatch) -> None:
    import scripts.kicad_107_erc_units as script

    invocations: list[tuple[str, ...]] = []

    def fake_step(cli: Path, step: object, artifacts: Path) -> dict[str, object]:
        args = step.args
        invocations.append(args)
        if args == ("version",):
            logs = artifacts / "logs"
            logs.mkdir(exist_ok=True)
            (logs / "kicad-107-version.stdout.log").write_text("10.0.7\n")
            return {"returncode": 0, "ok": True}
        assert args[:2] == ("sch", "erc")
        assert "--exit-code-violations" in args
        assert "--format" in args
        assert args[args.index("--format") + 1] == "json"
        unit = args[args.index("--units") + 1]
        output = Path(args[args.index("--output") + 1])
        source = Path(args[-1])
        assert source.exists()
        assert (
            source
            != ROOT
            / "packages/kicad-fixtures/fixtures/erc-power-pin-error/erc-power-pin-error.kicad_sch"
        )
        output.write_text(json.dumps(_report(unit)), encoding="utf-8")
        return {"returncode": 5, "ok": True}

    monkeypatch.setattr(script, "_run_step", fake_step)
    evidence = run_probe("fake-kicad-cli")
    assert evidence["status"] == "pass"
    assert len(invocations) == 4


def test_unexpected_native_exit_code_is_a_failure(monkeypatch) -> None:
    import scripts.kicad_107_erc_units as script

    def fake_step(cli: Path, step: object, artifacts: Path) -> dict[str, object]:
        if step.args == ("version",):
            logs = artifacts / "logs"
            logs.mkdir(exist_ok=True)
            (logs / "kicad-107-version.stdout.log").write_text("10.0.7\n")
            return {"returncode": 0, "ok": True}
        return {"returncode": 0, "ok": False}

    monkeypatch.setattr(script, "_run_step", fake_step)
    with pytest.raises(ProbeError, match="exit code"):
        run_probe("fake-kicad-cli")


def test_version_gating_is_enforced_before_erc(monkeypatch) -> None:
    import scripts.kicad_107_erc_units as script

    def fake_step(cli: Path, step: object, artifacts: Path) -> dict[str, object]:
        assert step.args == ("version",)
        logs = artifacts / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "kicad-107-version.stdout.log").write_text("10.0.6\n")
        return {"returncode": 0, "ok": True}

    monkeypatch.setattr(script, "_run_step", fake_step)
    with pytest.raises(ProbeError, match="version"):
        run_probe("fake-kicad-cli")


def test_windows_107_auto_lane_executes_regression_and_preserves_gui_boundary() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/kicad-10-0-7-windows-qualification.yml").read_text()
    )
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"push", "schedule", "workflow_dispatch"}
    assert "scripts/kicad_107_erc_units.py" in events["push"]["paths"]
    steps = workflow["jobs"]["native-windows-cli"]["steps"]
    native_index = next(
        i for i, step in enumerate(steps) if step["name"].startswith("Run full native")
    )
    regression_index = next(
        i
        for i, step in enumerate(steps)
        if step["name"] == "Verify 10.0.7 ERC JSON unit-scale semantics"
    )
    assert regression_index > native_index
    assert "scripts/kicad_107_erc_units.py" in steps[regression_index]["run"]
    assert "erc-units.json" in steps[regression_index]["run"]
    gui = yaml.safe_load(
        (ROOT / ".github/workflows/kicad-10-0-7-windows-gui-ipc-qualification.yml").read_text()
    )
    assert gui.get("on", gui.get(True)) == {"workflow_dispatch": None}
