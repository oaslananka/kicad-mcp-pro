"""macOS GUI gate must only pass exact native AX observations and integrity."""

import json
from pathlib import Path

import pytest

from scripts import kicad_107_macos_bom_gui as gui


def test_missing_live_ax_output_is_not_qualified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui, "_osa", lambda _script, **_opts: "NO_BOM_OUTPUT_FIELD")
    with pytest.raises(RuntimeError, match="native-bom-output-field-unavailable"):
        gui._read_output()


def test_untrusted_edit_field_is_rejected_before_automation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gui, "_osa", lambda _script, **_opts: pytest.fail("must not invoke GUI for invalid input")
    )
    with pytest.raises(RuntimeError, match="native-bom-saved-value-invalid"):
        gui._edit_output("../../confidential")


def test_mac_bom_gate_fails_closed_on_unverified_native(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "7" * 40)
    (tmp_path / "summary.json").write_text(
        json.dumps({"sourceRevision": "8" * 40, "versionVerified": True, "verdict": "pass"})
    )
    output = tmp_path / "bom-gui.json"
    assert gui.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text())
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert report["status"] == "fail"
    assert report["qualified"] is False
    assert summary["verdict"] == "fail"
    assert summary["macosBomGuiQualified"] is False


def test_mac_bom_gate_only_qualifies_after_native_observations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "7" * 40)
    (tmp_path / "summary.json").write_text(
        json.dumps(
            {
                "sourceRevision": "7" * 40,
                "versionVerified": True,
                "nativeExit": 0,
                "guiExit": 0,
                "verdict": "pass",
            }
        )
    )
    monkeypatch.setattr(
        gui,
        "_run",
        lambda _executable: {
            "observedA": "BOM_SAVED_A_aaaaaaaaaaaa.csv",
            "observedB": "BOM_SAVED_B_aaaaaaaaaaaa.csv",
            "reopenedB": "BOM_SAVED_B_aaaaaaaaaaaa.csv",
            "cancelReverted": True,
            "noBomFilesCreated": True,
            "projectIntegrityVerified": True,
            "nativeGuiObserved": True,
        },
    )
    output = tmp_path / "bom-gui.json"
    assert gui.main(["--output", str(output)]) == 0
    report = json.loads(output.read_text())
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert report["qualified"] is True
    assert report["status"] == "pass"
    assert summary["macosBomGuiQualified"] is True
    assert summary["verdict"] == "pass"
