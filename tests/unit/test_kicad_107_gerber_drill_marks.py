"""Fail-closed KiCad 10.0.7 NPTH/PTH Gerber flash regression (#25532)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import scripts.kicad_107_gerber_drill_marks as probe

ROOT = Path(__file__).resolve().parents[2]
GERBER = "%TF.FileFunction,Copper,L1,Top*%\n%FSLAX46Y46*%\nD10*\n{flash}\nM02*"
NPTH_DRILL = (
    "M48\n; #@! TF.FileFunction,NonPlated,1,2,NPTH\nMETRIC\nT1C3.200\n%\nT1\nX50.0Y-50.0\nM30\n"
)


def _files() -> dict[str, str]:
    return {"npth": GERBER.format(flash=""), "pth": GERBER.format(flash="X50000000Y-50000000D03*")}


def test_gerber_np_hole_is_not_flashed_but_pth_pad_is() -> None:
    evidence = probe.validate_gerbers(_files(), NPTH_DRILL)
    assert evidence["schemaVersion"] == "kicad-107-gerber-drill-marks.v1"
    assert evidence["kicadVersion"] == "10.0.7"
    assert evidence["copperFlashCount"] == {"npth": 0, "pth": 1}
    assert evidence["npthDrillMm"] == 3.2
    assert evidence["status"] == "pass"


@pytest.mark.parametrize("control", ["npth", "pth"])
def test_bad_f_cu_flash_regression_is_rejected(control: str) -> None:
    files = _files()
    files[control] = GERBER.format(flash="X50000000Y-50000000D03*" if control == "npth" else "")
    with pytest.raises(probe.ProbeError, match="flash count"):
        probe.validate_gerbers(files, NPTH_DRILL)


@pytest.mark.parametrize(
    "drill",
    [
        "",
        "T1C3.200\nX50.0Y-50.0",
        NPTH_DRILL.replace("T1C3.200", "T1C2.000"),
        NPTH_DRILL.replace("Y-50.0", "Y-51.0"),
    ],
)
def test_missing_or_wrong_npth_drill_data_is_rejected(drill: str) -> None:
    gerbers = _files()
    with pytest.raises(probe.ProbeError, match="NPTH"):
        probe.validate_gerbers(gerbers, drill)


def test_source_boards_preserve_full_drill_plot_option_and_control_geometry() -> None:
    for case in probe.CASES:
        text = (probe.FIXTURES / f"{case}-stored-full-drill.kicad_pcb").read_text()
        assert "(drillshape 2)" in text
        assert "(at 50 50)" in text
        assert "np_thru_hole" in text if case == "npth" else "thru_hole" in text
        assert "(drill 3.2)" in text


def test_wrong_native_version_blocks_plots(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(cli: Path, step: object, artifacts: Path) -> dict[str, object]:
        calls.append(step.args)
        (artifacts / "logs").mkdir(exist_ok=True)
        (artifacts / "logs/gerber-107-version.stdout.log").write_text("10.0.6\n")
        return {"returncode": 0, "ok": True}

    monkeypatch.setattr(probe, "_run_step", fake_run)
    with pytest.raises(probe.ProbeError, match="requires KiCad CLI 10.0.7"):
        probe.run_probe("fake-kicad-cli")
    assert calls == [("version",)]


def test_audited_runner_uses_disposable_copied_board_and_drill(monkeypatch) -> None:
    commands = []

    def fake_run(cli: Path, step: object, artifacts: Path) -> dict[str, object]:
        commands.append(step.args)
        if step.args == ("version",):
            (artifacts / "logs").mkdir(exist_ok=True)
            (artifacts / "logs/gerber-107-version.stdout.log").write_text("10.0.7\n")
        elif step.args[:3] == ("pcb", "export", "gerbers"):
            board = Path(step.args[-1])
            assert board.exists()
            assert board.parent.name in probe.CASES
            assert "--board-plot-params" in step.args
            case = board.parent.name
            file = (
                Path(step.args[step.args.index("--output") + 1])
                / f"{case}-stored-full-drill-F_Cu.gbr"
            )
            file.write_text(_files()[case])
        else:
            assert step.args[:3] == ("pcb", "export", "drill")
            nc = (
                Path(step.args[step.args.index("--output") + 1]) / "npth-stored-full-drill-NPTH.drl"
            )
            nc.write_text(NPTH_DRILL)
        return {"returncode": 0, "ok": True}

    monkeypatch.setattr(probe, "_run_step", fake_run)
    assert probe.run_probe("fake-kicad-cli")["status"] == "pass"
    assert len(commands) == 4


def test_trusted_windows_native_workflow_retains_readonly_manual_gui() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/kicad-10-0-7-windows-qualification.yml").read_text()
    )
    on = workflow.get("on", workflow.get(True))
    assert set(on) == {"push", "schedule", "workflow_dispatch"}
    assert "scripts/kicad_107_gerber_drill_marks.py" in on["push"]["paths"]
    assert workflow["permissions"] == {"contents": "read"}
    steps = workflow["jobs"]["native-windows-cli"]["steps"]
    mark = next(s for s in steps if s["name"] == "Verify 10.0.7 Gerber NPTH drill-mark exclusion")
    assert "scripts/kicad_107_gerber_drill_marks.py" in mark["run"]
    assert "gerber-drill-marks.json" in mark["run"]
    assert "SOURCE_REVISION" in mark["env"]
    gui = yaml.safe_load(
        (ROOT / ".github/workflows/kicad-10-0-7-windows-gui-ipc-qualification.yml").read_text()
    )
    assert gui.get("on", gui.get(True)) == {"workflow_dispatch": None}
