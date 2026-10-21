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


def test_all_macos_ax_helpers_specify_safe_diagnostic_stage() -> None:
    import ast

    source = Path(gui.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_osa"
    ]
    assert len(calls) == 6
    assert all(any(k.arg == "stage" for k in call.keywords) for call in calls)


def test_bom_edit_is_real_keyboard_interaction_not_ax_value_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def check(script: str, *, stage: str) -> str:
        assert stage == "edit-output"
        observed.append(script)
        return gui.REPLACEMENT

    monkeypatch.setattr(gui, "_osa", check)
    assert gui._edit_output("BOM_SAVED_B_aaaaaaaaaaaa.csv") == gui.REPLACEMENT
    assert len(observed) == 1
    assert "click elementFound" in observed[0]
    assert 'keystroke "a" using {command down}' in observed[0]
    assert 'keystroke "BOM_CANCEL_NOT_PERSISTED_107.csv"' in observed[0]
    assert "set value of elementFound" not in observed[0]


def test_cancel_uses_explicit_native_cancel_button_not_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def command(script: str, *, stage: str) -> str:
        seen.append(script)
        if stage == "cancel":
            return "CANCEL_CLICKED"
        if stage == "windows":
            return "PortableBom107B - Schematic Editor"
        pytest.fail("unexpected AX stage")

    monkeypatch.setattr(gui, "_osa", command)
    monkeypatch.setattr(gui.time, "sleep", lambda _seconds: None)
    gui._cancel()
    assert len(seen) == 2
    assert 'role of elementFound is "AXButton"' in seen[0]
    assert 'theName is "Cancel"' in seen[0]
    assert 'theDescription is "Cancel"' in seen[0]
    assert 'button "Cancel" of window "Symbol Fields Table"' in seen[0]
    assert "key code 53" not in seen[0]


def test_cancel_fails_closed_when_named_button_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gui, "_osa", lambda _script, *, stage: "CANCEL_CONTROL_NOT_FOUND")
    with pytest.raises(RuntimeError, match="native-bom-cancel-control-unavailable"):
        gui._cancel()
